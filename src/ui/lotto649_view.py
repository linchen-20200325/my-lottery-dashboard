"""大樂透 tab UI — 沿用 v5.1.2 邏輯、widget key 加 `l649_` 前綴隔離 tab 命名空間。"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.ui._view_base import (
    analysis_rng,
    expand_tails_to_numbers as _expand_tails_to_numbers,
    freshness_warning,
    upload_provenance,
)
from src.ui._widgets import sma_section, tail_signal_sliders, zscore_sliders
from src.analytics.cost_calc import UNIT_PRICE_TWD, summary as cost_summary
from src.data.freshness import LOTTO649_DRAW_WEEKDAYS
from src.data.loader import (
    HistoryLoadError,
    load_csv_file_with_provenance,
    load_csv_string_with_provenance,
    load_json_string,
    preview_recent,
)
from src.data.provenance import (
    HistoryProvenance,
    format_provenance_caption,
)
from src.generator.history_engine import (
    DEFAULTS,
    POOL_MAX,
    POOL_MIN,
    STATIC_FALLBACK_ANALYSIS,
    HistoryAnalysis,
    analyze,
)
from src.generator.abbreviated_wheel import (
    WHEEL_GUARANTEE_P,
    WHEEL_GUARANTEE_T,
    WHEEL_SIZE,
    WHEEL_TICKET_COUNT,
    pick_abbreviated_wheel,
)
from src.generator.lotto_picker import (
    ALLOWED_ODD_COUNTS,
    BIG_THRESHOLD,
    HOWARD_ALLOWED_SMALL_COUNTS,
    HOWARD_EXACT_CONSEC_PAIRS,
    HOWARD_EXACT_TAIL_PAIRS,
    HOWARD_GAP5_ALLOWED_COUNTS,
    HOWARD_GAP5_THRESHOLD,
    HOWARD_MAX_EMPTY_DECADES,
    HOWARD_MIN_HISTORY,
    HOWARD_REPEAT_FROM_LAST,
    HOWARD_SMALL_THRESHOLD,
    HOWARD_SOFT_MIN_SCORE,
    HOWARD_SUM_MAX,
    HOWARD_SUM_MIN,
    MAX_BASEMENT_PER_TICKET,
    MAX_CONSECUTIVE_PAIRS,
    MAX_PRIME_COUNT,
    MIN_BIG_COUNT,
    MIN_EMPTY_DECADES,
    MIN_PRIME_COUNT,
    SUM_MAX,
    SUM_MIN,
    generate_tickets,
    ticket_stats,
)


# --- Cached helpers (path-as-string for cache key stability) ------------------


@st.cache_data(ttl=3600, show_spinner=False)
def _load_bundled(path_str: str) -> tuple[list[list[int]], HistoryProvenance]:
    return load_csv_file_with_provenance(Path(path_str))


@st.cache_data(ttl=600, show_spinner=False)
def _freshness_warning(path_str: str) -> str | None:
    """憲法 §2.4:返回 stale 警告字串或 None;cache 10 分鐘避免每 rerun 重讀。"""
    return freshness_warning(path_str, LOTTO649_DRAW_WEEKDAYS)


@st.cache_data(ttl=3600, show_spinner=False)
def _load_upload(payload: bytes, name: str) -> tuple[list[list[int]], HistoryProvenance]:
    text = payload.decode("utf-8", errors="replace")
    source = f"<upload:{name}>"
    if name.lower().endswith(".json"):
        # JSON 路徑不帶 draw_date,provenance.as_of 為 None
        draws = load_json_string(text)
        return draws, upload_provenance(source, len(draws))
    return load_csv_string_with_provenance(text, source=source)


@st.cache_data(ttl=3600, show_spinner=False)
def _preview_bundled(path_str: str, limit: int) -> list[dict]:
    return preview_recent(Path(path_str), limit=limit)


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
    rng = analysis_rng(seed)
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


# --- Widget callbacks ---------------------------------------------------------
# v6.18.1: Streamlit 禁止在 widget 渲染後內聯寫其 session_state key (StreamlitAPIException)。
# 改用 on_click callback:在下一輪 rerun 啟動時、widget 渲染前執行,寫入合法。
# Reset:清掉 sentinel 讓 seed 區塊在新 rerun 重新填入當期 _sys_recommended;
# Clear:直接寫空 list,並把 sentinel 鎖成 True 防止再被覆寫。


def _reset_l649_excl_callback() -> None:
    st.session_state.pop("l649_excl_seeded", None)


def _clear_l649_excl_callback() -> None:
    st.session_state["l649_excl_pills"] = []
    st.session_state["l649_excl_multi"] = []
    st.session_state["l649_excl_seeded"] = True


# --- Render entry --------------------------------------------------------------


def render(sample_csv_path: Path) -> None:
    """渲染大樂透 tab。父 entry 已呼叫 `st.set_page_config` / `st.title`。"""

    # --- Settings expander (was sidebar) -------------------------------------
    with st.expander("⚙️ 大樂透 — 參數設定", expanded=True):
        st.markdown("#### 📥 歷史資料")
        source = st.radio(
            "資料來源",
            options=["倉庫內附 (data/lotto649.csv)", "上傳 CSV / JSON", "貼上文字"],
            index=0,
            help="Streamlit Cloud 不發外部 API。失敗時 UI 會自動降級至靜態安全模式。",
            key="l649_source",
        )
        uploaded_file = None
        pasted = ""
        if source == "上傳 CSV / JSON":
            uploaded_file = st.file_uploader(
                "上傳檔案", type=["csv", "json"], key="l649_uploader",
            )
        elif source == "貼上文字":
            pasted = st.text_area(
                "貼上 CSV 或 JSON", height=160, key="l649_paste",
            )

        if hasattr(st, "pills"):
            _preview_choice = st.pills(
                "📋 預覽近 N 期",
                options=[1, 3, 5, 10, 15, 20],
                selection_mode="single",
                default=5,
                key="l649_preview_pills",
                help="主面板頂部會顯示最近 N 期開獎,用來驗證資料是否正確下載/上傳。",
            )
            preview_limit = int(_preview_choice) if _preview_choice else 5
        else:
            preview_limit = st.slider(
                "📋 預覽近 N 期", 1, 20, 5,
                help="主面板頂部會顯示最近 N 期開獎,用來驗證資料是否正確下載/上傳。",
                key="l649_preview",
            )

        st.markdown("**🤖 自動更新歷史資料**")
        st.link_button(
            "🚀 觸發 GitHub Actions 抓檔 (大樂透)",
            url="https://github.com/LinChen-20200325/my-lottery-dashboard/actions/workflows/update-history.yml",
            use_container_width=True,
        )
        st.caption(
            "排程：每週二、五 22:23/22:53/23:23/00:23 GMT+8（4 槽容錯）。"
            "手動：右上 **Run workflow** → `main` → **Run workflow**。"
        )

        st.markdown("#### 🌡️ Z-Score 冷熱閾值")
        hot_sigma, cold_sigma = zscore_sliders("l649", DEFAULTS)

        sma_window, range_pad = sma_section(
            "l649", DEFAULTS,
            pad_pills_options=[10, 20, 30, 40, 50, 60], pad_slider_max=60,
        )

        overheat_recent, overheat_min, dormant_periods = tail_signal_sliders(
            "l649", DEFAULTS,
        )

        st.markdown("#### 🎯 膽碼 / 排除 (覆寫)")
        key_mode = st.radio(
            "雙膽", ["動態", "手動"], horizontal=True, key="l649_keymode",
        )
        manual_keys: list[int] | None = None
        if key_mode == "手動":
            st.caption("點擊號碼 1-49 即可加入/移除手動膽碼清單(1-5 顆)。")
            if hasattr(st, "pills"):
                manual_keys = st.pills(
                    "手動膽碼 (1-5 顆)",
                    options=list(range(POOL_MIN, POOL_MAX + 1)),
                    selection_mode="multi",
                    default=[7, 33],
                    format_func=lambda n: f"{n:02d}",
                    label_visibility="collapsed",
                    key="l649_keys_pills",
                )
            else:
                manual_keys = st.multiselect(
                    "手動膽碼 (1-5 顆)",
                    options=list(range(POOL_MIN, POOL_MAX + 1)),
                    default=[7, 33],
                    key="l649_keys",
                )
            manual_keys = list(manual_keys) if manual_keys else []

        tail_mode = st.radio(
            "排除尾數", ["動態", "手動"], horizontal=True, key="l649_tailmode",
        )
        manual_excluded_tails: list[int] | None = None
        if tail_mode == "手動":
            st.caption("點擊尾數 0-9 即可加入/移除排除清單;空 = 不排除任何尾數。")
            if hasattr(st, "pills"):
                manual_excluded_tails = st.pills(
                    "手動排除尾數",
                    options=list(range(10)),
                    selection_mode="multi",
                    default=[],
                    label_visibility="collapsed",
                    key="l649_extails_pills",
                )
            else:
                manual_excluded_tails = st.multiselect(
                    "手動排除尾數(升級 streamlit≥1.39 可享按鈕點選 UI)",
                    options=list(range(10)),
                    default=[],
                    key="l649_extails",
                )
            manual_excluded_tails = list(manual_excluded_tails) if manual_excluded_tails else []

        # --- v6.18: 早期載入 history + analyze → seed「排除特定號碼」動態建議 ---
        _early_history: list[list[int]] = []
        _early_load_failed = False
        try:
            if source == "上傳 CSV / JSON" and uploaded_file is not None:
                _early_history, _ = _load_upload(
                    uploaded_file.getvalue(), uploaded_file.name,
                )
            elif source == "貼上文字" and pasted.strip():
                if pasted.lstrip().startswith(("[", "{")):
                    _early_history = load_json_string(pasted)
                else:
                    _early_history, _ = load_csv_string_with_provenance(
                        pasted, source="<paste:csv>",
                    )
            elif source == "倉庫內附 (data/lotto649.csv)":
                _early_history, _ = _load_bundled(str(sample_csv_path))
        except (HistoryLoadError, OSError):
            _early_load_failed = True

        _early_analysis = STATIC_FALLBACK_ANALYSIS
        if _early_history and not _early_load_failed:
            try:
                _early_analysis = cached_analysis(
                    _early_history,
                    hot_sigma, cold_sigma,
                    sma_window, range_pad,
                    overheat_recent, overheat_min, dormant_periods,
                    0,
                )
            except Exception:  # noqa: BLE001 — seed 用,失敗就 fallback
                pass

        _effective_excluded_tails_for_seed = (
            set(manual_excluded_tails)
            if manual_excluded_tails is not None
            else set(_early_analysis.exclude_tails)
        )
        _tail_expanded_for_seed = _expand_tails_to_numbers(
            _effective_excluded_tails_for_seed, POOL_MIN, POOL_MAX,
        )
        _key_set = set(manual_keys) if manual_keys else set()
        _sys_recommended = sorted(
            (set(_early_analysis.cold) | set(_tail_expanded_for_seed)) - _key_set
        )

        if (
            not _early_analysis.is_fallback
            and not st.session_state.get("l649_excl_seeded", False)
        ):
            st.session_state["l649_excl_pills"] = list(_sys_recommended)
            st.session_state["l649_excl_multi"] = list(_sys_recommended)
            st.session_state["l649_excl_seeded"] = True

        st.markdown("##### 🚫 排除特定號碼")
        if _sys_recommended:
            st.caption(
                f"💡 進場已自動填入系統建議 **{len(_sys_recommended)}** 顆"
                f"(冷號 {len(_early_analysis.cold)} + 過熱尾數展開 "
                f"{len(_tail_expanded_for_seed)}),點擊可加減。"
            )
        else:
            st.caption("點擊號碼即可加入/移除排除清單;空 = 不排除任何號碼。")
        _excl_options = [n for n in range(POOL_MIN, POOL_MAX + 1) if n not in _key_set]
        if _key_set:
            st.caption(
                f"(已自動隱藏手動膽碼 {sorted(_key_set)},避免與排除清單衝突)"
            )
        if hasattr(st, "pills"):
            manual_excluded_numbers = st.pills(
                "點擊號碼",
                options=_excl_options,
                selection_mode="multi",
                format_func=lambda n: f"{n:02d}",
                label_visibility="collapsed",
                key="l649_excl_pills",
            )
        else:
            manual_excluded_numbers = st.multiselect(
                "排除號碼(升級 streamlit≥1.39 可享按鈕點選 UI)",
                options=_excl_options,
                format_func=lambda n: f"{n:02d}",
                key="l649_excl_multi",
            )
        if manual_excluded_numbers:
            st.caption(
                f"已排除 **{len(manual_excluded_numbers)}** 顆:"
                + ", ".join(f"{n:02d}" for n in sorted(manual_excluded_numbers))
            )

        _btn_col1, _btn_col2 = st.columns(2)
        _btn_col1.button(
            "🔄 重設為系統建議",
            key="l649_reset_excl",
            use_container_width=True,
            help=f"重設為系統建議的 {len(_sys_recommended)} 顆排除清單",
            on_click=_reset_l649_excl_callback,
        )
        _btn_col2.button(
            "🧹 全清空",
            key="l649_clear_excl",
            use_container_width=True,
            help="清空排除特定號碼清單",
            on_click=_clear_l649_excl_callback,
        )

        sum_mode = st.radio(
            "和值區間", ["動態 SMA", "手動"], horizontal=True, key="l649_summode",
        )
        manual_sum_range: tuple[int, int] | None = None
        if sum_mode == "手動":
            s_lo, s_hi = st.slider(
                "手動和值區間", 90, 210, (SUM_MIN, SUM_MAX), key="l649_sumrange",
            )
            manual_sum_range = (s_lo, s_hi)

        st.markdown("#### ⚙️ 產出")
        if hasattr(st, "pills"):
            _num_choice = st.pills(
                "注數",
                options=[1, 5, 10, 15, 20, 30, 50],
                selection_mode="single",
                default=5,
                key="l649_num_pills",
            )
            num_tickets = int(_num_choice) if _num_choice else 5
        else:
            num_tickets = st.slider("注數", 1, 50, 5, key="l649_num")

        batch_disjoint = st.checkbox(
            "🧩 批次推薦：注間號碼完全不重複",
            value=False,
            help=(
                "開啟後，各注 6 顆號碼完全不重合（會停用膽碼），"
                "可大幅提高批次覆蓋率。"
            ),
            key="l649_batch_disjoint",
        )

        howard_mode_ui = st.checkbox(
            "🎯 霍華德嚴格模式（黃金 8 條）",
            value=False,
            help=(
                "Gail Howard《Lottery Master Guide》八大條件。"
                "需 ≥ "
                f"{HOWARD_MIN_HISTORY} 期動態歷史；Round 2 fallback 自動退回 v6.16。"
            ),
            key="l649_howard_mode",
        )

        seed = st.number_input(
            "隨機種子（0 = 不固定）", min_value=0, max_value=10_000_000,
            value=0, step=1, key="l649_seed",
        )
        go = st.button(
            "🎲 產生大樂透選號", type="primary", use_container_width=True,
            key="l649_go",
        )

    with st.expander("📐 大樂透 七大濾網規則(v6.16 加入 Howard #4 + #11)"):
        st.markdown(
            f"""
- **質數**：`{MIN_PRIME_COUNT} ≤ 質數 ≤ {MAX_PRIME_COUNT}`(質數集 {{2,3,5,7,11,13,17,19,23,29,31,37,41,43,47}})
- **連號**:`連號對數 ≤ {MAX_CONSECUTIVE_PAIRS}`
- **動態和值**:`Phase 1 計算區間` (失敗回 `{SUM_MIN}-{SUM_MAX}`)
- **奇偶**:`奇數 ∈ {sorted(ALLOWED_ODD_COUNTS)}`
- **大數**:`> {BIG_THRESHOLD} 至少 {MIN_BIG_COUNT} 個`
- **字頭追蹤**(Howard #4):`至少 {MIN_EMPTY_DECADES} 個字頭區間完全空`(實測 577 期歷史命中 87.0%)
- **谷底陷阱**(Howard #11):`極冷號(engine cold list) ≤ {MAX_BASEMENT_PER_TICKET} 顆`(實測命中 85.8%)
"""
        )

    with st.expander("🎯 霍華德黃金 8 條(v6.19 opt-in)"):
        st.markdown(
            f"""
**Source**: Gail Howard《Lottery Master Guide》& 《Lotto Wheel Five to Win》

**硬綁(3 條全過)**
1. **總和**:`sum ∈ [{HOWARD_SUM_MIN}, {HOWARD_SUM_MAX}]`(SMA±30 clamp 在此區間)
2. **奇偶**:`奇數 ∈ {sorted(ALLOWED_ODD_COUNTS)}`(沿用 v6.16)
3. **大小**:`小數(≤ {HOWARD_SMALL_THRESHOLD}) ∈ {sorted(HOWARD_ALLOWED_SMALL_COUNTS)}`(切分 24/25,雙向)

**軟分(≥ {HOWARD_SOFT_MIN_SCORE}/5 通過,史料不足條目自動 +1)**
4. **同尾恰 1 對**:有且僅有 1 個尾數出現 2 次,其餘唯一(`{HOWARD_EXACT_TAIL_PAIRS}`)
5. **字頭空缺**:`空字頭數 ∈ [{MIN_EMPTY_DECADES}, {HOWARD_MAX_EMPTY_DECADES}]`
6. **連號恰 1 對**:`連號對數 == {HOWARD_EXACT_CONSEC_PAIRS}`
7. **遺漏黃金區**:`gap ≤ {HOWARD_GAP5_THRESHOLD} 的顆數 ∈ {sorted(HOWARD_GAP5_ALLOWED_COUNTS)}`
8. **連莊號**:`與上期(draws[0])共 {HOWARD_REPEAT_FROM_LAST} 顆`

**降級**:史料 < {HOWARD_MIN_HISTORY} 期 或 `is_fallback=True` → 自動退回 v6.16 + warning。
"""
        )

    with st.expander("🎯 精簡包牌(Abbreviated Wheel, 4保3)— v6.20"):
        st.markdown(
            f"""
**保證**:你抓 **{WHEEL_SIZE}** 個號(自選),若 6 個中獎號中**有 {WHEEL_GUARANTEE_T} 個落在你抓的 {WHEEL_SIZE} 個內**,則 **{WHEEL_TICKET_COUNT} 注**中**至少 1 注命中 {WHEEL_GUARANTEE_P} 個**(數學保證,非統計推估)。

**注數**:{WHEEL_TICKET_COUNT} 注 × NT$ {UNIT_PRICE_TWD} = **NT$ {WHEEL_TICKET_COUNT * UNIT_PRICE_TWD}**

**Source**:greedy set-cover on (12, 6, 4; 3) lotto design — `src/generator/abbreviated_wheel.py:WHEEL_12_4_OF_4_3`;`tests/test_abbreviated_wheel.py` 暴搜驗證 495 個 4-subset 全覆蓋。

⚠️ **與智能選號不同**:這裡不過 v6.16 / Howard 濾網 — 濾網會破壞 covering 數學保證,**故意不混用**。
"""
        )
        wheel_pool = st.multiselect(
            f"選 {WHEEL_SIZE} 個號碼",
            options=list(range(POOL_MIN, POOL_MAX + 1)),
            default=[],
            max_selections=WHEEL_SIZE,
            help=f"恰好選 {WHEEL_SIZE} 個 ∈ [{POOL_MIN}, {POOL_MAX}] 的整數,不重複。",
            key="l649_wheel_pool",
        )
        wheel_seed_str = st.text_input(
            "隨機種子(空白=固定排序)",
            value="",
            help="同 seed 同輸出;留空走 sorted-pool 確定性映射。",
            key="l649_wheel_seed",
        )
        wheel_go = st.button(
            f"🎯 產生 {WHEEL_TICKET_COUNT} 注精簡包牌",
            type="secondary",
            use_container_width=True,
            key="l649_wheel_go",
        )
        if wheel_go:
            if len(wheel_pool) != WHEEL_SIZE:
                st.warning(
                    f"⚠️ 需恰好選 {WHEEL_SIZE} 個號(目前 {len(wheel_pool)} 個)。"
                )
            else:
                seed_val: int | None = None
                if wheel_seed_str.strip():
                    try:
                        seed_val = int(wheel_seed_str.strip())
                    except ValueError:
                        st.warning("⚠️ 種子必須是整數,已忽略改用 sorted 排序。")
                try:
                    wheel_tickets = pick_abbreviated_wheel(wheel_pool, seed=seed_val)
                except (ValueError, TypeError) as exc:
                    st.error(f"❌ {exc}")
                else:
                    st.success(
                        f"✅ 已產生 {len(wheel_tickets)} 注 — "
                        f"保證 {WHEEL_GUARANTEE_T} 中 {WHEEL_GUARANTEE_T} 至少 {WHEEL_GUARANTEE_P} 注命中"
                    )
                    wheel_header = "| # | 號碼 |\n|---|---|\n"
                    wheel_rows = []
                    for idx, ticket in enumerate(wheel_tickets, start=1):
                        nums_str = " ".join(f"`{n:02d}`" for n in ticket)
                        wheel_rows.append(f"| {idx} | {nums_str} |")
                    st.markdown(wheel_header + "\n".join(wheel_rows))
                    st.caption(
                        f"成本:{len(wheel_tickets)} × NT$ {UNIT_PRICE_TWD} = "
                        f"**NT$ {len(wheel_tickets) * UNIT_PRICE_TWD}**"
                    )

    # --- Main panel ---------------------------------------------------------------

    fallback_reason: str | None = None
    history: list[list[int]] = []
    provenance: HistoryProvenance | None = None
    awaiting_input = False
    try:
        if source == "上傳 CSV / JSON":
            if uploaded_file is None:
                awaiting_input = True
            else:
                history, provenance = _load_upload(
                    uploaded_file.getvalue(), uploaded_file.name,
                )
        elif source == "貼上文字":
            if not pasted.strip():
                awaiting_input = True
            else:
                # CSV 或 JSON 各走自己的 provenance 路徑
                stripped = pasted.lstrip()
                if stripped.startswith(("[", "{")):
                    history = load_json_string(pasted)
                    provenance = upload_provenance("<paste:json>", len(history))
                else:
                    history, provenance = load_csv_string_with_provenance(
                        pasted, source="<paste:csv>",
                    )
        else:
            history, provenance = _load_bundled(str(sample_csv_path))
    except (HistoryLoadError, OSError) as exc:
        fallback_reason = f"歷史載入失敗:{exc}"

    if fallback_reason:
        st.warning(
            f"⚠️ **降級至靜態安全模式**:{fallback_reason}。"
            f"已套用預設區間 {SUM_MIN}-{SUM_MAX}、無冷熱訊號。"
        )

    st.caption(f"📊 已載入 **{len(history)}** 期歷史資料")
    if provenance is not None:
        st.caption(format_provenance_caption(provenance))

    # §2.4 Freshness check — 只在用倉庫內附 CSV 時檢查（上傳/貼上由使用者負責）
    if source == "倉庫內附 (data/lotto649.csv)":
        stale_msg = _freshness_warning(str(sample_csv_path))
        if stale_msg:
            st.warning(f"⏰ **資料可能過期** — {stale_msg}")

    # --- Always-on preview pane ---
    if source == "上傳 CSV / JSON" and uploaded_file is not None:
        preview_rows = _preview_upload(
            uploaded_file.getvalue(), uploaded_file.name, preview_limit
        )
    elif source == "貼上文字" and pasted.strip():
        preview_rows = _preview_text(pasted, preview_limit)
    elif source not in ("上傳 CSV / JSON", "貼上文字"):
        preview_rows = _preview_bundled(str(sample_csv_path), preview_limit)
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
        st.info("⬆️ 展開上方「參數設定」調整後按『產生大樂透選號』。預設使用倉庫內附歷史資料。")
        return

    # --- Analyze ---
    if history and not fallback_reason:
        try:
            analysis = cached_analysis(
                history,
                hot_sigma, cold_sigma,
                sma_window, range_pad,
                overheat_recent, overheat_min, dormant_periods,
                seed,
            )
        except Exception as exc:  # noqa: BLE001 — defensive 降級至靜態 fallback
            fallback_reason = f"動態分析失敗：{exc}"
            analysis = STATIC_FALLBACK_ANALYSIS
    else:
        analysis = STATIC_FALLBACK_ANALYSIS

    if analysis.is_fallback:
        st.caption("模式：⚠️ 靜態 Fallback")
    else:
        st.caption("模式：✅ 動態 Signal")

    # --- Validate conflicts ---
    if manual_keys and manual_excluded_numbers:
        _conflict = sorted(set(manual_keys) & set(manual_excluded_numbers))
        if _conflict:
            st.error(
                f"參數衝突：號碼 {_conflict} 同時被列為膽碼與排除清單，請擇一。"
            )
            return

    keys_arg = manual_keys
    if batch_disjoint and (manual_keys or analysis.auto_keys):
        st.info("🧩 批次不重複模式已停用膽碼，確保組與組之間 6 號完全不重複。")

    # v6.19 Howard 模式降級檢查(§1 Fail Loud):史料 < 5 期 或 fallback → 強制關閉
    howard_active = howard_mode_ui
    if howard_mode_ui and (len(history) < HOWARD_MIN_HISTORY or analysis.is_fallback):
        reason = (
            f"史料僅 {len(history)} 期(< {HOWARD_MIN_HISTORY})"
            if len(history) < HOWARD_MIN_HISTORY
            else "目前為靜態 fallback、無動態訊號"
        )
        st.warning(
            f"⚠️ **Howard 模式需 ≥ {HOWARD_MIN_HISTORY} 期歷史 + 動態訊號**({reason}),"
            "已自動降回 v6.16 七大濾網。"
        )
        howard_active = False
    if howard_active:
        st.info("🎯 **Howard 嚴格模式啟用**:Round 1 套用黃金 8 條;Round 2 fallback 退回 v6.16。")

    rng = analysis_rng(seed)
    try:
        tickets, _ = generate_tickets(
            history_draws=history if history else [[1, 2, 3, 4, 5, 6]],
            num_tickets=num_tickets,
            manual_keys=keys_arg,
            manual_excluded_tails=manual_excluded_tails,
            manual_excluded_numbers=list(manual_excluded_numbers) if manual_excluded_numbers else None,
            manual_sum_range=manual_sum_range,
            precomputed_analysis=analysis,
            batch_disjoint=batch_disjoint,
            howard_mode=howard_active,
            rng=rng,
        )
    except ValueError as exc:
        st.error(f"參數錯誤：{exc}")
        return

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
    # v6.11: 改顯示「實際生效」的排除尾數(動態 = analysis、手動 = manual_excluded_tails)
    # 避免「手動覆寫 → 主畫面仍顯示動態值」的視覺誤導。
    if manual_excluded_tails is not None:
        _effective_tails = sorted(set(manual_excluded_tails))
        _source_label = "手動覆寫"
        _detail = (
            f"動態建議:{analysis.exclude_tails or '—'}"
            if analysis.exclude_tails or manual_excluded_tails == []
            else "動態建議:—"
        )
    else:
        _effective_tails = list(analysis.exclude_tails)
        _source_label = "動態偵測"
        _detail = (
            f"過熱:{analysis.overheated_tails or '—'} · "
            f"死寂:{analysis.dormant_tails or '—'}"
        )
    if not _effective_tails:
        s2.metric("排除尾數", "✓ 無")
        s2.caption(
            f"來源:{_source_label} · "
            + (
                "(已清空 — 不排除任何尾數)"
                if manual_excluded_tails is not None
                else "尾數分佈均勻、無極端訊號(側欄可調低判定門檻)"
            )
        )
    else:
        s2.metric("排除尾數", str(_effective_tails))
        s2.caption(f"來源:{_source_label} · {_detail}")

    # --- v6.18: 主面板生效快照(§1 Fail Loud 眼見為憑) ---
    _effective_pool = {
        n for n in range(POOL_MIN, POOL_MAX + 1)
        if (n % 10) not in set(_effective_tails)
    } - set(manual_excluded_numbers or [])
    st.caption(
        f"🎯 **實際生效**:排除尾數 {len(_effective_tails)} 種"
        f"(={len(_expand_tails_to_numbers(_effective_tails, POOL_MIN, POOL_MAX))} 顆)"
        f" + 排除特定號碼 {len(manual_excluded_numbers or [])} 顆"
        f" → 選號池剩 **{len(_effective_pool)}** 顆"
    )

    # --- Silent-drop notice ---
    if not manual_keys and manual_excluded_numbers:
        _silent_dropped = sorted(set(analysis.auto_keys) & set(manual_excluded_numbers))
        if _silent_dropped:
            st.caption(
                f"ℹ️ 自動膽碼 {_silent_dropped} 與你的排除清單衝突 — 已自動移除（不影響選號）。"
            )

    if not tickets:
        if batch_disjoint:
            st.warning(
                "批次不重複模式下可行組合為 0。請放寬閾值、減少手動限制或關閉此模式再試。"
            )
        else:
            st.warning(
                "通過七大濾網的組合為 0；Round 2 disjoint fallback 亦無解。"
                "請放寬閾值或縮少手動限制再試。"
            )
        return

    _skip_legacy_split = False
    if batch_disjoint:
        # v6.13: 嚴格 pair-disjoint — 任意 2 顆配對在所有注中至多出現一次
        # v6.15: 均衡硬上限 — 每號出現次數 ≤ ⌈6N/P⌉ + 1
        if len(tickets) < num_tickets:
            st.warning(
                f"🧩 批次不重複模式:已產出 **{len(tickets)} / {num_tickets}** 注 — "
                "濾網/池太緊,「pair 不重複 + 號碼出現次數均衡」的雙約束下湊不到目標。"
                "請放寬尾數排除、減少注數,或在「🎚️ 尾數訊號」section 把判定門檻拉高(降低排除)。"
            )
        else:
            st.success(
                f"🧩 批次不重複模式:已產出 {len(tickets)} 注,"
                "pair 不重複 + 號碼出現次數均衡"
            )
        _skip_legacy_split = True

    # Detect Round 2 fallback tickets
    _effective_keys = (
        set(manual_keys) if manual_keys
        else set(analysis.auto_keys) - set(manual_excluded_numbers or [])
    )
    _r1 = [t for t in tickets if _effective_keys.issubset(t)] if _effective_keys else tickets
    _r2 = [t for t in tickets if not _effective_keys.issubset(t)] if _effective_keys else []

    if _skip_legacy_split:
        pass
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
    keys_used = [] if batch_disjoint else (keys_arg if keys_arg else analysis.auto_keys)
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

    st.subheader("🎟️ 推薦組合 + 每注診斷")
    header = (
        f"| # | 號碼 | 和 | 奇 | >{BIG_THRESHOLD} | 質 | 連 |\n"
        "|---|---|---|---|---|---|---|\n"
    )
    rows = []
    for idx, ticket in enumerate(tickets, start=1):
        s = ticket_stats(ticket)
        nums_str = " ".join(f"`{n:02d}`" for n in ticket)
        rows.append(
            f"| {idx} | {nums_str} | {s['sum']} | {s['odd_count']} "
            f"| {s['big_count']} | {s['prime_count']} | {s['consecutive_pairs']} |"
        )
    st.markdown(header + "\n".join(rows))

    st.caption(
        "提醒：本工具僅為數學優化器，無法改變獨立隨機事件之期望值；理性投注。"
    )
