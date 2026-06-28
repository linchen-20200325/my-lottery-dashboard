"""Scraper 日期正規化 — 兩 downloader 共用的單一真實來源 (SSOT)。

REFACTOR_AUDIT §5.3。原本 `lotto649_downloader._canon_date` 與
`powerball_downloader._canon_date` 為近乎逐字相同的兩份副本,在此收斂為一。

契約(寬鬆正規化「髒」API 輸入):
  - 接受 '2026/5/12'、'2026-05-15'、'2026-05-15T00:00:00' 等 → 回 'YYYY/MM/DD'(補零)
  - 結構可解析但不存在的日期(2026/02/30、2026/13/05)→ 回 ""(剔除偽造日期)
  - 數值解析本身失敗 → **原樣回傳**(保留上游雜訊供診斷 log)
  - 空字串 → 回 ""

注意:本函式刻意與 `data.provenance.extract_dates` / `data.freshness.latest_csv_date`
**分開** —— 後兩者用 `strptime("%Y/%m/%d")` 嚴格解析「已標準化」的 CSV 日期成
`date` 物件,契約不同(要 date、跳過非標準列),不在此合併(抽共用、留差異)。

Stdlib only(`datetime.date`)。
"""

from __future__ import annotations

from datetime import date


def canon_date(s: str) -> str:
    """Normalize date strings to `YYYY/MM/DD` (zero-padded).

    Accepts: '2026/5/12', '2026-05-15', '2026-05-15T00:00:00', etc.
    Returns "" for structurally parseable but impossible dates
    (e.g. 2026/02/30, 2026/13/05); returns input unchanged if
    numerical parsing itself fails (preserves upstream noise
    for diagnostic logs). Used as the dedupe key because the
    official API changed `draw_term` schemes (e.g. old `2446`
    vs new `115000053`) — date is the stable identifier.
    """
    if not s:
        return ""
    head = s[:10].replace("-", "/")
    parts = head.split("/")
    if len(parts) >= 3:
        try:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            return s
        try:
            date(y, m, d)  # validate impossible dates like 2/30, 13/05
        except ValueError:
            return ""
        return f"{y:04d}/{m:02d}/{d:02d}"
    return s
