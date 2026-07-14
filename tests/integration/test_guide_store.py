"""Phase G4 — 組層級 store 存取層測試(iteration 2)。

重用 tests/integration/test_guide_load 的 DB-skip 與假資料 load helper。
假資料:2 組;第1組 民進黨(蔡英文/賴清德)政見「第1組政見內容…」;
第2組 國民黨(侯友宜/趙少康)政見 None。
"""
from __future__ import annotations

import pytest

from tests.integration.test_guide_load import ELECTION_ID, _load, _store


def _view(store, tmp_path, ticket=1):
    store.guide_delete_election(ELECTION_ID)
    _load(store, tmp_path)
    return store.guide_group_view(ELECTION_ID, ticket)


def _pres_field(view, field_name):
    return next(f for f in view["president"]["fields"] if f["field_name"] == field_name)


def test_guide_tree(tmp_path):
    store = _store()
    try:
        _load(store, tmp_path)
        tree = store.guide_tree()
        pres = next(t for t in tree if t["type"] == "president")
        assert any(e["id"] == ELECTION_ID for e in pres["elections"])
    finally:
        store.guide_delete_election(ELECTION_ID)
        store.close()


def test_candidates_of_joins_group(tmp_path):
    store = _store()
    try:
        store.guide_delete_election(ELECTION_ID)
        _load(store, tmp_path)
        cands = store.guide_candidates_of(ELECTION_ID)
        assert len(cands) == 4
        c = next(x for x in cands if x["name"] == "蔡英文")
        assert c["ticket"] == 1 and c["party"] == "民主進步黨" and c["role"] == "總統"
        assert "guide_group_id" in c
    finally:
        store.guide_delete_election(ELECTION_ID)
        store.close()


def test_group_view_shape(tmp_path):
    store = _store()
    try:
        v = _view(store, tmp_path, 1)
        assert v["group"]["ticket"] == 1 and v["group"]["party"] == "民主進步黨"
        assert v["president"]["candidate"]["role"] == "總統"
        assert v["vice"]["candidate"]["role"] == "副總統"
        assert [f["field_name"] for f in v["president"]["fields"]] == \
            ["姓名", "出生年月日", "性別", "學歷", "經歷"]
        assert v["president"]["candidate"]["gender"] == "女"   # 蔡英文
        assert v["platform"]["value"] == "第1組政見內容…"
        assert v["platform"]["can_ai_repair"] is True
        assert v["has_uncommitted"] is False and v["latest_version"] == 1
    finally:
        store.guide_delete_election(ELECTION_ID)
        store.close()


def test_group_view_none_when_absent(tmp_path):
    store = _store()
    try:
        _load(store, tmp_path)
        assert store.guide_group_view(ELECTION_ID, 99) is None
    finally:
        store.guide_delete_election(ELECTION_ID)
        store.close()


def test_flag_field_and_platform_cause_uncommitted(tmp_path):
    store = _store()
    try:
        v = _view(store, tmp_path, 1)
        fid = _pres_field(v, "學歷")["id"]
        gid = v["group"]["id"]

        store.guide_flag_field(fid, "學歷有問題")
        assert store.guide_group_view(ELECTION_ID, 1)["has_uncommitted"] is True

        store.guide_unflag_field(fid)
        assert store.guide_group_view(ELECTION_ID, 1)["has_uncommitted"] is False

        store.guide_flag_platform(gid, "政見讀錯")
        v2 = store.guide_group_view(ELECTION_ID, 1)
        assert v2["has_uncommitted"] is True
        assert v2["platform"]["flagged"] is True
    finally:
        store.guide_delete_election(ELECTION_ID)
        store.close()


def test_manual_values(tmp_path):
    store = _store()
    try:
        v = _view(store, tmp_path, 1)
        fid = _pres_field(v, "學歷")["id"]
        gid = v["group"]["id"]

        store.guide_set_field_value(fid, "手動學歷")
        store.guide_set_platform_value(gid, "手動政見")
        v2 = store.guide_group_view(ELECTION_ID, 1)
        assert _pres_field(v2, "學歷")["value"] == "手動學歷"
        assert _pres_field(v2, "學歷")["grade"] is None
        assert v2["platform"]["value"] == "手動政見"
        assert v2["has_uncommitted"] is True
    finally:
        store.guide_delete_election(ELECTION_ID)
        store.close()


def test_has_uncommitted_excludes_photo(tmp_path):
    store = _store()
    try:
        v = _view(store, tmp_path, 1)
        cand_id = v["president"]["candidate"]["id"]
        store.guide_flag_photo(cand_id, "照片錯")
        # 照片不參與版本狀態
        assert store.guide_group_view(ELECTION_ID, 1)["has_uncommitted"] is False
    finally:
        store.guide_delete_election(ELECTION_ID)
        store.close()


def test_any_flag_reflects_platform(tmp_path):
    store = _store()
    try:
        v = _view(store, tmp_path, 1)
        gid = v["group"]["id"]
        store.guide_flag_platform(gid, "政見")
        cands = store.guide_candidates_of(ELECTION_ID)
        grp1 = [c for c in cands if c["ticket"] == 1]
        assert all(c["any_flag"] for c in grp1)   # 政見標記 → 整組亮
    finally:
        store.guide_delete_election(ELECTION_ID)
        store.close()


def test_group_commit_and_discard(tmp_path):
    store = _store()
    try:
        v = _view(store, tmp_path, 1)
        gid = v["group"]["id"]
        fid = _pres_field(v, "學歷")["id"]

        # 改欄位 + 政見 → commit → v2、未提交清除
        store.guide_set_field_value(fid, "commit前改")
        store.guide_set_platform_value(gid, "政見改")
        nv = store.guide_group_commit(gid, "版本2")
        assert nv == 2
        v2 = store.guide_group_view(ELECTION_ID, 1)
        assert v2["has_uncommitted"] is False and v2["latest_version"] == 2

        # 再改 → discard → 還原到 v2 值
        store.guide_set_field_value(fid, "又改")
        store.guide_set_platform_value(gid, "政見又改")
        store.guide_group_discard(gid)
        v3 = store.guide_group_view(ELECTION_ID, 1)
        assert _pres_field(v3, "學歷")["value"] == "commit前改"
        assert v3["platform"]["value"] == "政見改"
        assert v3["has_uncommitted"] is False
    finally:
        store.guide_delete_election(ELECTION_ID)
        store.close()


def test_group_snapshot_view_bounds(tmp_path):
    store = _store()
    try:
        v = _view(store, tmp_path, 1)
        gid = v["group"]["id"]
        store.guide_group_commit(gid, "v2")
        snap1 = store.guide_group_snapshot_view(gid, 1)
        assert snap1["version_no"] == 1
        assert snap1["min_version"] == 1 and snap1["max_version"] == 2
        # v1 快照含政見 + 正副各欄 = 11
        assert len(snap1["fields"]) == 11
        assert any(f["field_name"] == "政見" for f in snap1["fields"])
    finally:
        store.guide_delete_election(ELECTION_ID)
        store.close()
