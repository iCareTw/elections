from pathlib import Path

from src.webapp.discovery import discover_elections


def test_discover_elections_groups_known_sources(tmp_path: Path) -> None:
    data_dir = tmp_path / "_data"
    (data_dir / "president").mkdir(parents=True)
    (data_dir / "president" / "第16任總統副總統選舉.xlsx").write_text("")
    (tmp_path / "11th.yaml").write_text("[]", encoding="utf-8")

    elections = discover_elections(tmp_path)

    assert [e["type"] for e in elections] == ["party-list", "president"]
    assert elections[0]["election_id"] == "party-list/11th.yaml"
    assert elections[1]["election_id"] == "president/第16任總統副總統選舉.xlsx"


def test_discover_elections_includes_current_source_types(tmp_path: Path) -> None:
    (tmp_path / "11th.yaml").write_text("[]", encoding="utf-8")

    president_dir = tmp_path / "_data" / "president"
    president_dir.mkdir(parents=True)
    (president_dir / "第16任總統副總統選舉.xlsx").write_text("")

    mayor_dir = tmp_path / "_data" / "mayor"
    mayor_dir.mkdir(parents=True)
    (mayor_dir / "111年直轄市長選舉.xlsx").write_text("")

    district_dir = tmp_path / "_data" / "legislator" / "district-legislator" / "11th"
    district_dir.mkdir(parents=True)
    (district_dir / "區域_臺北市.xlsx").write_text("")

    (tmp_path / "_data" / "unknown").mkdir(parents=True)

    elections = discover_elections(tmp_path)
    by_id = {e["election_id"]: e for e in elections}

    assert set(by_id) == {
        "legislator/district-legislator/11th/區域_臺北市.xlsx",
        "mayor/111年直轄市長選舉.xlsx",
        "party-list/11th.yaml",
        "president/第16任總統副總統選舉.xlsx",
    }
    assert by_id["party-list/11th.yaml"]["status"] == "todo"
    assert by_id["party-list/11th.yaml"]["session"] == 11
    assert by_id["party-list/11th.yaml"]["year"] == 2024
    assert isinstance(by_id["party-list/11th.yaml"]["path"], Path)
    assert by_id["party-list/11th.yaml"]["path"] == tmp_path / "11th.yaml"
    assert by_id["president/第16任總統副總統選舉.xlsx"]["year"] == 2024
    assert by_id["mayor/111年直轄市長選舉.xlsx"]["year"] == 2022
    assert by_id["legislator/district-legislator/11th/區域_臺北市.xlsx"]["session"] == 11
    assert by_id["legislator/district-legislator/11th/區域_臺北市.xlsx"]["year"] == 2024
    assert by_id["legislator/district-legislator/11th/區域_臺北市.xlsx"]["path"] == district_dir / "區域_臺北市.xlsx"


def test_discover_elections_ignores_nested_party_list_lookalikes(tmp_path: Path) -> None:
    (tmp_path / "11th.yaml").write_text("[]", encoding="utf-8")

    nested_dir = tmp_path / "_data" / "legislator" / "party-list-legislator"
    nested_dir.mkdir(parents=True)
    (nested_dir / "11th.yaml").write_text("[]", encoding="utf-8")

    elections = discover_elections(tmp_path)

    assert [e["election_id"] for e in elections] == ["party-list/11th.yaml"]
