"""DELIBERATE VIOLATION — verifying constitution-check.yml actually fails.

此檔故意違反 CLAUDE.md §0/§6(stdlib-only)+ §1(silent except)。
若 CI gate 工作正常,本檔的 PR 應該紅燈無法 merge。
驗證後立即刪除整個 PR / branch — 絕不進 main。
"""

from __future__ import annotations

import pandas as pd  # noqa: F401 — DELIBERATE: violates stdlib-only rule


def silently_eat_errors() -> None:
    # DELIBERATE: violates Fail Loud rule via multi-line except / pass.
    try:
        1 / 0
    except Exception:
        pass


def use_pandas_imputation(df) -> object:
    return df.fillna(0)  # DELIBERATE: violates no-pandas-imputation
