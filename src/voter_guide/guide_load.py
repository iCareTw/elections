"""匯入選舉公報解析產物到 guide_* DB 資料表，並建立 v1 snapshot。"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from src.voter_guide.pipeline import BASIC_SUBFIELDS, PERSON_FIELDS, crop_filename


class GuideElectionExists(Exception):
    pass


def load_guide(
    store,
    *,
    yaml_path,
    source_pdf_path,
    crops_base_dir,
    election_type: str = "president",
    force: bool = False,
) -> str:
    """Load parser YAML output into guide_* DB tables and create v1 snapshots per candidate.

    Returns the guide_elections.id created (e.g. 'president_2024_16').
    Raises GuideElectionExists if the election already exists and force=False.
    """
    source_pdf_path = Path(source_pdf_path)
    m = re.search(r"(\d+)年第(\d+)任", source_pdf_path.name)
    if not m:
        raise ValueError(
            f"Cannot parse election year/session from filename: {source_pdf_path.name}"
        )

    minguo_year = int(m.group(1))
    session = int(m.group(2))
    year_ad = minguo_year + 1911

    election_id = f"{election_type}_{year_ad}_{session}"
    type_label = "總統" if election_type == "president" else election_type
    label = f"第{session}任 {year_ad} {type_label}"

    if store.guide_election_exists(election_id):
        if not force:
            raise GuideElectionExists(
                f"Election '{election_id}' already exists. Use force=True to overwrite."
            )
        store.guide_delete_election(election_id)

    store.guide_upsert_election(
        election_id=election_id,
        election_type=election_type,
        year=year_ad,
        session=session,
        label=label,
        source_pdf_path=str(source_pdf_path),
    )

    data = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8"))
    crops_base = Path(crops_base_dir)
    order_counter = 0

    def _crop(name_clean: str, field: str) -> str | None:
        rel = crop_filename(type=election_type, session=session,
                            minguo_year=minguo_year, ticket=ticket,
                            name=name_clean, field=field)
        p = crops_base / rel
        if p.exists():
            return str(p)
        if field in BASIC_SUBFIELDS:   # 113 出生年月日/性別 → 基本資料合併格
            rel_b = crop_filename(type=election_type, session=session,
                                  minguo_year=minguo_year, ticket=ticket,
                                  name=name_clean, field="基本資料")
            pb = crops_base / rel_b
            return str(pb) if pb.exists() else None
        return None

    for entry in data:
        ticket = entry["號次"]
        party = entry.get("政黨")
        verify_block = entry.get("_verify", {})

        order_counter += 1
        group_id = store.guide_insert_group(
            guide_election_id=election_id, ticket=ticket, party=party,
            order_id=order_counter)

        # 組共用政見
        platform_grade = verify_block.get("政見", {})
        platform_grade = platform_grade.get("grade") if isinstance(platform_grade, dict) else None
        store.guide_upsert_platform(
            guide_group_id=group_id, value=entry.get("政見"), grade=platform_grade,
            source_crop_path=_crop("", "政見"), update_source="parse")

        candidate_ids: dict[str, int] = {}
        for role in ("總統", "副總統"):
            role_dict = entry.get(role)
            if role_dict is None:
                continue

            order_counter += 1
            name_raw = role_dict.get("姓名")
            name_clean = "".join(str(name_raw).split()) if name_raw is not None else ""

            guide_candidate_id = store.guide_insert_candidate(
                guide_election_id=election_id, guide_group_id=group_id, role=role,
                photo_path=role_dict.get("相片"),
                source_page=role_dict.get("頁碼"),
                order_id=order_counter)
            candidate_ids[role] = guide_candidate_id

            role_verify = verify_block.get(role, {})
            for field in PERSON_FIELDS:
                grade_info = role_verify.get(field)
                grade = grade_info.get("grade") if isinstance(grade_info, dict) else None
                store.guide_insert_field(
                    guide_candidate_id=guide_candidate_id,
                    field_name=field, value=role_dict.get(field), grade=grade,
                    source_crop_path=_crop(name_clean, field), update_source="parse")

        # 組 v1 snapshot:凍結正副各欄 + 政見
        snapshot_id = store.guide_create_group_snapshot(guide_group_id=group_id, version_no=1)
        for role, cid in candidate_ids.items():
            for f in store.guide_get_fields(cid):
                store.guide_insert_group_snapshot_field(
                    snapshot_id=snapshot_id, scope=role, field_name=f["field_name"],
                    value=f["value"], grade=f["grade"],
                    source_crop_path=f["source_crop_path"],
                    flagged=f["flagged"], flag_note=f["flag_note"])
        plat = store.guide_get_platform(group_id)
        if plat is not None:
            store.guide_insert_group_snapshot_field(
                snapshot_id=snapshot_id, scope="政見", field_name="政見",
                value=plat["value"], grade=plat["grade"],
                source_crop_path=plat["source_crop_path"],
                flagged=plat["flagged"], flag_note=plat["flag_note"])

    return election_id


def main() -> None:
    import argparse

    from src.webapp.store import Store, load_database_config

    ap = argparse.ArgumentParser(description="匯入選舉公報解析產物到 guide_* DB")
    ap.add_argument("yaml_path", help="parser 產出的 YAML 路徑")
    ap.add_argument("source_pdf_path", help="來源公報 PDF 路徑(用於推導年份/屆次)")
    ap.add_argument("crops_base_dir", help="切圖/照片輸出基底目錄(如 _out/parsed)")
    ap.add_argument("--type", default="president", dest="election_type",
                    help="選舉類型(預設 president)")
    ap.add_argument("--force", action="store_true",
                    help="該場已存在時,刪除既有 guide_* 資料(含已提交 snapshot、人工修正)並重建 v1")
    args = ap.parse_args()

    store = Store(load_database_config())
    store.open()
    try:
        store.init_schema()
        election_id = load_guide(
            store,
            yaml_path=args.yaml_path,
            source_pdf_path=args.source_pdf_path,
            crops_base_dir=args.crops_base_dir,
            election_type=args.election_type,
            force=args.force,
        )
        print(f"loaded {election_id}")
    except GuideElectionExists as exc:
        raise SystemExit(f"{exc}\n(加 --force 可強制重灌,但會刪除該場所有既有資料)")
    finally:
        store.close()


if __name__ == "__main__":
    main()
