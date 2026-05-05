from pathlib import Path

from src.webapp.discovery import discover_elections, load_election_records


def test_discover_elections_includes_current_source_types(tmp_path: Path) -> None:
    party_list_dir = tmp_path / "_data" / "legislator" / "party-list-legislator"
    party_list_dir.mkdir(parents=True)
    (party_list_dir / "11th.yaml").write_text("[]", encoding="utf-8")

    president_dir = tmp_path / "_data" / "president"
    president_dir.mkdir(parents=True)
    (president_dir / "第16任總統副總統選舉.xlsx").write_text("")

    mayor_dir = tmp_path / "_data" / "mayor"
    mayor_dir.mkdir(parents=True)
    (mayor_dir / "111年直轄市長選舉.xlsx").write_text("")

    district_dir = tmp_path / "_data" / "legislator" / "district-legislator" / "11th"
    district_dir.mkdir(parents=True)
    (district_dir / "區域_臺北市.xlsx").write_text("")

    by_election_dir = tmp_path / "_data" / "legislator" / "by-election-legislator" / "8th"
    by_election_dir.mkdir(parents=True)
    (by_election_dir / "第8屆立法委員臺中市第02選舉區補選.xlsx").write_text("")
    by_election_yaml = tmp_path / "_data" / "legislator" / "by-election-legislator" / "9th.yaml"
    by_election_yaml.write_text("[]", encoding="utf-8")

    (tmp_path / "_data" / "unknown").mkdir(parents=True)

    elections = discover_elections(tmp_path)
    by_id = {e["election_id"]: e for e in elections}

    assert set(by_id) == {
        "legislator/district-legislator/11th/區域_臺北市.xlsx",
        "legislator/by-election-legislator/8th/第8屆立法委員臺中市第02選舉區補選.xlsx",
        "legislator/by-election-legislator/9th.yaml",
        "legislator/party-list-legislator/11th.yaml",
        "mayor/111年直轄市長選舉.xlsx",
        "president/第16任總統副總統選舉.xlsx",
    }
    assert by_id["legislator/party-list-legislator/11th.yaml"]["status"] == "todo"
    assert by_id["legislator/party-list-legislator/11th.yaml"]["session"] == 11
    assert by_id["legislator/party-list-legislator/11th.yaml"]["year"] == 2024
    assert isinstance(by_id["legislator/party-list-legislator/11th.yaml"]["path"], Path)
    assert by_id["legislator/party-list-legislator/11th.yaml"]["path"] == party_list_dir / "11th.yaml"
    assert by_id["president/第16任總統副總統選舉.xlsx"]["year"] == 2024
    assert by_id["mayor/111年直轄市長選舉.xlsx"]["year"] == 2022
    assert by_id["legislator/district-legislator/11th/區域_臺北市.xlsx"]["session"] == 11
    assert by_id["legislator/district-legislator/11th/區域_臺北市.xlsx"]["year"] == 2024
    assert by_id["legislator/district-legislator/11th/區域_臺北市.xlsx"]["path"] == district_dir / "區域_臺北市.xlsx"
    by_election_id = "legislator/by-election-legislator/8th/第8屆立法委員臺中市第02選舉區補選.xlsx"
    assert by_id[by_election_id]["session"] == 8
    assert "year" not in by_id[by_election_id]
    by_election_yaml_id = "legislator/by-election-legislator/9th.yaml"
    assert by_id[by_election_yaml_id]["session"] == 9
    assert "year" not in by_id[by_election_yaml_id]
    assert by_id[by_election_yaml_id]["path"] == by_election_yaml


def test_discover_elections_ignores_underscore_prefixed_files_and_dirs(tmp_path: Path) -> None:
    """
    確保 _data/_xxx "_" 開頭的東西不會出現在 identity-ui 裡頭
    """
    visible_dir = tmp_path / "_data" / "legislator" / "party-list-legislator"
    visible_dir.mkdir(parents=True)
    (visible_dir / "11th.yaml").write_text("[]", encoding="utf-8")
    ignored_dir = visible_dir / "_raw"
    ignored_dir.mkdir()
    (ignored_dir / "10th.yaml").write_text("[]", encoding="utf-8")
    (visible_dir / "_draft.yaml").write_text("[]", encoding="utf-8")

    elections = discover_elections(tmp_path)

    assert [e["election_id"] for e in elections] == ["legislator/party-list-legislator/11th.yaml"]


def test_load_election_records_assigns_stable_source_record_ids(tmp_path: Path) -> None:
    path = tmp_path / "_data" / "legislator" / "party-list-legislator" / "11th.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("- name: 測試\n  party: 測試黨\n  birthday: 1970\n", encoding="utf-8")
    election = {
        "election_id": "legislator/party-list-legislator/11th.yaml",
        "type": "party-list",
        "path": path,
        "session": 11,
    }

    rows = load_election_records(election)

    assert rows[0]["source_record_id"] == "legislator/party-list-legislator/11th.yaml:0"
    assert rows[0]["election_id"] == "legislator/party-list-legislator/11th.yaml"
    assert rows[0]["name"] == "測試"


def test_load_by_election_yaml_records(tmp_path: Path) -> None:
    path = tmp_path / "_data" / "legislator" / "by-election-legislator" / "9th.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "- name: 補選測試\n"
        "  birthday: 1980\n"
        "  order_id: 1\n"
        "  party: 測試黨\n"
        "  year: 2019\n"
        "  session: 9\n"
        "  region: 測試縣第01選舉區\n"
        "  type: 立法委員\n"
        "  elected: 1\n",
        encoding="utf-8",
    )
    election = {
        "election_id": "legislator/by-election-legislator/9th.yaml",
        "type": "legislator-by-election",
        "path": path,
        "session": 9,
    }

    rows = load_election_records(election)

    assert rows[0]["source_record_id"] == "legislator/by-election-legislator/9th.yaml:0"
    assert rows[0]["election_id"] == "legislator/by-election-legislator/9th.yaml"
    assert rows[0]["name"] == "補選測試"
