from src.normalize import normalize_name, generate_id
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


def test_generate_id_error_birthday():
    with pytest.raises(ValueError):
        generate_id("陳阿帥", -1986)


def test_generate_id_int_birthday():
    assert generate_id("陳阿帥", birthday=1973) == "id_陳阿帥_1973"
    assert generate_id("陳阿帥", birthday="1973") == "id_陳阿帥_1973"
