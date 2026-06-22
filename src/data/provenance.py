"""Provenance wrapper — CLAUDE.md §2.2 血緣追蹤實作。

設計取捨(對應憲法既有條款):
  - **純信號 dataclass (HistoryAnalysis / PowerballAnalysis) 不灌 provenance**
    — 引擎側維持 stdlib-only 純度,避免測試 fixture 一律要塞 fetched_at
  - **provenance 在資料載入層包裝**;loader 提供 `_with_provenance`
    additive 變體,不破壞既有 API、零回溯改造
  - **`as_of` 取 CSV 內最新 `draw_date`** 而非 wall-clock —
    這是業務歸屬日,跟資料本身綁定

Stdlib only(`datetime` + `dataclasses`)。
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class HistoryProvenance:
    """Loading-time metadata about a draws snapshot.

    Fields:
        source:     資料來源識別(`data/lotto649.csv`、`<upload:file.csv>`、`<paste>` 等)
        fetched_at: UTC,本次載入發生的 wall-clock 時刻
        n_rows:     成功 parse 的 draws 數量
        as_of:      CSV 內最新的 `draw_date`(資料歸屬日);全空則為 None
        earliest:   CSV 內最舊的 `draw_date`;全空則為 None
    """
    source: str
    fetched_at: datetime
    n_rows: int
    as_of: date | None = None
    earliest: date | None = None


def now_utc() -> datetime:
    """Inject point for tests; production wall-clock UTC."""
    return datetime.now(timezone.utc)


def extract_dates(
    rows: Iterable[dict],
) -> tuple[date | None, date | None]:
    """從 CSV DictReader rows 抽出 (as_of, earliest);全空回 (None, None)。

    Pure helper — 不 raise、不修改 rows、不污染外部狀態。
    """
    dates: list[date] = []
    for row in rows:
        raw = (row.get("draw_date") or "").strip()
        if not raw:
            continue
        try:
            dates.append(datetime.strptime(raw, "%Y/%m/%d").date())
        except ValueError:
            continue
    if not dates:
        return None, None
    return max(dates), min(dates)


def build_provenance_from_rows(
    rows: list[dict],
    source: str,
    n_parsed: int,
) -> HistoryProvenance:
    """Wrap loaded CSV rows with provenance metadata."""
    as_of, earliest = extract_dates(rows)
    return HistoryProvenance(
        source=source,
        fetched_at=now_utc(),
        n_rows=n_parsed,
        as_of=as_of,
        earliest=earliest,
    )


def read_csv_rows(text_or_path: str | Path) -> list[dict]:
    """Helper to fetch raw CSV rows for provenance extraction.

    Accepts a Path(file) or str(raw CSV text)。對 path 不存在 / I/O 失敗
    回空 list — 真正驗證走 loader.from_csv_rows 的 strict 路徑。
    """
    if isinstance(text_or_path, Path):
        if not text_or_path.exists():
            return []
        with text_or_path.open("r", encoding="utf-8", newline="") as fp:
            return list(csv.DictReader(fp))
    return list(csv.DictReader(io.StringIO(text_or_path)))


def format_provenance_caption(prov: HistoryProvenance) -> str:
    """UI helper — 一句話可讀格式 for `st.caption`。"""
    src_short = prov.source
    if len(src_short) > 40:
        src_short = "…" + src_short[-37:]
    parts = [f"📦 {prov.n_rows} 期"]
    if prov.as_of:
        parts.append(f"最新 {prov.as_of.isoformat()}")
    if prov.earliest and prov.earliest != prov.as_of:
        parts.append(f"最舊 {prov.earliest.isoformat()}")
    parts.append(f"來源 `{src_short}`")
    parts.append(f"載入 {prov.fetched_at:%H:%M UTC}")
    return " · ".join(parts)
