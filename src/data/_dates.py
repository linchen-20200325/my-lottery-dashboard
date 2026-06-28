"""Data-layer date parsing (v6.24 T4 — SSOT for standardized CSV `draw_date`).

與 `scraper/_dates.py` **分工明確**(不可混用):
  - `scraper/_dates.canon_date`:**寬鬆**正規化「髒」API 原始輸入 → 標準字串
    (容忍全形、雜訊;只在離線 scraper 端用)
  - `data/_dates.parse_csv_date`(本檔):**嚴格** strptime 已標準化的 CSV
    `draw_date`('YYYY/MM/DD')→ `date` 物件;空字串 / 非法格式回 None。
    `provenance.extract_dates` 與 `freshness.latest_csv_date` 共用(消 S5 重複)。

Stdlib only(`datetime`)。
"""

from __future__ import annotations

from datetime import date, datetime

CSV_DATE_FORMAT = "%Y/%m/%d"


def parse_csv_date(raw: str) -> date | None:
    """嚴格解析標準化 CSV `draw_date` → `date`;空 / 非法格式回 None(不 raise)。

    Pure helper — 真正的 schema 驗證走 loader.from_csv_rows 的 strict 路徑;
    本函式刻意寬容(回 None 而非 raise),供 provenance / freshness 掃描用。
    """
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, CSV_DATE_FORMAT).date()
    except ValueError:
        return None
