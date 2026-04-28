from __future__ import annotations

import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

from src.normalize import generate_id
from src.webapp.build_candidates import write_candidates_yaml
from src.webapp.discovery import discover_elections, load_election_records
from src.webapp.matching import classify_record
from src.webapp.store import Store


ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = Path(__file__).resolve().parent / "static"
DEFAULT_PORT = 23088


def _load_candidates(root: Path) -> list[dict]:
    path = root / "candidates.yaml"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or []


class ElectionAPI:
    def __init__(self, root: Path, store: Store | None = None) -> None:
        self.root = root
        self.store = store or Store()
        self.store.init_schema()

    def handle_json(self, method: str, path: str, body: dict | None = None) -> object:
        parsed = urlparse(path)
        route = parsed.path
        query = parse_qs(parsed.query)

        if method == "GET" and route == "/api/elections":
            return self.list_elections()
        if method == "POST" and route == "/api/elections/load":
            return self.load_election((body or {})["election_id"])
        if method == "GET" and route == "/api/review-items":
            return self.list_review_items(query["election_id"][0])
        if method == "POST" and route == "/api/resolutions":
            return self.save_resolution(body or {})
        if method == "POST" and route == "/api/build":
            return self.build_candidates()

        raise KeyError(route)

    def _discover_and_persist(self) -> list[dict]:
        elections = discover_elections(self.root)
        for election in elections:
            self.store.upsert_election(election)
        return elections

    def _find_election(self, election_id: str) -> dict:
        for election in self._discover_and_persist():
            if election["election_id"] == election_id:
                return election
        raise KeyError(election_id)

    def list_elections(self) -> list[dict]:
        self._discover_and_persist()
        return self.store.list_elections()

    def load_election(self, election_id: str) -> dict:
        election = self._find_election(election_id)
        candidates = _load_candidates(self.root)
        imported = auto = manual = 0

        for record in load_election_records(election):
            imported += 1
            self.store.insert_source_record(
                source_record_id=record["source_record_id"],
                election_id=election_id,
                payload=record,
            )
            result = classify_record(record, candidates)
            if result["kind"] in {"auto", "new"}:
                auto += 1
                self.store.save_resolution(
                    election_id=election_id,
                    source_record_id=record["source_record_id"],
                    candidate_id=result["candidate_id"],
                    mode=result["kind"],
                )
            else:
                manual += 1

        self.store.append_operation_log(
            election_id=election_id,
            action="load_election",
            payload={"imported": imported, "auto": auto, "manual": manual},
        )
        return {"election_id": election_id, "imported": imported, "auto": auto, "manual": manual}

    def list_review_items(self, election_id: str) -> list[dict]:
        candidates = _load_candidates(self.root)
        items = []
        for row in self.store.list_unresolved_records(election_id):
            record = dict(row["payload"])
            result = classify_record(record, candidates)
            items.append(
                {
                    "source_record_id": row["source_record_id"],
                    "election_id": row["election_id"],
                    "record": record,
                    "matches": result.get("matches", []),
                }
            )
        return items

    def save_resolution(self, body: dict) -> dict:
        source_record_id = body["source_record_id"]
        election_id = body["election_id"]
        mode = body["mode"]
        candidate_id = body.get("candidate_id")

        if mode == "new" and not candidate_id:
            source = self.store.get_source_record(source_record_id)
            if source is None:
                raise KeyError(source_record_id)
            candidate_id = generate_id(source["name"], source["birthday"])

        self.store.save_resolution(
            election_id=election_id,
            source_record_id=source_record_id,
            candidate_id=candidate_id,
            mode=mode,
        )
        self.store.append_operation_log(
            election_id=election_id,
            source_record_id=source_record_id,
            action="save_resolution",
            payload={"mode": mode, "candidate_id": candidate_id},
        )
        return {"ok": True, "source_record_id": source_record_id, "candidate_id": candidate_id, "mode": mode}

    def build_candidates(self) -> dict:
        rows = write_candidates_yaml(
            self.store,
            self.root / "candidates.yaml",
            self.root / "election_types.yaml",
        )
        self.store.append_operation_log(action="build_candidates", payload={"count": len(rows)})
        return {"ok": True, "count": len(rows)}


def build_api(root: Path = ROOT, store: Store | None = None) -> ElectionAPI:
    return ElectionAPI(root, store)


class Handler(SimpleHTTPRequestHandler):
    api: ElectionAPI | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self) -> None:
        if self.path.startswith("/api/"):
            self._handle_api("GET")
            return
        super().do_GET()

    def do_POST(self) -> None:
        self._handle_api("POST")

    def _handle_api(self, method: str) -> None:
        try:
            if self.api is None:
                self.__class__.api = build_api(ROOT)
            body = None
            if method == "POST":
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                body = json.loads(raw.decode("utf-8"))
            data = self.api.handle_json(method, self.path, body)
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as exc:
            payload = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)


def main() -> None:
    api = build_api(ROOT)
    api.store.validate_connection()

    Handler.api = api
    server = ThreadingHTTPServer(("127.0.0.1", DEFAULT_PORT), Handler)
    print(f"Serving election identity UI at http://127.0.0.1:{DEFAULT_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
