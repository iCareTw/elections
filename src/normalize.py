import re

# 先移除括號及其內容，再移除其餘特殊符號與空白
_BRACKET_PATTERN = re.compile(r'[(\（][^)\）]*[)\）]|[【][^】]*[】]')
_REMOVE_PATTERN = re.compile(r'[\s\u3000‧·•]')


def normalize_name(name: str) -> str:
    """移除空白、括號（含內容）、特殊符號，保留中文、英文、數字。"""
    name = _BRACKET_PATTERN.sub('', name)
    return _REMOVE_PATTERN.sub('', name)


def generate_id(name: str, birthday=None) -> str:
    """
    產生候選人唯一 ID。
    birthday 可為 int（僅年份）、str "yyyy/mm" 或 "yyyy/mm/dd"、或 None。
    """
    base = normalize_name(name)
    if birthday is None:
        return f"id_{base}"
    if isinstance(birthday, int):
        return f"id_{base}_{birthday}"
    parts = str(birthday).split('/')
    suffix = ''.join(parts)
    return f"id_{base}_{suffix}"
