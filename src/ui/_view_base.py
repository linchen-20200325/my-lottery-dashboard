"""Shared view helpers (v6.24 T2 — SSOT for the two Streamlit tab views).

抽出 `lotto649_view` / `powerball_view` 兩 tab **純資料 / 無 widget** 的共用
helper(byte-identical 或僅參數不同),解 SSOT/SoC 報告 S4·C2·C3:
  - `expand_tails_to_numbers`:排除尾數 → 具體號碼 list(v6.17;兩 view 原本逐位元組相同)
  - `freshness_warning`:CSV 新鮮度檢查(僅開獎 weekday 不同)
  - `upload_provenance`:JSON 上傳路徑的 `HistoryProvenance`(無 draw_date → as_of/earliest=None)
  - `analysis_rng`:seed → RNG 契約 SSOT(`seed==0` ⇒ 真隨機;修 DR-7 兩 view 不一致)

**刻意不收 widget 階梯**(render() 的設定 expander / 結果表)—— 那段需 Streamlit
手測,屬後續工作。本模組**不 import streamlit**,故可被 `tests/test_view_base.py`
純單元測試覆蓋。

Stdlib + data 層 only:`random` + `pathlib` + `src.data.*`(零 streamlit 依賴)。
"""

from __future__ import annotations

import random
from pathlib import Path

from src.data.freshness import check_freshness
from src.data.provenance import HistoryProvenance, now_utc


def expand_tails_to_numbers(
    tails: list[int] | tuple[int, ...] | set[int],
    lo: int,
    hi: int,
) -> list[int]:
    """把排除尾數 list 展開為對應的具體號碼 list(v6.17)。

    例:tails=[1,6] + lo=1 + hi=49 → [1, 6, 11, 16, 21, 26, 31, 36, 41, 46]
    """
    if not tails:
        return []
    tail_set = set(tails)
    return [n for n in range(lo, hi + 1) if (n % 10) in tail_set]


def freshness_warning(
    path_str: str, draw_weekdays: frozenset[int] | set[int]
) -> str | None:
    """憲法 §2.4:返回 stale 警告字串或 None(僅檢查 #2 倉庫內附 CSV)。"""
    return check_freshness(Path(path_str), draw_weekdays)


def upload_provenance(source: str, n_rows: int) -> HistoryProvenance:
    """JSON 上傳路徑的 provenance:JSON 不帶 draw_date → as_of / earliest 為 None。"""
    return HistoryProvenance(
        source=source, fetched_at=now_utc(), n_rows=n_rows,
        as_of=None, earliest=None,
    )


def analysis_rng(seed: int) -> random.Random:
    """seed → RNG 契約 SSOT。`seed == 0`(UI「0 = 真隨機」)⇒ 無種子 Random。

    DR-7(v6.24 T2):原本大樂透 render 在 seed==0 傳 `None`、威力彩傳
    `random.Random()`,雖功能等價(picker 內部 `rng or random.Random()`)但契約
    不一;統一走本函式,seed==0 一律回無種子 Random。
    """
    return random.Random(seed) if seed else random.Random()
