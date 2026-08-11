"""立委公報的認檔:四屆目錄擺法不一致,都要判定出同樣的身分欄位。"""
from pathlib import Path

from src.voter_guide import election_meta as em

BASE = Path("_data/voter_guide/legislator")


def meta(rel: str):
    return em.from_pdf_path(BASE / rel)


def test_district_old_layout():
    # 08th_101 用英文分類目錄
    m = meta("08th_101/district/01臺北市/臺北市立委選舉第1選區.pdf")
    assert (m.type, m.year, m.session, m.region) == ("legislator", 2012, 8, "臺北市")
    assert m.election_id == "legislator_2012_區域_臺北市第1選舉區"
    assert m.nav_path == ("立法委員", "第8屆 2012", "區域", "臺北市", "第1選舉區")
    assert m.roles == ("立法委員",)
    assert m.layout == em.SINGLE


def test_district_new_layout():
    # 11th_113 用「02區域立法委員」+ 選舉區目錄
    m = meta("11th_113/02區域立法委員/02臺北市/第1選舉區/臺北市立委第1選舉區.pdf")
    assert m.election_id == "legislator_2024_區域_臺北市第1選舉區"
    assert m.nav_path == ("立法委員", "第11屆 2024", "區域", "臺北市", "第1選舉區")


def test_district_covering_several_areas():
    m = meta("08th_101/district/02新北市/新北市立委選舉1.8.9選區.pdf")
    assert m.election_id == "legislator_2012_區域_新北市第1、8、9選舉區"


def test_district_chinese_numeral():
    m = meta("11th_113/02區域立法委員/12雲林縣/第1選舉區/雲林縣第11屆立委-第一選區.pdf")
    assert m.election_id == "legislator_2024_區域_雲林縣第1選舉區"


def test_tree_depth_is_the_same_for_every_county():
    # 左樹一律「區域 → 縣市 → 選舉區」;全縣一席的縣市也照樣開一層,不然有的
    # 縣市點得開、有的直接是連結,看起來很亂
    m = meta("09th_105/district/16花蓮縣/花蓮縣立委選舉.pdf")
    assert m.nav_path == ("立法委員", "第9屆 2016", "區域", "花蓮縣", "選舉區")
    other = meta("09th_105/district/01臺北市/臺北市立委選舉第1選區.pdf")
    assert len(other.nav_path) == len(m.nav_path)


def test_by_election_inside_district_dir():
    # 檔名寫著缺額補選,即使放在區域目錄下也算補選
    m = meta("10th_109/02區域立法委員/05臺中市/臺中市立委第2選舉區缺額補選.pdf")
    assert m.election_id == "legislator_2020_補選_臺中市第2選舉區"
    assert m.nav_path == ("立法委員", "第10屆 2020", "補選", "臺中市第2選舉區")
    assert m.label.endswith("立委補選")


def test_for_scope_splits_a_combined_gazette():
    # 合刊公報拆場:識別碼、標題、切圖前綴、左樹位置都跟著換
    base = meta("08th_101/district/16南投縣/南投縣立委選舉.pdf")
    one = base.for_scope(2)
    assert one.election_id == "legislator_2012_區域_南投縣第2選舉區"
    assert one.nav_path == ("立法委員", "第8屆 2012", "區域", "南投縣", "第2選舉區")
    assert one.crop_slug != base.crop_slug      # 不同區的第1號切圖不能互相覆蓋
    assert one.region == base.region and one.roles == base.roles


def test_for_scope_splits_by_name_for_indigenous_seats():
    # 101 把平地與山地原住民合刊,兩邊號次也各自從 1 編起
    base = meta("08th_101/native/101年第8屆平地山地原住民立委選舉.pdf")
    assert base.splits_by_scope and not base.by_district
    one = base.for_scope("山地原住民")
    assert one.election_id == "legislator_2012_原住民_山地原住民"
    assert one.nav_path == ("立法委員", "第8屆 2012", "山地原住民")


def test_party_list():
    m = meta("11th_113/05全國不分區及僑居國外國民立法委員/全國不分區及僑居國外國民立法委員.pdf")
    assert m.election_id == "legislator_2024_不分區_全國不分區"
    assert m.region is None
    assert m.roles == ()
    assert m.layout == em.PARTY_LIST


def test_party_list_split_into_several_files():
    # 105 的不分區公報拆成 4 份,不能互相覆蓋
    ids = {meta(f"09th_105/party/105年全國不分區及僑居國外國民立委選舉{n}.pdf").election_id
           for n in (1, 2, 3, 4)}
    assert len(ids) == 4


def test_native_kinds():
    assert meta("11th_113/04山地原住民立法委員/山地原住民立法委員.pdf").election_id \
        == "legislator_2024_原住民_山地原住民"
    # 101 把平地與山地合刊成一份
    assert meta("08th_101/native/101年第8屆平地山地原住民立委選舉.pdf").election_id \
        == "legislator_2012_原住民_平地山地原住民"


def test_front_and_back_are_separate_gazettes():
    a = meta("10th_109/02區域立法委員/11南投縣/南投縣第1、2選舉區立委-正面.pdf")
    b = meta("10th_109/02區域立法委員/11南投縣/南投縣第1、2選舉區立委-背面.pdf")
    assert a.election_id != b.election_id


def test_recall_and_polling_places_are_not_gazettes():
    assert not em.is_gazette(
        BASE / "11th_113/06罷免案/16花蓮縣/01紙本公報/第11屆立法委員（花蓮縣選舉區）傅崐萁罷免案公告.pdf")
    assert not em.is_gazette(
        BASE / "11th_113/02區域立法委員/22新竹市/02新竹市投開票所.pdf")


def test_same_file_shared_by_two_district_dirs_listed_once():
    # 臺南市第5、6選舉區合刊,同一份檔案被放進兩個選舉區目錄
    found = [p for p in em.find_gazettes(BASE / "11th_113/02區域立法委員/06臺南市")]
    assert len(found) == len({p.name for p in found})
