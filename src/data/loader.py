"""History data loader (大樂透 6/49).

Supports three input paths so the live app never depends on live scraping:
1. CSV file on disk (scraper output committed to repo).
2. Raw CSV string (uploaded via Streamlit file_uploader).
3. JSON list of `{"draw": [n1..n6], "term": "...", "date": "..."}` objects.

v6.22(B3):逐列驗證 / CSV·JSON 載入 / provenance 變體 / preview 收斂至
`src.data._loader_base`;本檔只保留大樂透 config(從 `DomainConfig.LOTTO649`
取號池/特別號值域 → SSOT)與薄 wrapper。回傳維持 `list[list[int]]`(newest
first),供 `src.generator.history_engine` 消費。

DR-1 修正:大樂透特別號改為「CSV/JSON 有 `special` 欄就驗 [1,49]、無則略過」,
補上原本完全不驗的漏洞(special 僅顯示用、非分析必需,故不強制)。

Stdlib only.
"""

from __future__ import annotations

from pathlib import Path

from src.data import _loader_base as base
from src.data._loader_base import LoaderConfig
from src.data.provenance import HistoryProvenance
from src.generator.domain import LOTTO649 as _DOM

TICKET_SIZE = _DOM.ticket_size
POOL_MIN, POOL_MAX = _DOM.pool_min, _DOM.pool_max


class HistoryLoadError(ValueError):
    """Raised when input cannot be parsed into valid draws."""


# 大樂透 LoaderConfig — 號池/特別號值域源自 DomainConfig(SSOT)。
# special_required=False:特別號非分析必需,有才驗(DR-1)。
_CFG = LoaderConfig(
    ticket_size=_DOM.ticket_size,
    pool_min=_DOM.pool_min,
    pool_max=_DOM.pool_max,
    special_min=_DOM.special_min,
    special_max=_DOM.special_max,
    special_required=False,
    error_cls=HistoryLoadError,
)


def from_csv_rows(rows: list[dict]) -> list[list[int]]:
    """Build draws list from DictReader rows (special 驗後丟棄,回 draws)。"""
    draws, _specials = base.from_csv_rows(rows, _CFG)
    return draws


def load_csv_file(path: Path | str) -> list[list[int]]:
    draws, _specials = base.load_csv_file(path, _CFG)
    return draws


def load_csv_string(text: str) -> list[list[int]]:
    draws, _specials = base.load_csv_string(text, _CFG)
    return draws


# --- §2.2 Provenance-annotated variants (additive; existing API unchanged) ---


def load_csv_file_with_provenance(
    path: Path | str,
) -> tuple[list[list[int]], HistoryProvenance]:
    """Like `load_csv_file` 但同時回傳 §2.2 血緣 metadata。"""
    draws, _specials, prov = base.load_csv_file_with_provenance(path, _CFG)
    return draws, prov


def load_csv_string_with_provenance(
    text: str, source: str = "<paste>",
) -> tuple[list[list[int]], HistoryProvenance]:
    draws, _specials, prov = base.load_csv_string_with_provenance(text, _CFG, source)
    return draws, prov


def load_json_string(text: str) -> list[list[int]]:
    draws, _specials = base.load_json_string(text, _CFG)
    return draws


def load_auto(text: str) -> list[list[int]]:
    """Try CSV first, JSON second. Helpful for one-field 'paste anything' UI."""
    draws, _specials = base.load_auto(text, _CFG)
    return draws


# --- UI-only helpers (lenient, never raise; for preview pane) -----------------


def preview_recent(source: Path | str | bytes, limit: int = 5) -> list[dict]:
    """Extract latest N rows with display metadata (term/date/nums/special).

    UI helper: returns [] silently on any parse failure so a malformed file
    doesn't crash the preview pane. The strict `load_csv_*` / `load_json_string`
    functions remain the source of truth for the generator engine.
    """
    return base.preview_recent(source, _CFG, limit)
