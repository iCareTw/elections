import re

_BRACKET_PATTERN = re.compile(r'[(\（][^)\）]*[)\）]|[【][^】]*[】]')
_REMOVE_PATTERN = re.compile(r'[\s\u3000‧·•]')


def normalize_name(name: str) -> str:
    """移除空白、括號（含內容）、特殊符號，保留中文、英文、數字。"""
    name = _BRACKET_PATTERN.sub('', name)
    return _REMOVE_PATTERN.sub('', name)


def generate_id(name: str, birthday=None) -> str:
    """
    產生候選人唯一 ID。
    birthday 可為 int（僅年份）、str（任意格式，只取前 4 碼）、或 None。
    ID 格式：id_{正規化姓名} 或 id_{正規化姓名}_{yyyy}
    """
    base = normalize_name(name)
    if birthday is None:
        return f"id_{base}"
    year = int(str(birthday)[:4])
    return f"id_{base}_{year}"
