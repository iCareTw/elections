"""一份公報依序試多種讀法,讀到跟名冊對得上為止,過程全部留下紀錄。

公報的長相沒有規律:有的是純文字、有的字型沒有對照表、有的整份是掃描圖;
排版有橫列也有直行,還有一份裡兩種混雜。與其為每種長相寫判斷,不如逐一嘗試,
用「跟中選會名冊對不對得上」來驗收——對不上就換下一個方法。

驗收標準(`evaluate`):
  有名冊  → 人數要相符,且至少八成姓名對得上(OCR 難免有錯字,不要求逐字精準)
  沒名冊  → 退回結構檢查:讀到人,且號次是從 1 開始的連號

每個方法的結果、耗時、被否決的原因都寫進 `ParseReport`,匯入時落檔也存進 DB,
所以每份公報「試過什麼、為什麼不行」都查得到。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from . import apple_ocr
from . import election_meta
from . import geometry as geo
from . import party_list_parse
from . import roster
from . import scan_parse
from . import scan_table
from . import table_parse
from . import token_parse

NAME_SIMILARITY = 0.6      # 姓名視為同一人的相似度門檻(OCR 錯字容忍)
NAME_HIT_RATIO = 0.8       # 名冊有幾成姓名對得上才算讀成功


@dataclass
class Attempt:
    method: str
    seconds: float
    found: int
    expected: int | None
    matched: int | None
    verdict: str            # 通過 / 為什麼被否決

    @property
    def ok(self) -> bool:
        return self.verdict == "通過"


@dataclass
class ParseReport:
    """一份公報的處理紀錄。"""
    pdf: str
    election_id: str
    attempts: list[Attempt] = field(default_factory=list)
    winner: str | None = None

    def as_text(self) -> str:
        lines = [f"{self.election_id}  ({self.pdf})"]
        for a in self.attempts:
            expect = "—" if a.expected is None else str(a.expected)
            match = "—" if a.matched is None else str(a.matched)
            lines.append(f"  {a.method:<16} {a.seconds:6.1f}s  讀到 {a.found:>3} 人 / "
                         f"名冊 {expect:>3} 人 / 對上 {match:>3} 人  → {a.verdict}")
        lines.append(f"  結果:{'採用 ' + self.winner if self.winner else '全部方法都讀不出來'}")
        return "\n".join(lines)


# ------------------------------------------------------------------ 驗收

def _names_of(groups: list[geo.Group]) -> list[str]:
    return [roster.clean(m.cells["姓名"].text)
            for g in groups for m in g.members if "姓名" in m.cells]


def _same_person(a: str, b: str) -> bool:
    """OCR 會少字、多字、錯字,姓名不要求逐字相同。"""
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    return SequenceMatcher(None, a, b).ratio() >= NAME_SIMILARITY


def _expected_names(meta, groups: list[geo.Group]) -> set[str] | None:
    """這份公報該有哪些人。

    合刊公報的名冊要按選舉區逐區取聯集:檔名寫的選舉區為準,若解析出更多區
    (檔名沒寫、但公報裡真的有)也一併算進來,否則正確的結果反而會被判成多人。
    """
    if not meta.by_district:
        return roster.expected_names(meta)
    nums = set(meta.districts)
    nums |= {g.members[0].district for g in groups
             if g.members and isinstance(g.members[0].district, int)}
    if not nums:
        return roster.expected_names(meta)
    out: set[str] = set()
    for n in sorted(nums):
        out |= roster.expected_names(meta.for_scope(n)) or set()
    return out or None


_LABEL_WORDS = ("姓名", "學歷", "經歷", "政見", "出生", "性別", "號次", "政黨",
                "選舉", "候選人", "資料")


def _looks_like_name(text: str) -> bool:
    """像不像人名。推版面那類方法失手時會把整段內文當成姓名,要擋下來。"""
    return 1 < len(text) <= 12 and not any(w in text for w in _LABEL_WORDS)


def _tickets_look_sane(groups: list[geo.Group]) -> bool:
    """號次應該是各選舉區從 1 開始的連號。"""
    per_scope: dict[object, list[int]] = {}
    for g in groups:
        scope = g.members[0].district if g.members else None
        per_scope.setdefault(scope, []).append(g.ticket or 0)
    for tickets in per_scope.values():
        want = list(range(1, len(tickets) + 1))
        if sorted(tickets) != want:
            return False
    return True


def evaluate(groups: list[geo.Group], meta) -> tuple[bool, int | None, int | None, str]:
    """(是否通過, 名冊人數, 對上人數, 判定說明)。"""
    names = [n for n in _names_of(groups) if n]
    if not names:
        return False, None, None, "讀不到任何候選人"

    junk = [n for n in names if not _looks_like_name(n)]
    if len(junk) > len(names) * 0.2:
        return False, None, None, f"讀出來的姓名不像人名(如「{junk[0][:12]}」)"

    expected = _expected_names(meta, groups)
    if expected is None:
        if not _tickets_look_sane(groups):
            return False, None, None, "沒有名冊可比對,且號次不是從1開始的連號"
        return True, None, None, "通過"

    matched = sum(1 for want in expected if any(_same_person(want, got) for got in names))
    if len(names) < len(expected):
        return False, len(expected), matched, f"人數不足(少 {len(expected) - len(names)} 人)"
    if matched < len(expected) * NAME_HIT_RATIO:
        return False, len(expected), matched, "姓名與名冊對不上"
    return True, len(expected), matched, "通過"


# ------------------------------------------------------------------ 方法清單

def _methods(meta, pdf_path: str):
    """由快到慢、由精確到勉強。每項回傳 (名稱, 取得候選人的函式, 來源標記)。"""
    if meta.layout == election_meta.PARTY_LIST:
        return [("文字層", lambda: party_list_parse.parse(pdf_path), "PDF 文字")]
    if meta.paired:
        return [
            ("文字層", lambda: geo.parse(pdf_path), "PDF 文字"),
            ("匡線+OCR", lambda: apple_ocr.parse(pdf_path), "圖像辨識"),
            ("影像找格線", lambda: scan_parse.parse(pdf_path), "掃描圖重建"),
        ]
    role = meta.roles[0]
    return [
        ("文字層", lambda: table_parse.parse(pdf_path, role=role), "PDF 文字"),
        ("匡線+OCR", lambda: table_parse.parse(pdf_path, role=role, ocr=True), "圖像辨識"),
        ("影像找格線", lambda: scan_table.parse(pdf_path, role=role), "掃描圖重建"),
        ("文字座標推版面", lambda: token_parse.parse(pdf_path, role=role), "PDF 文字"),
        ("整頁OCR推版面", lambda: token_parse.parse(pdf_path, role=role, ocr=True),
         "圖像辨識"),
    ]


def parse_best(pdf_path: str, meta, *, progress=None):
    """依序試各種讀法,回傳 (候選人, 來源標記, 處理紀錄)。

    一有方法通過驗收就停;全部沒過則採用「對上最多、人數最接近」的那個,
    仍然回傳結果(讓校對台至少看得到東西),紀錄裡會寫明沒有任何方法通過。
    """
    report = ParseReport(pdf=str(pdf_path), election_id=meta.election_id)
    best: tuple[tuple, list[geo.Group], str] | None = None

    for name, run, source in _methods(meta, str(pdf_path)):
        if progress:
            progress(0, 0, f"嘗試「{name}」")
        started = time.time()
        try:
            groups = list(run())
        except Exception as exc:                       # noqa: BLE001
            report.attempts.append(Attempt(
                name, time.time() - started, 0, None, None,
                f"執行失敗 {type(exc).__name__}: {exc}"))
            continue
        groups = _for_this_election(groups, meta)
        ok, expected, matched, verdict = evaluate(groups, meta)
        report.attempts.append(Attempt(
            name, time.time() - started, len(_names_of(groups)),
            expected, matched, verdict))
        if ok:
            report.winner = name
            return groups, source, report
        rank = (matched or 0, -abs(len(groups) - (expected or 0)))
        if groups and (best is None or rank > best[0]):
            best = (rank, groups, source)

    if best is not None:
        return best[1], best[2], report
    return [], "PDF 文字", report


def _is_native_seat(scope) -> bool:
    """選舉區欄指的是原住民席次嗎。

    單一席次的縣市寫的是名稱而非號碼(『基隆市選舉區』),所以不能用
    「號碼=區域、名稱=原住民」來分,要看內容有沒有寫原住民。
    """
    return isinstance(scope, str) and "原住民" in scope


def _for_this_election(groups: list[geo.Group], meta) -> list[geo.Group]:
    """濾掉同一份公報裡別場選舉的候選人。

    101 南投把區域(左半)與原住民(右半)排在同一張表格裡,兩個段落標題並排在同一列,
    用 y 位置分不出來;但選舉區欄自己就寫著是哪一區。
    """
    if meta.type != "legislator" or not meta.splits_by_scope:
        return groups

    def belongs(g: geo.Group) -> bool:
        scope = g.members[0].district if g.members else None
        if scope is None:                          # 公報沒有選舉區欄 → 整份都是本場
            return True
        return _is_native_seat(scope) != meta.by_district

    return [g for g in groups if belongs(g)]
