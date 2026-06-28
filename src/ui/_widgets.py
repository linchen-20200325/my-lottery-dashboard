"""Shared Streamlit widget sections (v6.24 T2-render — SSOT for設定階梯).

抽出兩 view `render()` 中**無狀態、byte-identical(或僅 data 參數不同)**的設定
widget 區段,消 S2 重複 + 縮短 render() 上帝函式(C1)。每個 helper:
  - 以 `key_prefix` 參數化 widget key(`l649` / `pb`)→ session_state key 與原本
    **完全相同**,不破壞既有使用者狀態
  - 吃 `defaults`(各 view 的 `DEFAULTS`,來源 domain SSOT)取預設值
  - 回傳純值,無 session_state callback(故低風險)

**刻意不收**有狀態 / 分歧大的區段(資料來源 + session_state、膽碼/排除 reset/clear
callback、結果表 Howard/wheel/bonus)—— 那些需 Streamlit 手測,留各 view。

本模組 import streamlit(故不被任何 test import;由各 view 在 runtime 載入,
stub-import 驗證模組頂層)。
"""

from __future__ import annotations

import streamlit as st


def zscore_sliders(key_prefix: str, defaults: dict) -> tuple[float, float]:
    """第一區 Z-Score 冷熱閾值雙滑桿(header 由 caller 渲染,因兩 view 標題不同)。"""
    hot_sigma = st.slider(
        "熱碼倍率 (μ − Nσ)", 0.0, 1.5, defaults["hot_sigma_factor"],
        step=0.1, key=f"{key_prefix}_hot",
    )
    cold_sigma = st.slider(
        "冷碼倍率 (μ + Nσ)", 0.5, 3.0, defaults["cold_sigma_factor"],
        step=0.1, key=f"{key_prefix}_cold",
    )
    return hot_sigma, cold_sigma


def sma_section(
    key_prefix: str,
    defaults: dict,
    pad_pills_options: list[int],
    pad_slider_max: int,
) -> tuple[int, int]:
    """動態和值 SMA 區段。pad 的選項 / 滑桿上界依樂透不同(大樂透 ±60、威力彩 ±50)。"""
    st.markdown("#### 📈 動態和值 (SMA)")
    if hasattr(st, "pills"):
        _sma_choice = st.pills(
            "SMA 視窗 (期數)",
            options=[5, 10, 15, 20, 25, 30],
            selection_mode="single",
            default=defaults["sum_sma_window"],
            key=f"{key_prefix}_sma_pills",
        )
        sma_window = int(_sma_choice) if _sma_choice else defaults["sum_sma_window"]
        _pad_choice = st.pills(
            "和值 ±pad",
            options=pad_pills_options,
            selection_mode="single",
            default=defaults["sum_range_pad"],
            key=f"{key_prefix}_pad_pills",
        )
        range_pad = int(_pad_choice) if _pad_choice else defaults["sum_range_pad"]
    else:
        sma_window = st.slider(
            "SMA 視窗 (期數)", 5, 30, defaults["sum_sma_window"],
            key=f"{key_prefix}_sma",
        )
        range_pad = st.slider(
            "和值 ±pad", 10, pad_slider_max, defaults["sum_range_pad"],
            key=f"{key_prefix}_pad",
        )
    return sma_window, range_pad


def tail_signal_sliders(key_prefix: str, defaults: dict) -> tuple[int, int, int]:
    """尾數訊號 3 滑桿(過熱觀察期 / 過熱判定次數 / 死寂判定期)— 兩 view 完全相同。"""
    st.markdown("#### 🎚️ 尾數訊號")
    st.caption(
        "↗ **拉高 = 自動排除少**(條件變嚴格,較少尾數被列為過熱/死寂) ｜ "
        "↘ **拉低 = 自動排除多**(條件變寬鬆,更多尾數被列入排除)"
    )
    if hasattr(st, "pills"):
        _oh_r_choice = st.pills(
            "過熱觀察期",
            options=[1, 2, 3, 4, 5, 6, 7, 8, 10],
            selection_mode="single",
            default=defaults["overheat_recent_periods"],
            key=f"{key_prefix}_oh_r_pills",
            help="觀察近 N 期的尾數出現次數。N 越小 → 越快反應近期熱點 → 越容易判過熱。",
        )
        overheat_recent = int(_oh_r_choice) if _oh_r_choice else defaults["overheat_recent_periods"]
        _oh_m_choice = st.pills(
            "過熱判定次數",
            options=[1, 2, 3, 4, 5, 6, 7, 8, 10],
            selection_mode="single",
            default=defaults["overheat_min_count"],
            key=f"{key_prefix}_oh_m_pills",
            help="觀察期內出現 ≥ N 次即判為過熱。**N 拉到 4-6 = 排除少**,N=2-3 = 排除多。",
        )
        overheat_min = int(_oh_m_choice) if _oh_m_choice else defaults["overheat_min_count"]
        _dorm_choice = st.pills(
            "死寂判定期",
            options=[5, 8, 10, 12, 15, 20, 25, 30],
            selection_mode="single",
            default=defaults["dormant_periods"],
            key=f"{key_prefix}_dorm_pills",
            help="連續 N 期未出現即判為死寂。**N 拉到 12-20 = 排除少**,N=5-8 = 排除多。",
        )
        dormant_periods = int(_dorm_choice) if _dorm_choice else defaults["dormant_periods"]
    else:
        overheat_recent = st.slider(
            "過熱觀察期", 1, 10, defaults["overheat_recent_periods"],
            key=f"{key_prefix}_oh_r",
            help="觀察近 N 期的尾數出現次數。N 越小 → 越快反應近期熱點 → 越容易判過熱。",
        )
        overheat_min = st.slider(
            "過熱判定次數", 1, 10, defaults["overheat_min_count"],
            key=f"{key_prefix}_oh_m",
            help="觀察期內出現 ≥ N 次即判為過熱。**N 拉到 4-6 = 排除少**,N=2-3 = 排除多。",
        )
        dormant_periods = st.slider(
            "死寂判定期", 5, 30, defaults["dormant_periods"],
            key=f"{key_prefix}_dorm",
            help="連續 N 期未出現即判為死寂。**N 拉到 12-20 = 排除少**,N=5-8 = 排除多。",
        )
    return overheat_recent, overheat_min, dormant_periods
