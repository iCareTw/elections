"""匯入選舉公報解析產物到 guide_* DB 資料表，並建立 v1 snapshot。"""
from __future__ import annotations

from pathlib import Path

import yaml

from src.voter_guide import election_meta
from src.voter_guide.pipeline import BASIC_SUBFIELDS, PERSON_FIELDS, crop_filename


class GuideElectionExists(Exception):
    pass


# 一組裡除了人以外的欄位
_GROUP_KEYS = ("號次", "政黨", "政見", "_verify")


def _roles_of(entry: dict) -> list[str]:
    """一組裡有哪些人。YAML 的鍵序就是公報上的順序(正/副、名單第 1..N 名)。"""
    return [k for k, v in entry.items()
            if k not in _GROUP_KEYS and isinstance(v, dict)]


def load_guide(
    store,
    *,
    yaml_path,
    source_pdf_path,
    crops_base_dir,
    force: bool = False,
) -> str:
    """Load parser YAML output into guide_* DB tables and create v1 snapshots per candidate.

    Returns the guide_elections.id created (e.g. 'president_2024_16'、'mayor_2022_臺北市').
    Raises GuideElectionExists if the election already exists and force=False.
    """
    source_pdf_path = Path(source_pdf_path)
    meta = election_meta.from_pdf_path(source_pdf_path)
    election_id = meta.election_id

    if store.guide_election_exists(election_id):
        if not force:
            raise GuideElectionExists(
                f"Election '{election_id}' already exists. Use force=True to overwrite."
            )
        store.guide_delete_election(election_id)

    store.guide_upsert_election(
        election_id=election_id,
        election_type=meta.type,
        year=meta.year,
        session=meta.session,
        label=meta.label,
        region=meta.region,
        source_pdf_path=str(source_pdf_path),
        nav_path="/".join(meta.nav_path) or None,
    )

    data = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8"))
    crops_base = Path(crops_base_dir)
    order_counter = 0

    def _crop(name_clean: str, field: str) -> str | None:
        p = crops_base / crop_filename(slug=meta.crop_slug, ticket=ticket,
                                       name=name_clean, field=field)
        if p.exists():
            return str(p)
        if field in BASIC_SUBFIELDS:   # 出生年月日/性別 疊在「基本資料」合併格
            pb = crops_base / crop_filename(slug=meta.crop_slug, ticket=ticket,
                                            name=name_clean, field="基本資料")
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
        # 角色以解析結果為準:總統公報固定正副兩人,不分區則是名單上第 1..N 名,
        # 人數隨政黨不同,不能拿 meta 的固定角色去套。
        for role in _roles_of(entry):
            role_dict = entry[role]

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

    # 套回手動更正的照片(獨立保存,重載/重解析都保留)
    store.guide_apply_manual_photos(election_id)

    return election_id


def main() -> None:
    import argparse

    from src.webapp.store import Store, load_database_config

    ap = argparse.ArgumentParser(description="匯入選舉公報解析產物到 guide_* DB")
    ap.add_argument("yaml_path", help="parser 產出的 YAML 路徑")
    ap.add_argument("source_pdf_path", help="來源公報 PDF 路徑(用於推導年份/屆次)")
    ap.add_argument("crops_base_dir", help="切圖/照片輸出基底目錄(如 _out/parsed)")
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
            force=args.force,
        )
        print(f"loaded {election_id}")
    except GuideElectionExists as exc:
        raise SystemExit(f"{exc}\n(加 --force 可強制重灌,但會刪除該場所有既有資料)")
    finally:
        store.close()


if __name__ == "__main__":
    main()
