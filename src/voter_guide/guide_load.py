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

    for entry in data:
        ticket = entry["號次"]
        party = entry.get("政黨")
        verify_block = entry.get("_verify", {})

        for role in ("總統", "副總統"):
            role_dict = entry.get(role)
            if role_dict is None:
                continue

            order_counter += 1
            name_raw = role_dict.get("姓名")
            name_clean = "".join(str(name_raw).split()) if name_raw is not None else ""
            photo_path = role_dict.get("相片")
            source_page = role_dict.get("頁碼")

            guide_candidate_id = store.guide_insert_candidate(
                guide_election_id=election_id,
                ticket=ticket,
                role=role,
                party=party,
                photo_path=photo_path,
                source_page=source_page,
                order_id=order_counter,
            )

            role_verify = verify_block.get(role, {})

            for field in PERSON_FIELDS:
                value = role_dict.get(field)
                grade_info = role_verify.get(field)
                grade = grade_info.get("grade") if isinstance(grade_info, dict) else None

                rel = crop_filename(
                    type=election_type,
                    session=session,
                    minguo_year=minguo_year,
                    ticket=ticket,
                    name=name_clean,
                    field=field,
                )
                full_path = crops_base / rel
                if full_path.exists():
                    source_crop_path = str(full_path)
                elif field in BASIC_SUBFIELDS:
                    rel_basic = crop_filename(
                        type=election_type,
                        session=session,
                        minguo_year=minguo_year,
                        ticket=ticket,
                        name=name_clean,
                        field="基本資料",
                    )
                    basic_path = crops_base / rel_basic
                    source_crop_path = str(basic_path) if basic_path.exists() else None
                else:
                    source_crop_path = None

                store.guide_insert_field(
                    guide_candidate_id=guide_candidate_id,
                    field_name=field,
                    value=value,
                    grade=grade,
                    source_crop_path=source_crop_path,
                    update_source="parse",
                )

            snapshot_id = store.guide_create_snapshot(
                guide_candidate_id=guide_candidate_id,
                version_no=1,
            )

            for f in store.guide_get_fields(guide_candidate_id):
                store.guide_insert_snapshot_field(
                    snapshot_id=snapshot_id,
                    field_name=f["field_name"],
                    value=f["value"],
                    grade=f["grade"],
                    source_crop_path=f["source_crop_path"],
                    flagged=f["flagged"],
                    flag_note=f["flag_note"],
                )

    return election_id
