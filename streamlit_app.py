"""Streamlit Cloud entry point for the Lotto 6/49 quantitative picker."""

from __future__ import annotations

import random

import streamlit as st

from src.generator.lotto_picker import (
    ALLOWED_ODD_COUNTS,
    BIG_THRESHOLD,
    MIN_BIG_COUNT,
    POOL_MAX,
    POOL_MIN,
    SUM_MAX,
    SUM_MIN,
    generate_tickets,
    ticket_stats,
)

st.set_page_config(
    page_title="大樂透多因子量化選號",
    page_icon="🎰",
    layout="wide",
)

st.title("🎰 大樂透多因子量化選號系統")
st.caption(
    "純隨機獨立事件 · EV<0 · 本工具不預測號碼，"
    "僅以「壓縮包牌成本 + 過濾劣質組合」優化資金運用。"
)


# --- Inputs -------------------------------------------------------------------


def _parse_csv_numbers(text: str) -> list[int]:
    return [int(x.strip()) for x in text.split(",") if x.strip()]


with st.sidebar:
    st.header("📥 輸入參數")

    prev_text = st.text_input(
        "上期開獎號碼（6 個，逗號分隔）",
        value="5, 12, 18, 25, 33, 42",
        help="僅用於 Phase 1 母體縮水；不引入歷史資料庫。",
    )

    tails = st.multiselect(
        "排除尾數 (0-9)",
        options=list(range(10)),
        default=[],
        help="例：選 7 → 排除 7、17、27、37、47。",
    )

    keys = st.multiselect(
        "膽碼 (1-5 顆)",
        options=list(range(POOL_MIN, POOL_MAX + 1)),
        default=[7, 17, 27],
        help="膽碼具絕對優先權，必出現於每注。",
    )

    drag_mode = st.radio(
        "拖碼模式",
        options=["自動（Phase 1 池）", "手動指定"],
        horizontal=True,
    )
    drag_nums: list[int] | None = None
    if drag_mode == "手動指定":
        drag_nums = st.multiselect(
            "拖碼候選池",
            options=list(range(POOL_MIN, POOL_MAX + 1)),
            default=[],
            help="會與 Phase 1 母體做交集；膽碼自動排除。",
        )

    num_tickets = st.slider("產出注數", 1, 50, 5)

    seed = st.number_input(
        "隨機種子（0 = 不固定）", min_value=0, max_value=10_000_000, value=0, step=1
    )

    go = st.button("🎯 產生選號", type="primary", use_container_width=True)


# --- Sidebar protocol summary -------------------------------------------------

with st.sidebar.expander("📐 過濾濾網規則"):
    st.markdown(
        f"""
- **和值濾網**：`{SUM_MIN} ≤ sum ≤ {SUM_MAX}`
- **奇偶濾網**：`奇數 ∈ {sorted(ALLOWED_ODD_COUNTS)}`
- **防分紅濾網**：`號碼 > {BIG_THRESHOLD} 至少 {MIN_BIG_COUNT} 個`
"""
    )


# --- Main panel ---------------------------------------------------------------

if not go:
    st.info("← 從左側設定參數後，按下『產生選號』。")
    st.stop()

try:
    prev_draw = _parse_csv_numbers(prev_text)
except ValueError:
    st.error("上期開獎格式錯誤：請輸入 6 個以逗號分隔的整數。")
    st.stop()

rng = random.Random(seed) if seed else None

try:
    tickets = generate_tickets(
        previous_draw=prev_draw,
        exclude_tails=tails,
        key_nums=keys,
        drag_nums=drag_nums,
        num_tickets=num_tickets,
        rng=rng,
    )
except ValueError as exc:
    st.error(f"參數錯誤：{exc}")
    st.stop()

if not tickets:
    st.warning(
        "通過 4 階段過濾的組合為 0。"
        "請放寬尾數排除、調整膽碼或擴大拖碼池後再試。"
    )
    st.stop()

st.success(f"✅ 已產出 {len(tickets)} 注合格組合（目標 {num_tickets} 注）")

col_left, col_right = st.columns([3, 2])

with col_left:
    st.subheader("🎟️ 推薦組合")
    for idx, ticket in enumerate(tickets, start=1):
        nums_str = "   ".join(f"`{n:02d}`" for n in ticket)
        st.markdown(f"**第 {idx} 注**：{nums_str}")

with col_right:
    st.subheader("📊 每注診斷")
    header = "| # | sum | odd | even | big | small |\n|---|---|---|---|---|---|\n"
    rows = []
    for idx, ticket in enumerate(tickets, start=1):
        s = ticket_stats(ticket)
        rows.append(
            f"| {idx} | {s['sum']} | {s['odd_count']} | {s['even_count']} "
            f"| {s['big_count']} | {s['small_count']} |"
        )
    st.markdown(header + "\n".join(rows))

st.caption(
    "提醒：本工具僅為數學優化器，無法改變獨立隨機事件之期望值；理性投注。"
)
