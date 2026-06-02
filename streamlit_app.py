"""Streamlit Cloud entry — 樂透量化訊號儀表板 v6.0（雙 tab：大樂透 + 威力彩）.

各 tab 自帶 widget 與快取，使用 widget key 前綴 (`l649_` / `pb_`) 隔離 session_state
命名空間，避免兩款參數互踩。Sidebar 完全棄用，所有參數移至各 tab 內的 `st.expander`。
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.ui.lotto649_view import render as render_lotto649
from src.ui.powerball_view import render as render_powerball

LOTTO649_CSV = Path(__file__).parent / "data" / "lotto649.csv"
POWERBALL_CSV = Path(__file__).parent / "data" / "powerball.csv"

st.set_page_config(
    page_title="樂透量化訊號儀表板 v6.0",
    page_icon="🎲",
    layout="wide",
)

st.title("🎲 樂透量化訊號儀表板 v6.0")
st.caption(
    "大樂透 6/49 · 威力彩 6/38 + 1/8 · Z-Score 動態冷熱 + SMA 動態和值 · 容錯架構 (Graceful Degradation)。"
    "EV<0 為樂透數學本質；本工具僅優化資金運用。"
)

tab_lotto, tab_power = st.tabs(["🎰 大樂透 6/49", "⚡ 威力彩 6/38 + 1/8"])
with tab_lotto:
    render_lotto649(LOTTO649_CSV)
with tab_power:
    render_powerball(POWERBALL_CSV)
