"""Streamlit Cloud entry point for the v3.0 dynamic Lotto picker."""

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
)
from src.generator.history_engine import DEFAULTS, POOL_MAX, POOL_MIN
from src.generator.lotto_picker import (
    ALLOWED_ODD_COUNTS,
    BIG_THRESHOLD,
    MAX_CONSECUTIVE_PAIRS,
    MAX_PRIME_COUNT,
    MIN_BIG_COUNT,
    MIN_PRIME_COUNT,
    SUM_MAX,
    SUM_MIN,
    TICKET_SIZE,
    generate_tickets,
    ticket_stats,
)

SAMPLE_CSV_PATH = Path(__file__).parent / "data" / "lotto649.csv"

st.set_page_config(
    page_title="大樂透動態量化選號 v3.0",
    page_icon="🎰",
    layout="wide",
)

st.title("🎰 大樂透動態量化選號系統 v3.0")
st.caption(
    "雙層過濾架構：動態歷史 (熱/溫/冷 + 雙向尾數排除) → 靜態五大濾網。"
    "EV<0 仍是大樂透數學本質；本工具僅優化資金運用。"
)


# --- Cached data loading ------------------------------------------------------


@st.cache_data(show_spinner=False)
def _load_bundled_csv() -> list[list[int]]:
    return load_csv_file(SAMPLE_CSV_PATH)


@st.cache_data(show_spinner=False)
def _load_upload(payload: bytes, name: str) -> list[list[int]]:
    text = payload.decode("utf-8", errors="replace")
    if name.lower().endswith(".json"):
        from src.data.loader import load_json_string
        return load_json_string(text)
    return load_csv_string(text)


# --- Sidebar inputs -----------------------------------------------------------

with st.sidebar:
    st.header("📥 歷史資料")
    source = st.radio(
        "資料來源",
        options=["倉庫內附 (data/lotto649.csv)", "上傳 CSV / JSON", "貼上文字"],
        index=0,
        help="Streamlit Cloud 無法存取外部 API 時，請改用上傳或貼上模式。",
    )
    uploaded_file = None
    pasted = ""
    if source == "上傳 CSV / JSON":
        uploaded_file = st.file_uploader(
            "上傳檔案",
            type=["csv", "json"],
            help="CSV 欄位 n1..n6；或 JSON [{\"draw\":[..]}]",
        )
    elif source == "貼上文字":
        pasted = st.text_area(
            "貼上 CSV 或 JSON",
            height=160,
            help="會自動偵測格式：以 `[` 開頭視為 JSON；否則 CSV。",
        )

    st.header("🎛️ 動態閾值")
    hot_max_gap = st.slider("熱碼最大遺漏期", 0, 5, DEFAULTS["hot_max_gap"])
    warm_max_gap = st.slider(
        "溫碼最大遺漏期", hot_max_gap + 1, 30, DEFAULTS["warm_max_gap"]
    )
    overheat_recent = st.slider(
        "過熱觀察期數", 1, 10, DEFAULTS["overheat_recent_periods"]
    )
    overheat_min = st.slider(
        "過熱判定次數", 1, 10, DEFAULTS["overheat_min_count"]
    )
    dormant_periods = st.slider(
        "死寂判定期數", 5, 30, DEFAULTS["dormant_periods"]
    )

    st.header("🎯 膽碼模式")
    key_mode = st.radio(
        "雙膽", ["動態 (1 熱 + 1 冷)", "手動指定"], horizontal=True
    )
    manual_keys: list[int] | None = None
    if key_mode == "手動指定":
        manual_keys = st.multiselect(
            "手動膽碼 (1-5 顆)",
            options=list(range(POOL_MIN, POOL_MAX + 1)),
            default=[7, 33],
        )

    tail_mode = st.radio(
        "排除尾數", ["動態 (過熱 ∪ 死寂)", "手動指定"], horizontal=True
    )
    manual_excluded_tails: list[int] | None = None
    if tail_mode == "手動指定":
        manual_excluded_tails = st.multiselect(
            "手動排除尾數",
            options=list(range(10)),
            default=[],
        )

    st.header("⚙️ 產出")
    num_tickets = st.slider("注數", 1, 50, 5)
    seed = st.number_input(
        "隨機種子（0 = 不固定）", min_value=0, max_value=10_000_000,
        value=0, step=1,
    )
    go = st.button("🎲 產生選號", type="primary", use_container_width=True)

with st.sidebar.expander("📐 五大靜態濾網"):
    st.markdown(
        f"""
- **和值**：`{SUM_MIN} ≤ sum ≤ {SUM_MAX}`
- **奇偶**：`奇數 ∈ {sorted(ALLOWED_ODD_COUNTS)}`
- **大數**：`> {BIG_THRESHOLD} 至少 {MIN_BIG_COUNT} 個`
- **質數**：`{MIN_PRIME_COUNT} ≤ 質數 ≤ {MAX_PRIME_COUNT}`
- **連號**：`連號對數 ≤ {MAX_CONSECUTIVE_PAIRS}`
"""
    )


# --- Main panel ---------------------------------------------------------------

if not go:
    st.info("← 設定參數後按『產生選號』。預設使用倉庫內附 50 期合成樣本。")
    st.stop()

# Resolve history input
try:
    if source == "上傳 CSV / JSON":
        if uploaded_file is None:
            st.error("請先上傳檔案。")
            st.stop()
        history = _load_upload(uploaded_file.getvalue(), uploaded_file.name)
    elif source == "貼上文字":
        if not pasted.strip():
            st.error("請貼上至少一期資料。")
            st.stop()
        history = load_auto(pasted)
    else:
        history = _load_bundled_csv()
except HistoryLoadError as exc:
    st.error(f"歷史資料解析失敗：{exc}")
    st.stop()

st.caption(f"📊 已載入 **{len(history)}** 期歷史資料 (最新優先)")

rng = random.Random(seed) if seed else None

try:
    tickets, analysis = generate_tickets(
        history_draws=history,
        num_tickets=num_tickets,
        hot_max_gap=hot_max_gap,
        warm_max_gap=warm_max_gap,
        overheat_recent_periods=overheat_recent,
        overheat_min_count=overheat_min,
        dormant_periods=dormant_periods,
        manual_keys=manual_keys if manual_keys else None,
        manual_excluded_tails=manual_excluded_tails,
        rng=rng,
    )
except ValueError as exc:
    st.error(f"參數錯誤：{exc}")
    st.stop()

# --- Phase 1 analysis cards ---
st.subheader("🌡️ Phase 1 — 動態歷史分析")
c1, c2, c3 = st.columns(3)
c1.metric("熱碼 (≤ {} 期)".format(hot_max_gap), f"{len(analysis.hot)} 顆")
c1.caption(", ".join(f"{n:02d}" for n in analysis.hot) or "—")
c2.metric("溫碼", f"{len(analysis.warm)} 顆")
c2.caption(", ".join(f"{n:02d}" for n in analysis.warm) or "—")
c3.metric("冷碼 (> {} 期)".format(warm_max_gap), f"{len(analysis.cold)} 顆")
c3.caption(", ".join(f"{n:02d}" for n in analysis.cold) or "—")

t1, t2 = st.columns(2)
t1.metric(
    "排除尾數 (過熱 ∪ 死寂)",
    str(analysis.exclude_tails) if analysis.exclude_tails else "—",
)
t1.caption(
    f"過熱：{analysis.overheated_tails or '—'} · 死寂：{analysis.dormant_tails or '—'}"
)
t2.metric(
    "本回合膽碼",
    ", ".join(f"{n:02d}" for n in (manual_keys if manual_keys else analysis.auto_keys)),
)
t2.caption("動態" if not manual_keys else "手動覆寫")

if not tickets:
    st.warning("通過五大濾網的組合為 0。放寬閾值或縮少手動限制再試。")
    st.stop()

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
