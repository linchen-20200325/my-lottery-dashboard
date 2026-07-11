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


# --- 回測面板(v6.25;兩 view 共用,SSOT)--------------------------------------


@st.cache_data(ttl=3600, show_spinner="🔮 回測中…")
def run_backtest_cached(
    csv_str: str,
    lottery: str,
    num_tickets: int,
    max_periods: int,
    lookback: int,
    batch_disjoint: bool,
    howard_mode: bool,
    hot_sigma: float,
    cold_sigma: float,
    sma_window: int,
    range_pad: int,
    overheat_recent: int,
    overheat_min: int,
    dormant_periods: int,
    seed: int,
    apply_manual: bool = False,
    manual_keys: tuple | None = None,
    manual_excluded_tails: tuple | None = None,
    manual_excluded_numbers: tuple | None = None,
) -> dict:
    """兩 view 共用的 cached 回測執行(SSOT)。

    以 `lottery`(str)當快取 key 解析 `dom`;scalar/tuple 參數 → 可 cache;lazy
    import `backtest` 避免 streamlit_app 載入時拉進離線分析層。
    `apply_manual=False` → 乾淨策略回測(僅動態訊號);`apply_manual=True` → 手動
    膽碼 / 排除尾數 / 排除特定號碼 也套進每一期(§7 使用者可選)。
    """
    from pathlib import Path as _Path

    from src.analytics.backtest import backtest
    from src.generator.domain import LOTTO649, POWERBALL

    dom = LOTTO649 if lottery == "lotto649" else POWERBALL
    signal_params = {
        "hot_sigma_factor": hot_sigma, "cold_sigma_factor": cold_sigma,
        "sum_sma_window": sma_window, "sum_range_pad": range_pad,
        "overheat_recent_periods": overheat_recent,
        "overheat_min_count": overheat_min, "dormant_periods": dormant_periods,
    }

    def _manual(v):
        return list(v) if (apply_manual and v) else None

    return backtest(
        _Path(csv_str), tickets_per_draw=num_tickets, lookback=lookback,
        seed=seed, dom=dom, batch_disjoint=batch_disjoint,
        howard_mode=howard_mode, max_periods=max_periods,
        signal_params=signal_params,
        manual_keys=_manual(manual_keys),
        manual_excluded_tails=_manual(manual_excluded_tails),
        manual_excluded_numbers=_manual(manual_excluded_numbers),
    )


def backtest_panel(*, key_prefix: str, show_howard: bool, run) -> None:
    """渲染「🔮 回測」控制項 + 結果。

    `run(controls: dict) -> result dict`:呼叫端(view)綁定的 cached 回測函式,
    controls = {num_tickets, max_periods, lookback, batch_disjoint, howard_mode, seed}。
    `show_howard`:是否顯示霍華德嚴格 toggle(僅大樂透)。
    """
    st.caption(
        "**每一期都重新選號(不是固定一組)**:回到每次開獎前,只用當時可得的歷史"
        "(往前 lookback 期)算訊號、用你**當前的訊號參數**重新選出號碼,再跟該期"
        "**實際開獎**對獎;一路做 N 期 = 選了 N 次號。預設**不套手動膽碼/排除**"
        "(乾淨策略回測),可勾下方「套用手動」把你目前畫面的手動設定也套進每一期。"
        "EV<0 為樂透數學本質,回測僅審視策略行為、非預測。"
    )
    if hasattr(st, "pills"):
        _n = st.pills(
            "每期幾組(注數)", options=[1, 3, 5, 10, 15, 20],
            selection_mode="single", default=10, key=f"{key_prefix}_bt_num",
        )
        num_tickets = int(_n) if _n else 10
    else:
        num_tickets = st.slider(
            "每期幾組(注數)", 1, 20, 10, key=f"{key_prefix}_bt_num_s",
        )
    max_periods = st.slider(
        "回測期數(最近 N 期)", 5, 100, 30, key=f"{key_prefix}_bt_periods",
        help="回測最近 N 期開獎。越多越慢(每期重跑選號)。",
    )
    lookback = st.slider(
        "每期參考歷史(lookback)", 10, 50, 30, key=f"{key_prefix}_bt_lookback",
        help="每一期選號時,往前看幾期歷史算訊號。",
    )
    batch_disjoint = st.checkbox(
        "號碼完全不重複(組間 6 號互斥)", value=False,
        key=f"{key_prefix}_bt_disjoint",
    )
    howard_mode = False
    if show_howard:
        howard_mode = st.checkbox(
            "🎯 霍華德嚴格模式", value=False, key=f"{key_prefix}_bt_howard",
            help="霍華德黃金 8 條硬綁 + 軟分;史料不足的期會自動跳過。",
        )
    apply_manual = st.checkbox(
        "套用目前的手動膽碼 / 排除(否則乾淨策略回測)", value=False,
        key=f"{key_prefix}_bt_apply_manual",
        help="勾 = 把你上方設的手動膽碼 / 手動排除尾數 / 排除特定號碼也套到回測每一期"
             "(完全照現在畫面跑)。不勾 = 只用動態訊號,不受一次性人工選擇影響。",
    )
    seed = int(st.number_input(
        "隨機種子(同 seed 同結果)", min_value=0, value=2026, step=1,
        key=f"{key_prefix}_bt_seed",
        help="選號有隨機性(從候選號池洗牌抽組)。固定同一個 seed → 每次跑結果完全"
             "一樣,方便『只改一個選項』做公平比較;換一個 seed = 重擲一次骰子,多換"
             "幾個 seed 若結論都差不多,代表策略不是靠運氣。不影響策略本身,只固定隨機。",
    ))

    if not st.button(
        "▶ 執行回測", key=f"{key_prefix}_bt_run", use_container_width=True,
    ):
        st.caption("設定好後按「▶ 執行回測」。")
        return

    controls = dict(
        num_tickets=num_tickets, max_periods=max_periods, lookback=lookback,
        batch_disjoint=batch_disjoint, howard_mode=howard_mode, seed=seed,
        apply_manual=apply_manual,
    )
    try:
        result = run(controls)
    except ValueError as exc:
        st.error(f"❌ 回測失敗:{exc}")
        return
    if result["draws_evaluated"] == 0:
        st.warning("⚠️ 沒有可評估的期數(可能史料不足或濾網篩光)。請放寬設定或減少 lookback。")
        return
    _render_backtest_result(result)


def _render_backtest_result(result: dict) -> None:
    evaluated = result["draws_evaluated"]
    requested = result["periods_requested"]
    tickets = result["tickets_generated"]

    cols = st.columns(3)
    cols[0].metric("已回測期數", f"{evaluated} / {requested}")
    cols[1].metric("產生注數", f"{tickets:,}")
    if result["payout_twd"] is not None:
        cols[2].metric("名目 ROI", f"{result['roi_percent']:.1f}%")

    # 範例:秀最新一期「當時實際選出的注」→ 眼見每期都是重新選號、不是固定一組
    sample = result.get("sample")
    if sample:
        st.markdown(
            f"**範例 — 最新一期({sample['date'] or '最近期'})當時實際選出的注**"
            "(每期都像這樣重新選,不是固定同一組):"
        )
        st.caption(
            "該期實際開獎:`"
            + " ".join(f"{n:02d}" for n in sample["target"]) + "`"
        )
        for t, h in zip(sample["tickets"], sample["hits"]):
            nums = " ".join(f"{n:02d}" for n in t)
            st.markdown(f"- `{nums}` — 命中 **{h}** 顆")

    ddist = result["draws_hit_distribution"]
    hit3 = sum(v for k, v in ddist.items() if k >= 3)
    st.markdown(f"**每期最佳一注命中(共 {evaluated} 期):**")
    if ddist:
        st.markdown(
            " ｜ ".join(
                f"命中 {k} 顆:**{v}** 期"
                for k, v in sorted(ddist.items(), reverse=True)
            )
        )
    st.caption(
        f"至少命中 3 顆的期數:**{hit3} / {evaluated}** "
        f"({hit3 / evaluated * 100:.1f}%)。"
    )

    hdist = result["hit_distribution"]
    st.markdown(f"**每注命中分佈(共 {tickets:,} 注):**")
    st.markdown(" ｜ ".join(f"{k} 顆:{v:,}" for k, v in sorted(hdist.items())))

    if result["payout_twd"] is not None:
        st.caption(
            f"名目成本 NT$ {result['cost_twd']:,} · 名目回收 NT$ {result['payout_twd']:,}"
            "(頭獎以名目上限估算,非分潤後實際;EV<0 為大樂透數學本質)。"
        )
    else:
        st.caption("威力彩無 honest 名目獎金表 → 不估 ROI(§1 不捏造),只看命中分佈。")
