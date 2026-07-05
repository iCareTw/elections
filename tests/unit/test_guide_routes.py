"""
Tests for Phase 5 voter-guide web UI routes (Tasks 5.1–5.4).

Structure:
- Template-only tests (Jinja2 direct render, no HTTP, no DB)
- Mock-store route tests (TestClient + in-memory store, no DB)
- DB integration tests (real DB, skip if unreachable) for 5.1 seeding
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader

from src.webapp.app import create_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "src" / "webapp" / "templates"


def _make_guide_app(tmp_path: Path, store: Any) -> Any:
    app = create_app(root=tmp_path)
    app.state.store = store
    return app


def _render_candidate(
    *,
    candidate: dict,
    fields: list[dict],
    has_uncommitted: bool = False,
    latest_version: int = 1,
    version_no: int = 1,
    min_version: int = 1,
    max_version: int = 1,
    readonly: bool = False,
    tree: list | None = None,
    candidates: list | None = None,
    selected_candidate_id: int | None = None,
    selected_election_id: str | None = None,
) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("guide/candidate.html")
    return template.render(
        tree=tree or [],
        selected_election_id=selected_election_id,
        candidates=candidates or [],
        selected_candidate_id=selected_candidate_id,
        candidate=candidate,
        fields=fields,
        has_uncommitted=has_uncommitted,
        latest_version=latest_version,
        version_no=version_no,
        min_version=min_version,
        max_version=max_version,
        readonly=readonly,
    )


def _render_index(
    *,
    tree: list | None = None,
    selected_election_id: str | None = None,
    candidates: list | None = None,
    selected_candidate_id: int | None = None,
) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("guide/index.html")
    return template.render(
        tree=tree or [],
        selected_election_id=selected_election_id,
        candidates=candidates or [],
        selected_candidate_id=selected_candidate_id,
    )


# ---------------------------------------------------------------------------
# Fixtures: fake store implementations
# ---------------------------------------------------------------------------

_TREE = [
    {
        "type": "president",
        "elections": [
            {"id": "president_2024_16", "label": "第16任 2024 總統", "year": 2024, "session": 16}
        ],
    }
]

_CANDIDATES = [
    {
        "id": 1,
        "ticket": 1,
        "role": "總統",
        "party": "民主進步黨",
        "name": "蔡英文",
        "photo_flagged": False,
        "any_flag": False,
        "order_id": 1,
    },
    {
        "id": 2,
        "ticket": 1,
        "role": "副總統",
        "party": "民主進步黨",
        "name": "賴清德",
        "photo_flagged": False,
        "any_flag": True,  # has a flag → orange dot
        "order_id": 2,
    },
]

_BASE_CANDIDATE_META = {
    "id": 1,
    "ticket": 1,
    "role": "總統",
    "party": "民主進步黨",
    "gender": "女",
    "photo_path": None,
    "photo_flagged": False,
    "photo_note": None,
    "source_page": 0,
    "election_id": "president_2024_16",
    "election_label": "第16任 2024 總統",
    "name": "蔡英文",
}

_BASE_FIELDS = [
    {
        "id": 10,
        "field_name": "姓名",
        "value": "蔡英文",
        "grade": "完全一致",
        "source_crop_path": None,
        "flagged": False,
        "flag_note": None,
        "can_ai_repair": False,
    },
    {
        "id": 11,
        "field_name": "學歷",
        "value": "法學博士",
        "grade": "完全一致",
        "source_crop_path": "/fake/_out/crop_學歷.png",
        "flagged": False,
        "flag_note": None,
        "can_ai_repair": True,
    },
]


class TreeOnlyStore:
    """Minimal store: only guide_tree."""

    def guide_tree(self) -> list:
        return _TREE


class GuideIndexStore:
    """Store for index view tests (guide_tree + guide_candidates_of)."""

    def guide_tree(self) -> list:
        return _TREE

    def guide_candidates_of(self, election_id: str) -> list:
        return _CANDIDATES


class StatefulGuideStore:
    """In-memory stateful store for action tests (5.3, 5.4)."""

    def __init__(self) -> None:
        import copy

        self._fields: list[dict] = copy.deepcopy(_BASE_FIELDS)
        self._field_by_id: dict[int, dict] = {f["id"]: f for f in self._fields}
        self._meta: dict = dict(_BASE_CANDIDATE_META)
        self._snapshot_val: dict[str, str | None] = {
            f["field_name"]: f["value"] for f in self._fields
        }
        self._snapshot_flag: dict[str, bool] = {
            f["field_name"]: False for f in self._fields
        }
        self._version: int = 1

    # ---- read methods ----

    def guide_tree(self) -> list:
        return _TREE

    def guide_candidates_of(self, election_id: str) -> list:
        return _CANDIDATES

    def guide_candidate_view(self, candidate_id: int) -> dict:
        has_uncommitted = any(
            f["value"] != self._snapshot_val.get(f["field_name"])
            or f["flagged"] != self._snapshot_flag.get(f["field_name"], False)
            for f in self._fields
        ) or self._meta.get("photo_flagged", False)
        import copy

        return {
            "candidate": dict(self._meta),
            "fields": copy.deepcopy(self._fields),
            "has_uncommitted": has_uncommitted,
            "latest_version": self._version,
        }

    def guide_snapshot_view(self, candidate_id: int, version_no: int) -> dict:
        return {
            "fields": [
                {
                    "field_name": fn,
                    "value": val,
                    "grade": "完全一致",
                    "source_crop_path": None,
                    "flagged": self._snapshot_flag.get(fn, False),
                    "flag_note": None,
                }
                for fn, val in self._snapshot_val.items()
            ],
            "version_no": version_no,
            "min_version": 1,
            "max_version": self._version,
        }

    # ---- mutation methods ----

    def guide_flag_field(self, field_id: int, note: str) -> None:
        f = self._field_by_id[field_id]
        f["flagged"] = True
        f["flag_note"] = note

    def guide_unflag_field(self, field_id: int) -> None:
        f = self._field_by_id[field_id]
        f["flagged"] = False
        f["flag_note"] = None

    def guide_set_field_value(self, field_id: int, value: str) -> None:
        f = self._field_by_id[field_id]
        f["value"] = value
        f["grade"] = None

    def guide_flag_photo(self, candidate_id: int, note: str) -> None:
        self._meta["photo_flagged"] = True
        self._meta["photo_note"] = note

    def guide_unflag_photo(self, candidate_id: int) -> None:
        self._meta["photo_flagged"] = False
        self._meta["photo_note"] = None

    def guide_commit(self, candidate_id: int, note: str | None = None) -> int:
        self._snapshot_val = {f["field_name"]: f["value"] for f in self._fields}
        self._snapshot_flag = {f["field_name"]: f["flagged"] for f in self._fields}
        self._version += 1
        return self._version

    def guide_discard(self, candidate_id: int) -> None:
        for f in self._fields:
            fn = f["field_name"]
            f["value"] = self._snapshot_val.get(fn)
            f["flagged"] = self._snapshot_flag.get(fn, False)
            f["flag_note"] = None


# ===========================================================================
# Task 5.1 — router skeleton + three-column shell
# ===========================================================================


def test_guide_home_returns_200_with_tree(tmp_path: Path) -> None:
    """GET /guide → 200, left tree rendered from guide_tree()."""
    app = _make_guide_app(tmp_path, TreeOnlyStore())
    client = TestClient(app, raise_server_exceptions=True)

    resp = client.get("/guide")

    assert resp.status_code == 200
    assert "選舉公報資料庫" in resp.text
    assert "president" in resp.text or "第16任" in resp.text


def test_guide_election_returns_200_with_candidates(tmp_path: Path) -> None:
    """GET /guide/election/{id} → 200, candidate rail shown."""
    app = _make_guide_app(tmp_path, GuideIndexStore())
    client = TestClient(app, raise_server_exceptions=True)

    resp = client.get("/guide/election/president_2024_16")

    assert resp.status_code == 200
    assert "蔡英文" in resp.text
    assert "賴清德" in resp.text


def test_guide_election_shows_orange_dot_for_flagged(tmp_path: Path) -> None:
    """Candidate with any_flag=True should render the orange dot class."""
    app = _make_guide_app(tmp_path, GuideIndexStore())
    client = TestClient(app, raise_server_exceptions=True)

    resp = client.get("/guide/election/president_2024_16")

    assert resp.status_code == 200
    # orange dot for 賴清德 (any_flag=True)
    assert "dot warn" in resp.text


def test_guide_home_db(tmp_path: Path) -> None:
    """DB smoke test: GET /guide returns 200. Skip if DB unreachable."""
    from src.webapp.store import Store, load_database_config

    config = load_database_config()
    if not config.database_url:
        pytest.skip("PostgreSQL connection not configured")

    store = Store(config)
    try:
        store.open()
    except Exception:
        pytest.skip("PostgreSQL is not reachable")

    try:
        store.init_schema()
        app = _make_guide_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)

        resp = client.get("/guide")
        assert resp.status_code == 200
        assert "選舉公報資料庫" in resp.text
    finally:
        store.close()


def test_guide_election_db(tmp_path: Path) -> None:
    """DB smoke test: load_guide seed → GET /guide/election/{id} shows candidates."""
    from src.webapp.store import Store, load_database_config
    from src.voter_guide.guide_load import load_guide

    config = load_database_config()
    if not config.database_url:
        pytest.skip("PostgreSQL connection not configured")

    store = Store(config)
    try:
        store.open()
    except Exception:
        pytest.skip("PostgreSQL is not reachable")

    try:
        store.init_schema()
        election_id = _seed_guide(store, tmp_path)

        app = _make_guide_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)

        resp = client.get(f"/guide/election/{election_id}")
        assert resp.status_code == 200
        assert "蔡英文" in resp.text
        assert "賴清德" in resp.text
    finally:
        try:
            store.guide_delete_election(election_id)
        except Exception:
            pass
        store.close()


# ===========================================================================
# Task 5.2 — candidate field panel tests
# ===========================================================================


class TestGenderIconLogic:
    """Template test: gender icon rendered based on candidate.gender."""

    def _make_candidate(self, gender: str | None) -> dict:
        return {**_BASE_CANDIDATE_META, "gender": gender}

    def test_male_shows_g_m_class(self) -> None:
        html = _render_candidate(
            candidate=self._make_candidate("男"),
            fields=[{**_BASE_FIELDS[0], "field_name": "姓名"}],
        )
        assert '<span class="gicon g-m">' in html

    def test_female_shows_g_f_class(self) -> None:
        html = _render_candidate(
            candidate=self._make_candidate("女"),
            fields=[{**_BASE_FIELDS[0], "field_name": "姓名"}],
        )
        assert '<span class="gicon g-f">' in html

    def test_none_gender_shows_no_icon(self) -> None:
        html = _render_candidate(
            candidate=self._make_candidate(None),
            fields=[{**_BASE_FIELDS[0], "field_name": "姓名"}],
        )
        # CSS defines .g-m/.g-f but the <span> elements should not be rendered
        assert '<span class="gicon g-m">' not in html
        assert '<span class="gicon g-f">' not in html

    def test_other_gender_shows_no_icon(self) -> None:
        html = _render_candidate(
            candidate=self._make_candidate("其他"),
            fields=[{**_BASE_FIELDS[0], "field_name": "姓名"}],
        )
        assert '<span class="gicon g-m">' not in html
        assert '<span class="gicon g-f">' not in html


class TestUncommittedBanner:
    """Template test: yellow banner toggles on has_uncommitted."""

    def test_banner_shown_when_uncommitted(self) -> None:
        html = _render_candidate(
            candidate=_BASE_CANDIDATE_META,
            fields=_BASE_FIELDS,
            has_uncommitted=True,
        )
        assert "建立快照" in html
        assert "uncommit" in html

    def test_banner_hidden_when_committed(self) -> None:
        html = _render_candidate(
            candidate=_BASE_CANDIDATE_META,
            fields=_BASE_FIELDS,
            has_uncommitted=False,
        )
        assert "建立快照" not in html

    def test_no_banner_in_readonly_mode(self) -> None:
        html = _render_candidate(
            candidate=_BASE_CANDIDATE_META,
            fields=_BASE_FIELDS,
            has_uncommitted=True,  # even if True, readonly suppresses banner
            readonly=True,
        )
        assert "建立快照" not in html


class TestAiRepairButtonGate:
    """AI 修復 button must NOT appear when can_ai_repair == False."""

    def test_no_ai_button_when_no_crop(self) -> None:
        field_no_crop = {
            **_BASE_FIELDS[0],
            "flagged": True,
            "flag_note": "問題",
            "can_ai_repair": False,
        }
        html = _render_candidate(
            candidate=_BASE_CANDIDATE_META,
            fields=[field_no_crop],
        )
        assert "AI 修復" not in html

    def test_ai_button_present_when_crop_exists(self) -> None:
        field_with_crop = {
            **_BASE_FIELDS[1],
            "flagged": True,
            "flag_note": "問題",
            "can_ai_repair": True,
        }
        html = _render_candidate(
            candidate=_BASE_CANDIDATE_META,
            fields=[field_with_crop],
        )
        assert "AI 修復" in html


class TestCropRoutePathSafety:
    """Crop route rejects paths outside project _out/ directory."""

    def test_rejects_absolute_path_outside_out(self, tmp_path: Path) -> None:
        app = _make_guide_app(tmp_path, TreeOnlyStore())
        client = TestClient(app, raise_server_exceptions=True)

        resp = client.get("/guide/crop?path=/etc/passwd")
        assert resp.status_code == 403

    def test_rejects_traversal_path(self, tmp_path: Path) -> None:
        app = _make_guide_app(tmp_path, TreeOnlyStore())
        client = TestClient(app, raise_server_exceptions=True)

        # A relative path that resolves outside _out/
        resp = client.get("/guide/crop?path=../../etc/passwd")
        assert resp.status_code == 403

    def test_missing_file_inside_out_returns_404(self, tmp_path: Path) -> None:
        """Valid path under _out/ but file absent → 404, not 403."""
        app = _make_guide_app(tmp_path, TreeOnlyStore())
        client = TestClient(app, raise_server_exceptions=True)

        out_dir = tmp_path / "_out"
        out_dir.mkdir()
        nonexistent = out_dir / "nonexistent.png"

        resp = client.get(f"/guide/crop?path={nonexistent}")
        assert resp.status_code == 404

    def test_file_inside_out_served(self, tmp_path: Path) -> None:
        """Valid file under _out/ is served (200)."""
        app = _make_guide_app(tmp_path, TreeOnlyStore())
        client = TestClient(app, raise_server_exceptions=True)

        out_dir = tmp_path / "_out"
        out_dir.mkdir()
        crop_file = out_dir / "test_crop.png"
        crop_file.write_bytes(b"\x89PNG_FAKE")

        resp = client.get(f"/guide/crop?path={crop_file}")
        assert resp.status_code == 200


# ===========================================================================
# Task 5.3 — 標記 / 手動填值 / 解除 POST actions
# ===========================================================================


class TestPostFlagField:
    def test_flag_redirects_to_candidate(self, tmp_path: Path) -> None:
        store = StatefulGuideStore()
        app = _make_guide_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)

        resp = client.post(
            "/guide/field/11/flag",
            data={"note": "學歷有誤", "candidate_id": "1"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/guide/candidate/1"

    def test_flag_then_redirect_shows_flagged_state(self, tmp_path: Path) -> None:
        store = StatefulGuideStore()
        app = _make_guide_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)

        client.post(
            "/guide/field/11/flag",
            data={"note": "學歷有誤", "candidate_id": "1"},
        )
        resp = client.get("/guide/candidate/1")

        assert resp.status_code == 200
        assert "已標記" in resp.text
        assert "學歷有誤" in resp.text


class TestPostUnflagField:
    def test_unflag_redirects(self, tmp_path: Path) -> None:
        store = StatefulGuideStore()
        # Pre-flag field 11
        store.guide_flag_field(11, "test note")

        app = _make_guide_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)

        resp = client.post(
            "/guide/field/11/unflag",
            data={"candidate_id": "1"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/guide/candidate/1"

    def test_unflag_clears_flag(self, tmp_path: Path) -> None:
        store = StatefulGuideStore()
        store.guide_flag_field(11, "test note")

        app = _make_guide_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)

        client.post("/guide/field/11/unflag", data={"candidate_id": "1"})
        resp = client.get("/guide/candidate/1")

        assert resp.status_code == 200
        assert "已標記" not in resp.text


class TestPostSetFieldValue:
    def test_value_change_redirects(self, tmp_path: Path) -> None:
        store = StatefulGuideStore()
        app = _make_guide_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)

        resp = client.post(
            "/guide/field/10/value",
            data={"value": "新姓名", "candidate_id": "1"},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    def test_value_change_shows_new_value_and_uncommitted(self, tmp_path: Path) -> None:
        store = StatefulGuideStore()
        app = _make_guide_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)

        client.post("/guide/field/10/value", data={"value": "新姓名", "candidate_id": "1"})
        resp = client.get("/guide/candidate/1")

        assert resp.status_code == 200
        assert "新姓名" in resp.text
        # has_uncommitted=True → banner
        assert "建立快照" in resp.text


class TestPostPhotoFlag:
    def test_photo_flag_redirects(self, tmp_path: Path) -> None:
        store = StatefulGuideStore()
        app = _make_guide_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)

        resp = client.post(
            "/guide/candidate/1/photo/flag",
            data={"note": "照片抓錯"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/guide/candidate/1"

    def test_photo_flag_shows_flagged_state(self, tmp_path: Path) -> None:
        store = StatefulGuideStore()
        app = _make_guide_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)

        client.post("/guide/candidate/1/photo/flag", data={"note": "照片抓錯"})
        resp = client.get("/guide/candidate/1")

        assert resp.status_code == 200
        # The photo row should show flagged state
        assert "已標記" in resp.text
        assert "照片抓錯" in resp.text


class TestPostPhotoUnflag:
    def test_photo_unflag(self, tmp_path: Path) -> None:
        store = StatefulGuideStore()
        store.guide_flag_photo(1, "照片抓錯")

        app = _make_guide_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)

        resp = client.post(
            "/guide/candidate/1/photo/unflag",
            follow_redirects=False,
        )
        assert resp.status_code == 303


# ===========================================================================
# Task 5.4 — commit / discard / version ◀▶
# ===========================================================================


class TestCommit:
    def test_commit_increments_version(self, tmp_path: Path) -> None:
        store = StatefulGuideStore()
        store.guide_set_field_value(10, "修改後值")  # create uncommitted change

        app = _make_guide_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)

        # Commit
        resp = client.post(
            "/guide/candidate/1/commit",
            data={"note": ""},
            follow_redirects=False,
        )
        assert resp.status_code == 303

        # After commit: banner gone, version is 2
        resp = client.get("/guide/candidate/1")
        assert resp.status_code == 200
        assert "建立快照" not in resp.text  # banner gone
        assert "v2" in resp.text


class TestDiscard:
    def test_discard_reverts_changes(self, tmp_path: Path) -> None:
        store = StatefulGuideStore()
        original_value = store._fields[0]["value"]  # "蔡英文"
        store.guide_set_field_value(10, "錯誤值")

        app = _make_guide_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)

        # Verify change is visible (has banner)
        resp = client.get("/guide/candidate/1")
        assert "建立快照" in resp.text
        assert "錯誤值" in resp.text

        # Discard
        resp = client.post("/guide/candidate/1/discard", follow_redirects=False)
        assert resp.status_code == 303

        # After discard: reverted, banner gone
        resp = client.get("/guide/candidate/1")
        assert resp.status_code == 200
        assert "建立快照" not in resp.text
        assert original_value in resp.text

    def test_discard_redirects(self, tmp_path: Path) -> None:
        store = StatefulGuideStore()
        app = _make_guide_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)

        resp = client.post("/guide/candidate/1/discard", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/guide/candidate/1"


class TestVersionNav:
    def test_snapshot_view_is_readonly(self, tmp_path: Path) -> None:
        """GET ?version=1 → no 建立快照 banner, no flag buttons."""
        store = StatefulGuideStore()

        app = _make_guide_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)

        resp = client.get("/guide/candidate/1?version=1")
        assert resp.status_code == 200
        assert "建立快照" not in resp.text
        assert "⚑ 標記" not in resp.text  # action buttons absent in readonly

    def test_snapshot_view_shows_version_label(self, tmp_path: Path) -> None:
        store = StatefulGuideStore()
        app = _make_guide_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)

        resp = client.get("/guide/candidate/1?version=1")
        assert resp.status_code == 200
        assert "v1" in resp.text

    def test_version_nav_prev_arrow_disabled_at_min(self) -> None:
        """At version 1 (min), ◀ arrow is disabled."""
        html = _render_candidate(
            candidate=_BASE_CANDIDATE_META,
            fields=_BASE_FIELDS,
            version_no=1,
            min_version=1,
            max_version=2,
            readonly=True,
        )
        # ◀ should be dim (disabled) since version_no == min_version
        assert 'arw dim' in html

    def test_version_nav_next_arrow_disabled_in_working_view(self) -> None:
        """In latest working view (non-readonly), ▶ is always disabled."""
        html = _render_candidate(
            candidate=_BASE_CANDIDATE_META,
            fields=_BASE_FIELDS,
            version_no=2,
            min_version=1,
            max_version=2,
            readonly=False,
        )
        # ▶ should be dim (at latest)
        assert 'arw dim' in html

    def test_version_nav_next_arrow_enabled_when_snapshot_has_next(self) -> None:
        """In a snapshot view where version_no < max_version, ▶ is a real link."""
        html = _render_candidate(
            candidate=_BASE_CANDIDATE_META,
            fields=_BASE_FIELDS,
            version_no=1,
            min_version=1,
            max_version=2,
            readonly=True,
        )
        # At v1 of 2, ▶ should be an active link (not dim)
        assert 'href="/guide/candidate/1?version=2"' in html

    def test_mutate_commit_shows_version_2(self, tmp_path: Path) -> None:
        store = StatefulGuideStore()
        store.guide_set_field_value(10, "新值")  # create uncommitted

        app = _make_guide_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)

        # Before commit: v1 + 未提交
        resp = client.get("/guide/candidate/1")
        assert "v1" in resp.text
        assert "未提交" in resp.text

        # Commit
        client.post("/guide/candidate/1/commit", data={"note": ""})

        # After commit: v2, no 未提交
        resp = client.get("/guide/candidate/1")
        assert "v2" in resp.text
        assert "未提交" not in resp.text
        assert "建立快照" not in resp.text


# ===========================================================================
# Shared seed helper for DB tests
# ===========================================================================


def _seed_guide(store: Any, tmp_path: Path) -> str:
    """Seed a minimal guide election for DB integration tests."""
    from src.voter_guide.guide_load import load_guide

    data = [
        {
            "號次": 1,
            "總統": {
                "姓名": "蔡英文",
                "出生年月日": "民國46年8月31日",
                "性別": "女",
                "學歷": "法學博士",
                "經歷": "總統",
                "頁碼": 0,
            },
            "副總統": {
                "姓名": "賴清德",
                "出生年月日": "民國48年10月6日",
                "性別": "男",
                "學歷": "公共衛生碩士",
                "經歷": "行政院長",
                "頁碼": 0,
            },
            "政黨": "民主進步黨",
            "_verify": {
                "總統": {
                    fn: {"grade": "完全一致"}
                    for fn in ["姓名", "出生年月日", "性別", "學歷", "經歷"]
                },
                "副總統": {
                    fn: {"grade": "完全一致"}
                    for fn in ["姓名", "出生年月日", "性別", "學歷", "經歷"]
                },
            },
        }
    ]

    yaml_path = tmp_path / "guide.yaml"
    yaml_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    crops_dir = tmp_path / "crops"
    crops_dir.mkdir(exist_ok=True)

    return load_guide(
        store,
        yaml_path=yaml_path,
        source_pdf_path=Path("/fake/113年第16任總統副總統.pdf"),
        crops_base_dir=crops_dir,
        election_type="president",
        force=True,
    )


# ---------------------------------------------------------------------------
# Task 6.2 — 文字欄 AI 修復 觸發 + 狀態輪詢
# ---------------------------------------------------------------------------

class _MockRepairStore:
    def __init__(self):
        self.jobs: dict = {}
        self._next = 1
        self.fields = {
            7: {"guide_candidate_id": 3, "field_name": "學歷",
                "source_crop_path": "/x/crop.png"},
        }

    def guide_field_ref(self, field_id: int):
        return self.fields.get(field_id)

    def guide_create_repair_job(self, candidate_id: int, target: str, user_note=None) -> int:
        jid = self._next
        self._next += 1
        self.jobs[jid] = {
            "id": jid, "guide_candidate_id": candidate_id, "target": target,
            "status": "queued", "user_note": user_note,
            "before_value": None, "result_value": None, "error": None,
        }
        return jid

    def guide_get_repair_job(self, job_id: int):
        return self.jobs.get(job_id)


class TestRepairRoutes:
    def test_repair_creates_job_and_redirects(self, tmp_path: Path, monkeypatch) -> None:
        import src.webapp.routes.guide as guidemod

        store = _MockRepairStore()

        def fake_run(store, job_id):           # 背景作業:決定性地標為 done
            j = store.jobs[job_id]
            j["status"] = "done"
            j["result_value"] = "法學博士"

        monkeypatch.setattr(guidemod, "run_repair_job", fake_run)

        app = _make_guide_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)

        r = client.post("/guide/field/7/repair",
                        data={"candidate_id": 3, "note": "學歷讀錯了"},
                        follow_redirects=False)
        assert r.status_code == 303
        assert "repair_job=1" in r.headers["location"]
        assert store.jobs[1]["user_note"] == "學歷讀錯了"

        s = client.get("/guide/repair/1/status")
        assert s.status_code == 200
        body = s.json()
        assert body["status"] == "done"
        assert body["result_value"] == "法學博士"
        assert body["target"] == "學歷"

    def test_repair_rejects_field_without_crop(self, tmp_path: Path) -> None:
        store = _MockRepairStore()
        store.fields[7]["source_crop_path"] = None
        app = _make_guide_app(tmp_path, store)
        client = TestClient(app, raise_server_exceptions=True)
        r = client.post("/guide/field/7/repair",
                        data={"candidate_id": 3, "note": ""},
                        follow_redirects=False)
        assert r.status_code == 400

    def test_status_404_for_unknown_job(self, tmp_path: Path) -> None:
        app = _make_guide_app(tmp_path, _MockRepairStore())
        client = TestClient(app, raise_server_exceptions=True)
        assert client.get("/guide/repair/999/status").status_code == 404
