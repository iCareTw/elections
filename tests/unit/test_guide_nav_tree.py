"""左樹節點的排序與層數:立委比總統深,年份由新到舊,選舉區照數字順序。"""
from src.webapp.store import _nav_fill, _nav_node, _nav_path_of


def _row(**kw):
    row = {"id": "x", "label": "", "year": 2024, "session": None,
           "type": "mayor", "region": None, "nav_path": None}
    row.update(kw)
    return row


def _build(paths_with_ids):
    root = _nav_node("")
    for path, eid in paths_with_ids:
        node = root
        for name in path[:-1]:
            kid = next((c for c in node["children"]
                        if c["label"] == name and not c["id"]), None)
            if kid is None:
                kid = _nav_node(name)
                node["children"].append(kid)
            node = kid
        leaf = _nav_node(path[-1])
        leaf["id"] = eid
        node["children"].append(leaf)
    return root


def test_path_uses_nav_path_when_present():
    assert _nav_path_of(_row(nav_path="立法委員/第11屆 2024/區域/臺北市/第1選舉區")) \
        == ["立法委員", "第11屆 2024", "區域", "臺北市", "第1選舉區"]


def test_path_falls_back_for_rows_without_nav_path():
    # 尚未回填 nav_path 的舊資料仍要能出現在左樹
    assert _nav_path_of(_row(type="mayor", year=2022, region="臺北市")) \
        == ["縣市長", "2022", "臺北市"]
    assert _nav_path_of(_row(type="president", label="第16任 2024", region=None)) \
        == ["總統", "第16任 2024"]


def test_districts_sort_numerically_and_years_newest_first():
    root = _build([
        (["立法委員", "第10屆 2020", "區域", "臺北市", "第2選舉區"], "a"),
        (["立法委員", "第10屆 2020", "區域", "臺北市", "第10選舉區"], "b"),
        (["立法委員", "第11屆 2024", "區域", "臺北市", "第1選舉區"], "c"),
    ])
    _nav_fill(root, {})
    legislator = root["children"][0]
    assert [s["label"] for s in legislator["children"]] == ["第11屆 2024", "第10屆 2020"]
    taipei = legislator["children"][1]["children"][0]["children"][0]
    assert [e["label"] for e in taipei["children"]] == ["第2選舉區", "第10選舉區"]


def test_top_level_follows_fixed_order():
    root = _build([
        (["立法委員", "第11屆 2024", "全國不分區"], "a"),
        (["總統", "第16任 2024"], "b"),
        (["縣市長", "2022", "臺北市"], "c"),
    ])
    _nav_fill(root, {})
    assert [n["label"] for n in root["children"]] == ["總統", "縣市長", "立法委員"]


def test_pending_counts_bubble_up():
    root = _build([
        (["立法委員", "第11屆 2024", "區域", "臺北市", "第1選舉區"], "a"),
        (["立法委員", "第11屆 2024", "區域", "臺北市", "第2選舉區"], "b"),
    ])
    _nav_fill(root, {"a": 3, "b": 4})
    assert root["children"][0]["pending_commit_count"] == 7
