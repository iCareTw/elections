from src.normalize import normalize_name, normalize_name_without_latin, normalize_candidate_name, generate_id
import pytest


def test_remove_special_chars_to_normalize_name():
    """
    人名去除特殊字元無用部分用來組id
    """
    assert normalize_name("伍麗華Saidhai‧Tahovecahe") == "伍麗華SaidhaiTahovecahe"
    assert normalize_name("陳 明") == "陳明"
    assert normalize_name("陳　明") == "陳明"
    assert normalize_name("陳明(阿明)") == "陳明"
    assert normalize_name("陳明（阿明）") == "陳明"
    assert normalize_name("SaidhaiTahovecahe") == "SaidhaiTahovecahe"
    assert normalize_name("Istanda．Paingav") == "IstandaPaingav"


def test_normalize_candidate_name():
    assert normalize_candidate_name("伍麗華 Saidhai．Tahovecahe") == "伍麗華Saidhai.Tahovecahe"
    assert normalize_candidate_name("伍麗華Saidhai‧Tahovecahe") == "伍麗華Saidhai.Tahovecahe"
    assert normalize_candidate_name("高潞‧以用‧巴魕剌Kawlo‧Iyun‧Pacidal") == "高潞.以用.巴魕剌Kawlo.Iyun.Pacidal"
    assert normalize_candidate_name("章正輝 Lemaljiz．Kusaza") == "章正輝Lemaljiz.Kusaza"
    assert normalize_candidate_name("陳　杰") == "陳杰"
    assert normalize_candidate_name("陳明(阿明)") == "陳明"


def test_normalize_name_without_latin():
    assert normalize_name_without_latin("簡東明Uliw．Qaljupayare") == "簡東明"
    assert normalize_name_without_latin("伍麗華Saidhai‧Tahovecahe") == "伍麗華"
    assert normalize_name_without_latin("Kolas Yotaka") == ""


def test_generate_id_error_birthday():
    with pytest.raises(ValueError):
        generate_id("陳阿帥", -1986)


def test_generate_id_int_birthday():
    assert generate_id("陳阿帥", birthday=1973) == "id_陳阿帥_1973"
    assert generate_id("陳阿帥", birthday="1973") == "id_陳阿帥_1973"
