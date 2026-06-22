"""憲法自動稽核 — 把 CLAUDE.md §6 自審清單變成 CI gate。

跑法:
    python -m scripts.check_constitution

退出碼:0 = 全 pass;1 = 有違規。
每條規則對應 CLAUDE.md 哪一節,違規訊息會印 file:line + 為什麼違規。

新增規則的位置:在 `RULES` tuple 加一條 `(name, check_fn)`,
check_fn 回傳 `list[Violation]`。
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Violation:
    rule: str
    file: str
    line: int
    snippet: str
    why: str

    def format(self) -> str:
        loc = f"{self.file}:{self.line}" if self.line else self.file
        head = f"  {loc}  [{self.rule}]"
        if self.snippet:
            head += f"\n    {self.snippet.strip()}"
        head += f"\n    → {self.why}"
        return head


def _iter_src_files() -> list[Path]:
    """核心模組(generator / data / scraper / analytics);不含 UI / tests / streamlit_app。"""
    out: list[Path] = []
    for sub in ("generator", "data", "scraper", "analytics"):
        d = ROOT / "src" / sub
        if d.exists():
            out.extend(d.rglob("*.py"))
    return [p for p in out if "__pycache__" not in p.parts]


# --- Rules -------------------------------------------------------------------


def check_stdlib_only() -> list[Violation]:
    """CLAUDE.md §6 + §0 dependency limit:核心引擎禁 pandas / numpy。"""
    out: list[Violation] = []
    pat = re.compile(r"^\s*(?:import|from)\s+(pandas|numpy)\b")
    for f in _iter_src_files():
        for i, line in enumerate(f.read_text().splitlines(), 1):
            m = pat.match(line)
            if m:
                out.append(Violation(
                    "stdlib-only",
                    str(f.relative_to(ROOT)),
                    i,
                    line,
                    f"banned import: {m.group(1)} (CLAUDE.md §0/§6)",
                ))
    return out


def check_no_silent_except() -> list[Violation]:
    """CLAUDE.md §1 Fail Loud:禁 `except: pass` / `except <X>: pass`(單/雙行皆抓)。"""
    out: list[Violation] = []
    inline_pat = re.compile(r"^\s*except[^:]*:\s*pass\s*(#.*)?$")
    except_only_pat = re.compile(r"^(\s*)except[^:]*:\s*(#.*)?$")
    for f in _iter_src_files():
        lines = f.read_text().splitlines()
        for i, line in enumerate(lines, 1):
            if inline_pat.match(line):
                out.append(Violation(
                    "no-silent-except",
                    str(f.relative_to(ROOT)),
                    i,
                    line,
                    "silent exception swallow (CLAUDE.md §1)",
                ))
                continue
            m = except_only_pat.match(line)
            if m and i < len(lines):
                next_stripped = lines[i].strip()  # i 在 1-indexed loop = 下一行
                if next_stripped == "pass":
                    out.append(Violation(
                        "no-silent-except",
                        str(f.relative_to(ROOT)),
                        i,
                        line + "\n" + lines[i],
                        "silent exception swallow (multi-line, CLAUDE.md §1)",
                    ))
    return out


def check_no_pandas_imputation() -> list[Violation]:
    """CLAUDE.md §3.3 反捏造:禁 fillna / ffill / bfill 痕跡(本專案 stdlib-only)。"""
    out: list[Violation] = []
    pat = re.compile(r"\.(fillna|ffill|bfill)\s*\(")
    for f in _iter_src_files():
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if pat.search(line):
                out.append(Violation(
                    "no-pandas-imputation",
                    str(f.relative_to(ROOT)),
                    i,
                    line,
                    "pandas-style silent imputation (CLAUDE.md §1 + §3.3)",
                ))
    return out


def check_newest_first_invariant() -> list[Violation]:
    """CLAUDE.md §2.3 + §4.6:backtest 必須有 newest-first 不變量斷言。"""
    p = ROOT / "src/analytics/backtest.py"
    if not p.exists():
        return [Violation(
            "lookahead-protection", "src/analytics/backtest.py", 0, "",
            "file missing entirely",
        )]
    content = p.read_text()
    if "_assert_newest_first" not in content:
        return [Violation(
            "lookahead-protection", "src/analytics/backtest.py", 0, "",
            "_assert_newest_first guard missing (CLAUDE.md §2.3)",
        )]
    return []


def check_canon_date_validates() -> list[Violation]:
    """CLAUDE.md §3.1 schema:_canon_date 必須有 datetime.date(y,m,d) 合法性驗證。"""
    out: list[Violation] = []
    for path in (
        "src/scraper/lotto649_downloader.py",
        "src/scraper/powerball_downloader.py",
    ):
        p = ROOT / path
        if not p.exists():
            continue
        content = p.read_text()
        if "date(y, m, d)" not in content.replace(" ", "") and "date(y,m,d)" not in content.replace(" ", ""):
            # 寬鬆比對:剝空白後找 date(y,m,d)
            out.append(Violation(
                "canon-date-validates", path, 0, "",
                "_canon_date missing date(y,m,d) validation (CLAUDE.md §3.1)",
            ))
    return out


def check_docs_exist() -> list[Violation]:
    """CLAUDE.md §8.1:核心文件必須存在(冷熱分離)。"""
    out: list[Violation] = []
    for doc in ("CLAUDE.md", "STATE.md", "ARCHITECTURE.md"):
        if not (ROOT / doc).exists():
            out.append(Violation(
                "docs-exist", doc, 0, "",
                "required doc missing (CLAUDE.md §8.1)",
            ))
    return out


def check_invariant_asserts_present() -> list[Violation]:
    """CLAUDE.md §4.2:核心引擎必須有不變量斷言(v6.4 加入)。"""
    out: list[Violation] = []
    required = {
        "src/generator/history_engine.py": "set(hot) | set(warm) | set(cold)",
        "src/generator/powerball_engine.py": "set(hot) | set(warm) | set(cold)",
        "src/generator/lotto_picker.py": "ticket invariant violated",
        "src/generator/powerball_picker.py": "ticket invariant violated",
        "src/scraper/lotto649_downloader.py": "append-only violated",
        "src/scraper/powerball_downloader.py": "append-only violated",
    }
    for path, sentinel in required.items():
        p = ROOT / path
        if not p.exists():
            continue
        if sentinel not in p.read_text():
            out.append(Violation(
                "invariant-asserts", path, 0, "",
                f"missing assert sentinel '{sentinel}' (CLAUDE.md §4.2)",
            ))
    return out


RULES: tuple[tuple[str, callable], ...] = (
    ("stdlib-only", check_stdlib_only),
    ("no-silent-except", check_no_silent_except),
    ("no-pandas-imputation", check_no_pandas_imputation),
    ("lookahead-protection", check_newest_first_invariant),
    ("canon-date-validates", check_canon_date_validates),
    ("docs-exist", check_docs_exist),
    ("invariant-asserts", check_invariant_asserts_present),
)


def main() -> int:
    print("=== CLAUDE.md 憲法自動稽核 ===\n")
    all_violations: list[Violation] = []
    for name, fn in RULES:
        v = fn()
        status = "✅ PASS" if not v else f"❌ FAIL ({len(v)})"
        print(f"  [{status}] {name}")
        all_violations.extend(v)

    if all_violations:
        print(f"\n違規明細 ({len(all_violations)} 條):\n")
        for v in all_violations:
            print(v.format())
        return 1

    print(f"\n✅ 所有 {len(RULES)} 條憲法規則通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
