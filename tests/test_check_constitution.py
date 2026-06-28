"""scripts/check_constitution.py 的單元測試。

兩個目的:
  1. 確保檢查器對當前(已通過 v6.4-v6.5 落地的)codebase 全綠
  2. 對每條 rule 用人造違規來驗證它真的會抓到 — 避免「假 pass」
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.check_constitution import (
    RULES,
    Violation,
    check_canon_date_validates,
    check_docs_exist,
    check_invariant_asserts_present,
    check_newest_first_invariant,
    check_no_pandas_imputation,
    check_no_silent_except,
    check_stdlib_only,
    main,
)


class TestCurrentCodebasePasses(unittest.TestCase):
    """當前 codebase 必須通過所有規則(snapshot test)。"""

    def test_all_rules_pass(self):
        violations: list[Violation] = []
        for name, fn in RULES:
            v = fn()
            violations.extend(v)
        if violations:
            formatted = "\n".join(v.format() for v in violations)
            self.fail(f"current codebase has {len(violations)} violations:\n{formatted}")

    def test_main_returns_zero(self):
        # main() 印 stdout + 回 exit code
        exit_code = main()
        self.assertEqual(exit_code, 0)


class TestRulesActuallyCatchViolations(unittest.TestCase):
    """注入式違規:確保檢查器不會「總是 pass」。"""

    def test_stdlib_only_catches_pandas_import(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "src" / "generator").mkdir(parents=True)
            bad = tmp_path / "src" / "generator" / "bad.py"
            bad.write_text("import pandas as pd\n")
            with patch("scripts.check_constitution.ROOT", tmp_path):
                violations = check_stdlib_only()
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].rule, "stdlib-only")
            self.assertIn("pandas", violations[0].why)

    def test_silent_except_catches(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "src" / "data").mkdir(parents=True)
            bad = tmp_path / "src" / "data" / "bad.py"
            bad.write_text("try:\n    1/0\nexcept:\n    pass\n")
            with patch("scripts.check_constitution.ROOT", tmp_path):
                violations = check_no_silent_except()
            self.assertEqual(len(violations), 1)

    def test_pandas_imputation_catches_fillna(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "src" / "analytics").mkdir(parents=True)
            bad = tmp_path / "src" / "analytics" / "bad.py"
            bad.write_text("df.fillna(0)\n")
            with patch("scripts.check_constitution.ROOT", tmp_path):
                violations = check_no_pandas_imputation()
            self.assertEqual(len(violations), 1)

    def test_newest_first_missing(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "src" / "analytics").mkdir(parents=True)
            bad = tmp_path / "src" / "analytics" / "backtest.py"
            # 故意不含 guard 字串(連註解都不能有,否則檢查器會誤判)
            bad.write_text("# placeholder backtest with no guard\n")
            with patch("scripts.check_constitution.ROOT", tmp_path):
                violations = check_newest_first_invariant()
            self.assertEqual(len(violations), 1)

    def test_canon_date_without_validation(self):
        # v6.22:正規化邏輯收斂至 src/scraper/_dates.py;注入無驗證版本應被抓到。
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "src" / "scraper").mkdir(parents=True)
            bad = tmp_path / "src" / "scraper" / "_dates.py"
            bad.write_text("def canon_date(s):\n    return s  # no validation\n")
            with patch("scripts.check_constitution.ROOT", tmp_path):
                violations = check_canon_date_validates()
            self.assertEqual(len(violations), 1)

    def test_docs_missing(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # 完全沒有任何 .md
            with patch("scripts.check_constitution.ROOT", tmp_path):
                violations = check_docs_exist()
            self.assertEqual(len(violations), 3)  # CLAUDE / STATE / ARCHITECTURE

    def test_invariant_asserts_missing(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "src" / "generator").mkdir(parents=True)
            # v6.23 B4a:partition 斷言收斂至 base_engine(SSOT)→ 以它當缺失目標
            (tmp_path / "src" / "generator" / "base_engine.py").write_text(
                "# no invariant assert here\n"
            )
            with patch("scripts.check_constitution.ROOT", tmp_path):
                violations = check_invariant_asserts_present()
            # required 5 個 sentinel 對應 5 檔;只 create 了 base_engine,
            # 其餘 4 檔不存在 → continue,故只回 base_engine 的 1 個違規
            self.assertEqual(len(violations), 1)
            self.assertIn("base_engine", violations[0].file)


if __name__ == "__main__":
    unittest.main()
