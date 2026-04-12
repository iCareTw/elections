from src.normalize import normalize_name, generate_id


def test_remove_special_chars():
    assert normalize_name("伍麗華Saidhai‧Tahovecahe") == "伍麗華SaidhaiTahovecahe"


def test_remove_whitespace():
    assert normalize_name("陳 明") == "陳明"


def test_remove_fullwidth_space():
    assert normalize_name("陳　明") == "陳明"


def test_remove_brackets():
    assert normalize_name("陳明(阿明)") == "陳明"
    assert normalize_name("陳明（阿明）") == "陳明"


def test_keep_english():
    assert normalize_name("SaidhaiTahovecahe") == "SaidhaiTahovecahe"


def test_generate_id_no_birthday():
    assert generate_id("許淑華") == "id_許淑華"


def test_generate_id_int_birthday():
    assert generate_id("許淑華", birthday=1973) == "id_許淑華_1973"


def test_generate_id_str_birthday_year_only():
    # str "1973" → only year used
    assert generate_id("許淑華", birthday="1973") == "id_許淑華_1973"
