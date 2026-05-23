"""Streamlit Cloud entry point — v5.0 signal dashboard with graceful degradation."""

from __future__ import annotations

import random
from pathlib import Path

import streamlit as st

from src.analytics.cost_calc import UNIT_PRICE_TWD, summary as cost_summary
from src.data.loader import (
    HistoryLoadError,
    load_auto,
    load_csv_file,
    load_csv_string,
    load_json_string,
    preview_recent,
)
from src.generator.history_engine import (
    DEFAULTS,
    POOL_MAX,
    POOL_MIN,
    STATIC_FALLBACK_ANALYSIS,
    HistoryAnalysis,
    analyze,
)
from src.generator.lotto_picker import (
    ALLOWED_ODD_COUNTS,
    BIG_THRESHOLD,
    MAX_CONSECUTIVE_PAIRS,
    MAX_PRIME_COUNT,
    MIN_BIG_COUNT,
    MIN_PRIME_COUNT,
    SUM_MAX,
    SUM_MIN,
    generate_tickets,
    ticket_stats,
)

SAMPLE_CSV_PATH = Path(__file__).parent / "data" / "lotto649.csv"

st.set_page_config(
    page_title="大樂透量化訊號儀表板 v5.0",
    page_icon="🎰",
    layout="wide",
)

st.title("🎰 大樂透量化訊號儀表板 v5.0")
st.caption(
    "Signal-Driven · Z-Score 動態冷熱 + SMA 動態和值 · 容錯架構 (Graceful Degradation)。"
    "EV<0 為大樂透數學本質；本工具僅優化資金運用。"
)


# --- Cached load + analyze (Phase 2: cache + fallback) ------------------------


@st.cache_data(ttl=3600, show_spinner=False)
def _load_bundled() -> list[list[int]]:
    return load_csv_file(SAMPLE_CSV_PATH)


@st.cache_data(ttl=3600, show_spinner=False)
def _load_upload(payload: bytes, name: str) -> list[list[int]]:
    text = payload.decode("utf-8", errors="replace")
    if name.lower().endswith(".json"):
        return load_json_string(text)
    return load_csv_string(text)


@st.cache_data(ttl=3600, show_spinner=False)
def _preview_bundled(limit: int) -> list[dict]:
    return preview_recent(SAMPLE_CSV_PATH, limit=limit)


@st.cache_data(ttl=3600, show_spinner=False)
def _preview_upload(payload: bytes, _name: str, limit: int) -> list[dict]:
    return preview_recent(payload, limit=limit)


@st.cache_data(ttl=3600, show_spinner=False)
def _preview_text(text: str, limit: int) -> list[dict]:
    return preview_recent(text, limit=limit)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_analysis(
    history: list[list[int]],
    hot_sigma: float,
    cold_sigma: float,
    sma_window: int,
    range_pad: int,
    overheat_recent: int,
    overheat_min: int,
    dormant_periods: int,
    seed: int,
) -> HistoryAnalysis:
    rng = random.Random(seed) if seed else random.Random()
    return analyze(
        draws=history,
        hot_sigma_factor=hot_sigma,
        cold_sigma_factor=cold_sigma,
        sum_sma_window=sma_window,
        sum_range_pad=range_pad,
        overheat_recent_periods=overheat_recent,
        overheat_min_count=overheat_min,
        dormant_periods=dormant_periods,
        rng=rng,
    )


# --- Sidebar ------------------------------------------------------------------

with st.sidebar:
    st.header("📥 歷史資料")
    source = st.radio(
        "資料來源",
        options=["倉庫內附 (data/lotto649.csv)", "上傳 CSV / JSON", "貼上文字"],
        index=0,
        help="Streamlit Cloud 不發外部 API。失敗時 UI 會自動降級至靜態安全模式。",
    )
    uploaded_file = None
    pasted = ""
    if source == "上傳 CSV / JSON":
        uploaded_file = st.file_uploader("上傳檔案", type=["csv", "json"])
    elif source == "貼上文字":
        pasted = st.text_area("貼上 CSV 或 JSON", height=160)

    preview_limit = st.slider(
        "📋 預覽近 N 期", 1, 20, 5,
        help="主面板頂部會顯示最近 N 期開獎，用來驗證資料是否正確下載/上傳。",
    )

    st.divider()
    st.markdown("**🤖 自動更新歷史資料**")
    st.link_button(
        "🚀 觸發 GitHub Actions 抓檔",
        url="https://github.com/LinChen-20200325/my-lottery-dashboard/actions/workflows/update-history.yml",
        use_container_width=True,
    )
    st.caption(
        "新分頁打開後，右上角點 **Run workflow** → 選 `main` → 再點 **Run workflow**。"
        "成功的話 Action bot 會自動補新一期到 CSV、推 main、Cloud 自動 redeploy（1-3 分鐘）。"
    )

    st.header("🌡️ Z-Score 冷熱閾值")
    hot_sigma = st.slider(
        "熱碼倍率 (μ − Nσ)", 0.0, 1.5, DEFAULTS["hot_sigma_factor"], step=0.1
    )
    cold_sigma = st.slider(
        "冷碼倍率 (μ + Nσ)", 0.5, 3.0, DEFAULTS["cold_sigma_factor"], step=0.1
    )

    st.header("📈 動態和值 (SMA)")
    sma_window = st.slider(
        "SMA 視窗 (期數)", 5, 30, DEFAULTS["sum_sma_window"]
    )
    range_pad = st.slider(
        "和值 ±pad", 10, 60, DEFAULTS["sum_range_pad"]
    )

    st.header("🎚️ 尾數訊號")
    overheat_recent = st.slider(
        "過熱觀察期", 1, 10, DEFAULTS["overheat_recent_periods"]
    )
    overheat_min = st.slider(
        "過熱判定次數", 1, 10, DEFAULTS["overheat_min_count"]
    )
    dormant_periods = st.slider(
        "死寂判定期", 5, 30, DEFAULTS["dormant_periods"]
    )

    st.header("🎯 膽碼 / 排除 (覆寫)")
    key_mode = st.radio(
        "雙膽", ["動態", "手動"], horizontal=True
    )
    manual_keys: list[int] | None = None
    if key_mode == "手動":
        manual_keys = st.multiselect(
            "手動膽碼 (1-5 顆)",
            options=list(range(POOL_MIN, POOL_MAX + 1)),
            default=[7, 33],
        )

    tail_mode = st.radio(
        "排除尾數", ["動態", "手動"], horizontal=True
    )
    manual_excluded_tails: list[int] | None = None
    if tail_mode == "手動":
        manual_excluded_tails = st.multiselect(
            "手動排除尾數",
            options=list(range(10)),
            default=[],
        )

    st.subheader("🚫 排除特定號碼")
    st.caption("點擊號碼即可加入/移除排除清單；空 = 不排除任何號碼。")
    _key_set = set(manual_keys) if manual_keys else set()
    _excl_options = [n for n in range(POOL_MIN, POOL_MAX + 1) if n not in _key_set]
    if _key_set:
        st.caption(
            f"（已自動隱藏手動膽碼 {sorted(_key_set)}，避免與排除清單衝突）"
        )
    if hasattr(st, "pills"):
        manual_excluded_numbers = st.pills(
            "點擊號碼",
            options=_excl_options,
            selection_mode="multi",
            default=[],
            format_func=lambda n: f"{n:02d}",
            label_visibility="collapsed",
        )
    else:
        manual_excluded_numbers = st.multiselect(
            "排除號碼（升級 streamlit≥1.39 可享按鈕點選 UI）",
            options=_excl_options,
            default=[],
            format_func=lambda n: f"{n:02d}",
        )
    if manual_excluded_numbers:
        st.caption(
            f"已排除 **{len(manual_excluded_numbers)}** 顆："
            + ", ".join(f"{n:02d}" for n in sorted(manual_excluded_numbers))
        )

    sum_mode = st.radio(
        "和值區間", ["動態 SMA", "手動"], horizontal=True
    )
    manual_sum_range: tuple[int, int] | None = None
    if sum_mode == "手動":
        s_lo, s_hi = st.slider(
            "手動和值區間", 90, 210, (SUM_MIN, SUM_MAX)
        )
        manual_sum_range = (s_lo, s_hi)

    st.header("⚙️ 產出")
    num_tickets = st.slider("注數", 1, 50, 5)

    pair_disjoint = st.checkbox(
        "🧩 五注 pair 不重複",
        value=False,
        help=(
            "開啟後，任兩注之間沒有任何 2 號 pair 重複。"
            "需 ≤ 1 顆膽碼（2 顆以上膽碼會強制 pair 重複，與本模式互斥）。"
        ),
    )
    if pair_disjoint:
        pair_overlap_max = st.slider(
            "允許 pair 共享上限",
            min_value=0, max_value=3, value=0, step=1,
            help=(
                "0 = 嚴格 pair-disjoint；湊不滿 N 注時可調高，"
                "依序放寬到允許每注最多跟既有 ticket 共享 K 個 pair。"
            ),
        )
    else:
        pair_overlap_max = 0

    seed = st.number_input(
        "隨機種子（0 = 不固定）", min_value=0, max_value=10_000_000,
        value=0, step=1,
    )
    go = st.button("🎲 產生選號", type="primary", use_container_width=True)

with st.sidebar.expander("📐 五大濾網規則"):
    st.markdown(
        f"""
- **質數**：`{MIN_PRIME_COUNT} ≤ 質數 ≤ {MAX_PRIME_COUNT}`
- **連號**：`連號對數 ≤ {MAX_CONSECUTIVE_PAIRS}`
- **動態和值**：`Phase 1 計算區間` (失敗回 `{SUM_MIN}-{SUM_MAX}`)
- **奇偶**：`奇數 ∈ {sorted(ALLOWED_ODD_COUNTS)}`
- **大數**：`> {BIG_THRESHOLD} 至少 {MIN_BIG_COUNT} 個`
"""
    )


# --- Main panel ---------------------------------------------------------------

# --- Phase 2: always-attempt load (graceful degradation; pre-go for preview) ---
fallback_reason: str | None = None
history: list[list[int]] = []
awaiting_input = False
try:
    if source == "上傳 CSV / JSON":
        if uploaded_file is None:
            awaiting_input = True
        else:
            history = _load_upload(uploaded_file.getvalue(), uploaded_file.name)
    elif source == "貼上文字":
        if not pasted.strip():
            awaiting_input = True
        else:
            history = load_auto(pasted)
    else:
        history = _load_bundled()
except (HistoryLoadError, OSError) as exc:
    fallback_reason = f"歷史載入失敗：{exc}"

if fallback_reason:
    st.warning(
        f"⚠️ **降級至靜態安全模式**：{fallback_reason}。"
        f"已套用預設區間 {SUM_MIN}-{SUM_MAX}、無冷熱訊號。"
    )

st.caption(f"📊 已載入 **{len(history)}** 期歷史資料")

# --- Always-on preview pane (verify download/upload correctness) ---
if source == "上傳 CSV / JSON" and uploaded_file is not None:
    preview_rows = _preview_upload(
        uploaded_file.getvalue(), uploaded_file.name, preview_limit
    )
elif source == "貼上文字" and pasted.strip():
    preview_rows = _preview_text(pasted, preview_limit)
elif source not in ("上傳 CSV / JSON", "貼上文字"):
    preview_rows = _preview_bundled(preview_limit)
else:
    preview_rows = []

if preview_rows:
    st.subheader(f"📋 最近 {len(preview_rows)} 期歷史 — 驗證資料")
    header = (
        "| 期別 | 日期 | 1 | 2 | 3 | 4 | 5 | 6 | 特別號 |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
    )
    body = "\n".join(
        "| " + r["term"] + " | " + r["date"] + " | "
        + " | ".join(f"`{n:02d}`" for n in r["nums"])
        + " | `" + r["special"] + "` |"
        for r in preview_rows
    )
    st.markdown(header + body)
elif awaiting_input:
    st.info("📋 預覽待命中 — 上傳或貼上資料後即可預覽近期開獎。")

st.divider()

if not go:
    st.info("← 設定參數後按『產生選號』。預設使用倉庫內附歷史資料。")
    st.stop()

# --- Analyze (post-go, since it depends on sliders) ---
if history and not fallback_reason:
    try:
        analysis = cached_analysis(
            history,
            hot_sigma, cold_sigma,
            sma_window, range_pad,
            overheat_recent, overheat_min, dormant_periods,
            seed,
        )
    except (ValueError, Exception) as exc:  # noqa: BLE001 — defensive
        fallback_reason = f"動態分析失敗：{exc}"
        analysis = STATIC_FALLBACK_ANALYSIS
else:
    analysis = STATIC_FALLBACK_ANALYSIS

if analysis.is_fallback:
    st.caption("模式：⚠️ 靜態 Fallback")
else:
    st.caption("模式：✅ 動態 Signal")

# --- Generate ---
if manual_keys and manual_excluded_numbers:
    _conflict = sorted(set(manual_keys) & set(manual_excluded_numbers))
    if _conflict:
        st.error(
            f"參數衝突：號碼 {_conflict} 同時被列為膽碼與排除清單，請擇一。"
        )
        st.stop()

if pair_disjoint and manual_keys and len(manual_keys) >= 2:
    st.error(
        f"pair-disjoint 模式下手動膽碼最多 1 顆（目前 {len(manual_keys)} 顆）— "
        "請改成 0 或 1 顆膽碼，或關閉「五注 pair 不重複」。"
    )
    st.stop()

rng = random.Random(seed) if seed else None
try:
    tickets, _ = generate_tickets(
        history_draws=history if history else [[1, 2, 3, 4, 5, 6]],  # dummy seed if all-fallback
        num_tickets=num_tickets,
        manual_keys=manual_keys if manual_keys else None,
        manual_excluded_tails=manual_excluded_tails,
        manual_excluded_numbers=list(manual_excluded_numbers) if manual_excluded_numbers else None,
        manual_sum_range=manual_sum_range,
        precomputed_analysis=analysis,
        pair_disjoint=pair_disjoint,
        pair_overlap_max=pair_overlap_max,
        rng=rng,
    )
except ValueError as exc:
    st.error(f"參數錯誤：{exc}")
    st.stop()

# --- Phase 1 signal cards ---
st.subheader("🌡️ Phase 1 — 動態訊號分析")
c1, c2, c3 = st.columns(3)
c1.metric(
    f"熱碼 (gap ≤ {analysis.hot_threshold:.1f})",
    f"{len(analysis.hot)} 顆",
    help=f"μ={analysis.gap_mean:.2f} σ={analysis.gap_std:.2f}",
)
c1.caption(", ".join(f"{n:02d}" for n in analysis.hot) or "—")
c2.metric("溫碼", f"{len(analysis.warm)} 顆")
c2.caption(", ".join(f"{n:02d}" for n in analysis.warm) or "—")
c3.metric(f"冷碼 (gap ≥ {analysis.cold_threshold:.1f})", f"{len(analysis.cold)} 顆")
c3.caption(", ".join(f"{n:02d}" for n in analysis.cold) or "—")

s1, s2 = st.columns(2)
s1.metric(
    "動態和值區間",
    f"{analysis.sum_min_dynamic} – {analysis.sum_max_dynamic}",
    help=f"SMA={analysis.sum_sma:.1f} ± {DEFAULTS['sum_range_pad']}",
)
s1.caption(
    "（手動覆寫 → "
    + (f"{manual_sum_range[0]}–{manual_sum_range[1]}" if manual_sum_range else "未啟用")
    + "）"
)
s2.metric(
    "排除尾數",
    str(analysis.exclude_tails) if analysis.exclude_tails else "—",
)
s2.caption(
    f"過熱：{analysis.overheated_tails or '—'} · 死寂：{analysis.dormant_tails or '—'}"
)

# --- Silent-drop notice: auto-key collided with user exclusion ---
if not manual_keys and manual_excluded_numbers:
    _silent_dropped = sorted(set(analysis.auto_keys) & set(manual_excluded_numbers))
    if _silent_dropped:
        st.caption(
            f"ℹ️ 自動膽碼 {_silent_dropped} 與你的排除清單衝突 — 已自動移除（不影響選號）。"
        )

if not tickets:
    st.warning(
        "通過五大濾網的組合為 0；Round 2 disjoint fallback 亦無解。"
        "請放寬閾值或縮少手動限制再試。"
    )
    st.stop()

# --- pair-disjoint mode: report strict vs relaxed split ---
if pair_disjoint and len(tickets) >= 1:
    from itertools import combinations as _combs_ui
    _strict = 0
    _relaxed = 0
    _seen_pairs: set[frozenset[int]] = set()
    for _t in tickets:
        _ticket_pairs = {frozenset(p) for p in _combs_ui(_t, 2)}
        if not (_ticket_pairs & _seen_pairs):
            _strict += 1
        else:
            _relaxed += 1
        _seen_pairs |= _ticket_pairs
    if len(tickets) < num_tickets:
        st.warning(
            f"🧩 pair-disjoint：已產出 **{len(tickets)} / {num_tickets}** 注"
            f"（嚴格 {_strict} 注 ｜ 放寬 {_relaxed} 注）— "
            f"若需更多注，調高「允許 pair 共享上限」(目前 {pair_overlap_max})。"
        )
    else:
        st.success(
            f"🧩 pair-disjoint：已產出 {len(tickets)} 注"
            f"（嚴格 {_strict} 注 ｜ 放寬 {_relaxed} 注）"
        )
    # Skip the legacy R1/R2 split (pair-disjoint replaces both rounds)
    _skip_legacy_split = True
else:
    _skip_legacy_split = False

# Detect Round 2 fallback tickets (those that don't carry the effective keys)
_effective_keys = (
    set(manual_keys) if manual_keys
    else set(analysis.auto_keys) - set(manual_excluded_numbers or [])
)
_r1 = [t for t in tickets if _effective_keys.issubset(t)] if _effective_keys else tickets
_r2 = [t for t in tickets if not _effective_keys.issubset(t)] if _effective_keys else []

if _skip_legacy_split:
    pass  # pair-disjoint mode already reported above
elif len(tickets) < num_tickets:
    if _r2:
        st.success(
            f"✅ 已產出 **{len(tickets)} / {num_tickets}** 注 "
            f"（Round 1: {len(_r1)} 注 ｜ Round 2 disjoint 補齊: {len(_r2)} 注）"
        )
        st.caption(
            "💡 Round 2 為 disjoint fallback — 票面不含膽碼，且與 Round 1 票"
            "完全不共號（六顆主號互斥）。"
        )
    else:
        st.warning(
            f"⚠️ 已產出 **{len(tickets)} / {num_tickets}** 注 "
            f"（濾網太嚴或排除過多 → 連 Round 2 disjoint 補齊都無解）"
        )
else:
    st.success(f"✅ 已產出 {len(tickets)} 注合格組合（目標 {num_tickets} 注）")

# --- Cost panel ---
keys_used = manual_keys if manual_keys else analysis.auto_keys
tail_set_used = (
    set(manual_excluded_tails)
    if manual_excluded_tails is not None
    else set(analysis.exclude_tails)
)
_pool = {n for n in range(POOL_MIN, POOL_MAX + 1) if (n % 10) not in tail_set_used}
_drag_pool = _pool - set(keys_used)
try:
    cs = cost_summary(len(keys_used), len(_drag_pool))
    k1, k2, k3 = st.columns(3)
    k1.metric("膽碼 / 拖碼池", f"{len(keys_used)} / {len(_drag_pool)}")
    k2.metric(
        "全包牌注數 C(drag, 6−key)",
        f"{cs['wheel_ticket_count']:,}",
        help=f"每注 NT${UNIT_PRICE_TWD}；本工具僅輸出過濾後子集。",
    )
    k3.metric("全包牌成本 (NT$)", f"{cs['wheel_cost_twd']:,}")
except ValueError:
    pass

col_left, col_right = st.columns([3, 2])

with col_left:
    st.subheader("🎟️ 推薦組合")
    for idx, ticket in enumerate(tickets, start=1):
        nums_str = "   ".join(f"`{n:02d}`" for n in ticket)
        st.markdown(f"**第 {idx} 注**：{nums_str}")

with col_right:
    st.subheader("📊 每注診斷")
    header = (
        "| # | sum | odd | big | prime | consec |\n"
        "|---|---|---|---|---|---|\n"
    )
    rows = []
    for idx, ticket in enumerate(tickets, start=1):
        s = ticket_stats(ticket)
        rows.append(
            f"| {idx} | {s['sum']} | {s['odd_count']} | {s['big_count']} "
            f"| {s['prime_count']} | {s['consecutive_pairs']} |"
        )
    st.markdown(header + "\n".join(rows))

st.caption(
    "提醒：本工具僅為數學優化器，無法改變獨立隨機事件之期望值；理性投注。"
)
