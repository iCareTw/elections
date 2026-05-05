import re
from typing import Union

_BRACKET_PATTERN = re.compile(r"[(\（][^)\）]*[)\）]|[【][^】]*[】]")
_REMOVE_PATTERN = re.compile(r"[\s　‧·•．]")
_SPACE_PATTERN = re.compile(r"[\s　]")
_DOT_PATTERN = re.compile(r"[‧·•．]")
_LATIN_PATTERN = re.compile(r"[A-Za-z]+")
_ASCII_DOT_PATTERN = re.compile(r"[.]")


def normalize_name(name: str) -> str:
    """移除空白、括號（含內容）、特殊符號，保留中文、英文、數字。"""
    name = _BRACKET_PATTERN.sub("", name)
    return _REMOVE_PATTERN.sub("", name)


def normalize_name_without_latin(name: str) -> str:
    """供 fallback 比對使用：移除英文字母與英文名常見分隔點。"""
    name = _LATIN_PATTERN.sub("", name)
    name = _ASCII_DOT_PATTERN.sub("", name)
    return normalize_name(name)


def normalize_candidate_name(name: str) -> str:
    """去除空白、將 ‧·•． 統一轉為 .，供 candidates.name 儲存與比對用。"""
    name = _BRACKET_PATTERN.sub("", name)
    name = _SPACE_PATTERN.sub("", name)
    return _DOT_PATTERN.sub(".", name)


def generate_id(
    name: str,
    birthday: Union[str, int, None],
    year: Union[int, str, None] = None,
    age: Union[int, str, None] = None,
) -> str:
    """
    產生候選人唯一 ID
    birthday 可以接受 yyyy-mm-dd 或 yyyy 或 None
    year 為 int, 當 birthday 為 None 時使用, 格式為 yyyy
    age 為 int, 此為 birthday 為 None 時使用, 格式 xx
    ID 格式：id_{正規化姓名} 或 id_{正規化姓名}_{yyyy}
    """
    base = normalize_name(name)

    if birthday:
        birth_year = str(birthday)[:4]
        if (int(birth_year) > 2100) or (int(birth_year) < 1900):  # 生日合理範圍判斷
            raise ValueError(f"❌ {name} 組 id 失敗. year={year} 不合理")
        return f"id_{base}_{birth_year}"
    elif year is not None and age is not None:
        return f"id_{base}_{year}_{age}"
    else:
        raise ValueError(f"❌ {name} 組 id 失敗. birthday={birthday} & year={year} & age={age}")
