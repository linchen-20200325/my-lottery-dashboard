"""威力彩 tab UI — 第一區 6/38 + 第二區 1/8 雙池；widget key 加 `pb_` 前綴隔離。"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.ui._view_base import (
    analysis_rng,
    expand_tails_to_numbers as _expand_tails_to_numbers,
    freshness_warning,
    upload_provenance,
)
from src.ui._widgets import (
    backtest_panel,
    run_backtest_cached,
    sma_section,
    tail_signal_sliders,
    zscore_sliders,
)
from src.data.freshness import POWERBALL_DRAW_WEEKDAYS
from src.data.loader_powerball import (
    PowerballLoadError,
    load_csv_file_with_provenance,
    load_csv_string_with_provenance,
    load_json_string,
    preview_recent,
)
from src.data.provenance import (
    HistoryProvenance,
    format_provenance_caption,
)
from src.generator.powerball_engine import (
    BONUS_POOL_MAX,
    BONUS_POOL_MIN,
    DEFAULTS,
    MAIN_POOL_MAX,
    MAIN_POOL_MIN,
    STATIC_FALLBACK_ANALYSIS,
    PowerballAnalysis,
    analyze,
)
from src.generator.powerball_picker import (
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


# --- Cached helpers ----------------------------------------------------------


@st.cache_data(ttl=3600, show_spinner=False)
def _load_bundled(
    path_str: str,
) -> tuple[list[list[int]], list[int], HistoryProvenance]:
    return load_csv_file_with_provenance(Path(path_str))


@st.cache_data(ttl=600, show_spinner=False)
def _freshness_warning(path_str: str) -> str | None:
    """憲法 §2.4:返回 stale 警告字串或 None;cache 10 分鐘避免每 rerun 重讀。"""
    return freshness_warning(path_str, POWERBALL_DRAW_WEEKDAYS)


@st.cache_data(ttl=3600, show_spinner=False)
def _load_upload(
    payload: bytes, name: str,
) -> tuple[list[list[int]], list[int], HistoryProvenance]:
    text = payload.decode("utf-8", errors="replace")
    source = f"<upload:{name}>"
    if name.lower().endswith(".json"):
        draws, specials = load_json_string(text)
        return draws, specials, upload_provenance(source, len(draws))
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
    specials: list[int],
    hot_sigma: float,
    cold_sigma: float,
    sma_window: int,
    range_pad: int,
    overheat_recent: int,
    overheat_min: int,
    dormant_periods: int,
    seed: int,
) -> PowerballAnalysis:
    rng = analysis_rng(seed)
    return analyze(
        draws=history, specials=specials,
        hot_sigma_factor=hot_sigma, cold_sigma_factor=cold_sigma,
        sum_sma_window=sma_window, sum_range_pad=range_pad,
        overheat_recent_periods=overheat_recent,
        overheat_min_count=overheat_min,
        dormant_periods=dormant_periods,
        rng=rng,
    )


# --- Widget callbacks ---------------------------------------------------------
# v6.18.1: 同步 lotto649_view 修正 — 內聯寫 widget session_state 會觸發
# StreamlitAPIException。改 on_click callback 即可。


def _reset_pb_excl_callback() -> None:
    st.session_state.pop("pb_excl_seeded", None)


def _clear_pb_excl_callback() -> None:
    st.session_state["pb_excl_pills"] = []
    st.session_state["pb_excl_multi"] = []
    st.session_state["pb_excl_seeded"] = True


# --- Render entry --------------------------------------------------------------


def render(sample_csv_path: Path) -> None:
    """渲染威力彩 tab。父 entry 已呼叫 `st.set_page_config` / `st.title`。"""

    with st.expander("⚙️ 威力彩 — 參數設定", expanded=True):
        st.markdown("#### 📥 歷史資料")
        source = st.radio(
            "資料來源",
            options=["倉庫內附 (data/powerball.csv)", "上傳 CSV / JSON", "貼上文字"],
            index=0,
            help="Streamlit Cloud 不發外部 API；失敗會自動降級至靜態安全模式。",
            key="pb_source",
        )
        uploaded_file = None
        pasted = ""
        if source == "上傳 CSV / JSON":
            uploaded_file = st.file_uploader(
                "上傳檔案", type=["csv", "json"], key="pb_uploader",
            )
        elif source == "貼上文字":
            pasted = st.text_area(
                "貼上 CSV 或 JSON", height=160, key="pb_paste",
            )

        if hasattr(st, "pills"):
            _preview_choice = st.pills(
                "📋 預覽近 N 期",
                options=[1, 3, 5, 10, 15, 20],
                selection_mode="single",
                default=5,
                key="pb_preview_pills",
            )
            preview_limit = int(_preview_choice) if _preview_choice else 5
        else:
            preview_limit = st.slider(
                "📋 預覽近 N 期", 1, 20, 5, key="pb_preview",
            )

        st.markdown("**🤖 自動更新威力彩歷史**")
        st.link_button(
            "🚀 觸發 GitHub Actions 抓檔 (威力彩)",
            url="https://github.com/LinChen-20200325/my-lottery-dashboard/actions/workflows/update-powerball.yml",
            use_container_width=True,
        )
        st.caption(
            "排程：週一、四 00:07/00:37/01:07/01:37 GMT+8 翻日（4 槽容錯）。"
            "手動：右上 **Run workflow** → `main` → **Run workflow**。"
        )

        st.markdown("#### 🌡️ 第一區 Z-Score 冷熱閾值")
        hot_sigma, cold_sigma = zscore_sliders("pb", DEFAULTS)

        sma_window, range_pad = sma_section(
            "pb", DEFAULTS,
            pad_pills_options=[10, 15, 20, 25, 30, 40, 50], pad_slider_max=50,
        )

        overheat_recent, overheat_min, dormant_periods = tail_signal_sliders(
            "pb", DEFAULTS,
        )

        st.markdown("#### 🎯 第一區膽碼 / 排除 (覆寫)")
        key_mode = st.radio(
            "雙膽", ["動態", "手動"], horizontal=True, key="pb_keymode",
        )
        manual_keys: list[int] | None = None
        if key_mode == "手動":
            st.caption("點擊號碼 1-38 即可加入/移除手動膽碼清單(1-5 顆)。")
            if hasattr(st, "pills"):
                manual_keys = st.pills(
                    "手動膽碼 (1-5 顆,範圍 1-38)",
                    options=list(range(MAIN_POOL_MIN, MAIN_POOL_MAX + 1)),
                    selection_mode="multi",
                    default=[7, 17],
                    format_func=lambda n: f"{n:02d}",
                    label_visibility="collapsed",
                    key="pb_keys_pills",
                )
            else:
                manual_keys = st.multiselect(
                    "手動膽碼 (1-5 顆,範圍 1-38)",
                    options=list(range(MAIN_POOL_MIN, MAIN_POOL_MAX + 1)),
                    default=[7, 17],
                    key="pb_keys",
                )
            manual_keys = list(manual_keys) if manual_keys else []

        tail_mode = st.radio(
            "排除尾數", ["動態", "手動"], horizontal=True, key="pb_tailmode",
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
                    key="pb_extails_pills",
                )
            else:
                manual_excluded_tails = st.multiselect(
                    "手動排除尾數(升級 streamlit≥1.39 可享按鈕點選 UI)",
                    options=list(range(10)),
                    default=[],
                    key="pb_extails",
                )
            manual_excluded_tails = list(manual_excluded_tails) if manual_excluded_tails else []

        # --- v6.18: 早期載入 history + analyze → seed「排除特定號碼」動態建議 ---
        _early_history: list[list[int]] = []
        _early_specials: list[int] = []
        _early_load_failed = False
        try:
            if source == "倉庫內附 (data/powerball.csv)":
                _early_history, _early_specials, _ = _load_bundled(str(sample_csv_path))
            elif source == "上傳 CSV / JSON" and uploaded_file is not None:
                _early_history, _early_specials, _ = _load_upload(
                    uploaded_file.getvalue(), uploaded_file.name,
                )
            elif source == "貼上文字" and pasted.strip():
                if pasted.lstrip().startswith(("[", "{")):
                    _early_history, _early_specials = load_json_string(pasted)
                else:
                    _early_history, _early_specials, _ = load_csv_string_with_provenance(
                        pasted, source="<paste:csv>",
                    )
        except (PowerballLoadError, OSError):
            # DR-4(v6.24 T2):收窄至載入類例外,對齊大樂透;非預期例外不靜默吞掉
            # (§1 Fail Loud)。本路徑僅供 seed 建議,失敗則退回 STATIC_FALLBACK。
            _early_load_failed = True

        _early_analysis = STATIC_FALLBACK_ANALYSIS
        if _early_history and _early_specials and not _early_load_failed:
            try:
                _early_analysis = cached_analysis(
                    history=_early_history, specials=_early_specials,
                    hot_sigma=hot_sigma, cold_sigma=cold_sigma,
                    sma_window=sma_window, range_pad=range_pad,
                    overheat_recent=overheat_recent, overheat_min=overheat_min,
                    dormant_periods=dormant_periods,
                    seed=0,
                )
            except Exception:  # noqa: BLE001 — seed 用,失敗就 fallback
                pass

        _effective_excluded_tails_for_seed = (
            set(manual_excluded_tails)
            if manual_excluded_tails is not None
            else set(_early_analysis.exclude_tails)
        )
        _tail_expanded_for_seed = _expand_tails_to_numbers(
            _effective_excluded_tails_for_seed, MAIN_POOL_MIN, MAIN_POOL_MAX,
        )
        _key_set = set(manual_keys) if manual_keys else set()
        _sys_recommended = sorted(
            (set(_early_analysis.cold) | set(_tail_expanded_for_seed)) - _key_set
        )

        if (
            not _early_analysis.is_fallback
            and not st.session_state.get("pb_excl_seeded", False)
        ):
            st.session_state["pb_excl_pills"] = list(_sys_recommended)
            st.session_state["pb_excl_multi"] = list(_sys_recommended)
            st.session_state["pb_excl_seeded"] = True

        st.markdown("##### 🚫 排除特定號碼 (1-38)")
        if _sys_recommended:
            st.caption(
                f"💡 進場已自動填入系統建議 **{len(_sys_recommended)}** 顆"
                f"(冷號 {len(_early_analysis.cold)} + 過熱尾數展開 "
                f"{len(_tail_expanded_for_seed)}),點擊可加減。"
            )
        else:
            st.caption("點擊號碼即可加入/移除排除清單;空 = 不排除任何號碼。")
        _excl_options = [n for n in range(MAIN_POOL_MIN, MAIN_POOL_MAX + 1) if n not in _key_set]
        if hasattr(st, "pills"):
            manual_excluded_numbers = st.pills(
                "點擊號碼",
                options=_excl_options,
                selection_mode="multi",
                format_func=lambda n: f"{n:02d}",
                label_visibility="collapsed",
                key="pb_excl_pills",
            )
        else:
            manual_excluded_numbers = st.multiselect(
                "排除號碼(升級 streamlit≥1.39 可享按鈕點選 UI)",
                options=_excl_options,
                format_func=lambda n: f"{n:02d}",
                key="pb_excl_multi",
            )
        excl_arg = list(manual_excluded_numbers) if manual_excluded_numbers else None

        _btn_col1, _btn_col2 = st.columns(2)
        _btn_col1.button(
            "🔄 重設為系統建議",
            key="pb_reset_excl",
            use_container_width=True,
            help=f"重設為系統建議的 {len(_sys_recommended)} 顆排除清單",
            on_click=_reset_pb_excl_callback,
        )
        _btn_col2.button(
            "🧹 全清空",
            key="pb_clear_excl",
            use_container_width=True,
            help="清空排除特定號碼清單",
            on_click=_clear_pb_excl_callback,
        )

        st.markdown("#### ⚡ 第二區特別號 (1-8)")
        bonus_mode = st.radio(
            "選號方式", ["動態 (熱號隨機)", "手動指定"],
            horizontal=True, key="pb_bonus_mode",
        )
        manual_bonus: int | None = None
        if bonus_mode == "手動指定":
            manual_bonus = st.selectbox(
                "選擇第二區號碼",
                options=list(range(BONUS_POOL_MIN, BONUS_POOL_MAX + 1)),
                index=0,
                key="pb_bonus_val",
            )

        st.markdown("#### 🧮 和值區間 (覆寫)")
        sum_mode = st.radio(
            "和值來源", ["動態 SMA", "手動"],
            horizontal=True, key="pb_summode",
        )
        manual_sum_range: tuple[int, int] | None = None
        if sum_mode == "手動":
            sum_lo, sum_hi = st.slider(
                "手動和值區間", 21, 213, (SUM_MIN, SUM_MAX), key="pb_sumrange",
            )
            manual_sum_range = (int(sum_lo), int(sum_hi))

        st.markdown("#### ⚙️ 產出")
        if hasattr(st, "pills"):
            _pb_num_choice = st.pills(
                "注數",
                options=[1, 3, 5, 8, 10],
                selection_mode="single",
                default=10,
                key="pb_num_pills",
            )
            num_tickets = int(_pb_num_choice) if _pb_num_choice else 10
        else:
            num_tickets = st.slider("注數", 1, 10, 10, key="pb_num")
        seed_input = st.number_input(
            "隨機種子 (0 = 真隨機)", min_value=0, value=0, step=1, key="pb_seed",
        )

        batch_disjoint = st.checkbox(
            "🧩 批次推薦：注間號碼完全不重複",
            value=True,
            help="開啟後各注 6 顆號碼完全不重疊（會停用膽碼），用於提高批次覆蓋率。",
            key="pb_batch_disjoint",
        )

        go = st.button(
            "🎲 產生威力彩選號", type="primary", use_container_width=True,
            key="pb_go",
        )

    with st.expander("📐 威力彩 五大濾網規則 (1-38 池重校版)"):
        st.markdown(f"""
- **質數**：`{MIN_PRIME_COUNT} ≤ 質數 ≤ {MAX_PRIME_COUNT}`（1-38 池內 12 顆質數，去掉大樂透的 41/43/47）
- **連號**：`連號對數 ≤ {MAX_CONSECUTIVE_PAIRS}`
- **動態和值**：`Phase 1 計算區間`（失敗回 `{SUM_MIN}-{SUM_MAX}`）
- **奇偶**：`奇數 ∈ {sorted(ALLOWED_ODD_COUNTS)}`
- **大數**：`> {BIG_THRESHOLD} 至少 {MIN_BIG_COUNT} 個`（vs 大樂透 >31，因池小一階）

第二區為**獨立池** (1-8)：以遺漏期數排序、`gap ≤ mean` = 熱號、auto pick 從熱號隨機抽。
        """)

    # --- 載入歷史 + fallback -----------------------------------------------------

    history: list[list[int]] = []
    specials: list[int] = []
    provenance: HistoryProvenance | None = None
    load_error: str | None = None
    preview_rows: list[dict] = []

    try:
        if source == "倉庫內附 (data/powerball.csv)":
            history, specials, provenance = _load_bundled(str(sample_csv_path))
            preview_rows = _preview_bundled(str(sample_csv_path), preview_limit)
        elif source == "上傳 CSV / JSON" and uploaded_file is not None:
            payload = uploaded_file.getvalue()
            history, specials, provenance = _load_upload(payload, uploaded_file.name)
            preview_rows = _preview_upload(payload, uploaded_file.name, preview_limit)
        elif source == "貼上文字" and pasted.strip():
            if pasted.lstrip().startswith(("[", "{")):
                history, specials = load_json_string(pasted)
                provenance = upload_provenance("<paste:json>", len(history))
            else:
                history, specials, provenance = load_csv_string_with_provenance(
                    pasted, source="<paste:csv>",
                )
            preview_rows = _preview_text(pasted, preview_limit)
        else:
            load_error = "等待資料輸入:請選擇來源並上傳/貼上 CSV/JSON,或等 cron 自動抓檔。"
    except PowerballLoadError as exc:
        load_error = f"資料解析失敗:{exc}"
    except Exception as exc:  # noqa: BLE001
        load_error = f"未預期錯誤:{exc}"

    st.caption(f"📊 已載入 **{len(history)}** 期威力彩歷史資料")
    if provenance is not None:
        st.caption(format_provenance_caption(provenance))

    # §2.4 Freshness check — 只在用倉庫內附 CSV 時檢查
    if source == "倉庫內附 (data/powerball.csv)":
        stale_msg = _freshness_warning(str(sample_csv_path))
        if stale_msg:
            st.warning(f"⏰ **資料可能過期** — {stale_msg}")

    # --- 預覽 ---
    if preview_rows:
        st.subheader(f"📋 最近 {len(preview_rows)} 期開獎")
        header = (
            "| 期別 | 日期 | 1 | 2 | 3 | 4 | 5 | 6 | 第二區 |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
        )
        body = "\n".join(
            "| " + r["term"] + " | " + r["date"] + " | "
            + " | ".join(f"`{n:02d}`" for n in r["nums"])
            + " | ⚡`" + r["special"] + "` |"
            for r in preview_rows
        )
        st.markdown(header + body)
    elif load_error:
        st.info(load_error)

    st.divider()

    # --- Analysis + fallback ---
    analysis: PowerballAnalysis
    if history and specials:
        try:
            analysis = cached_analysis(
                history=history, specials=specials,
                hot_sigma=hot_sigma, cold_sigma=cold_sigma,
                sma_window=sma_window, range_pad=range_pad,
                overheat_recent=overheat_recent, overheat_min=overheat_min,
                dormant_periods=dormant_periods,
                seed=int(seed_input),
            )
        except Exception as exc:  # noqa: BLE001
            st.warning(f"訊號分析失敗，降級至靜態安全模式：{exc}")
            analysis = STATIC_FALLBACK_ANALYSIS
    else:
        analysis = STATIC_FALLBACK_ANALYSIS

    if analysis.is_fallback:
        st.info(
            "🛡️ 目前為**靜態安全模式** (Static Fallback)：無冷熱訊號、無排除尾數、"
            f"和值區間 {SUM_MIN}-{SUM_MAX}、第二區回退至 {BONUS_POOL_MIN}。"
            "請於上方載入歷史 CSV 啟用動態訊號（或等首次 cron 自動填入）。"
        )

    # --- 訊號展示 ---
    col_signal, col_bonus = st.columns([2, 1])
    with col_signal:
        st.subheader("🌡️ 第一區訊號 (1-38)")
        st.markdown(
            f"**熱碼** (gap ≤ {analysis.hot_threshold:.1f})："
            + (" ".join(f"`{n:02d}`" for n in analysis.hot) or "—")
        )
        st.markdown(
            f"**冷碼** (gap ≥ {analysis.cold_threshold:.1f})："
            + (" ".join(f"`{n:02d}`" for n in analysis.cold) or "—")
        )
        st.markdown(
            f"**和值動態區間**：`{analysis.sum_min_dynamic} - {analysis.sum_max_dynamic}`"
            f"（SMA={analysis.sum_sma:.1f}）"
        )
        # v6.11: 改顯示「實際生效」的排除尾數 — 動態 = analysis、手動 = manual_excluded_tails。
        # 避免「手動覆寫 → 主畫面仍顯示動態值」的視覺誤導。
        if manual_excluded_tails is not None:
            _effective_tails = sorted(set(manual_excluded_tails))
            _source_label = "手動覆寫"
            _detail = (
                f"動態建議:{analysis.exclude_tails or '—'}"
            )
        else:
            _effective_tails = list(analysis.exclude_tails)
            _source_label = "動態偵測"
            _detail = (
                f"過熱:{analysis.overheated_tails or '—'} · "
                f"死寂:{analysis.dormant_tails or '—'}"
            )
        if _effective_tails:
            st.markdown(
                "**排除尾數**:" +
                " ".join(f"`{t}`" for t in _effective_tails)
            )
            st.caption(f"來源:{_source_label} · {_detail}")
        else:
            st.markdown("**排除尾數**:✓ 無")
            st.caption(
                f"來源:{_source_label} · "
                + (
                    "(已清空 — 不排除任何尾數)"
                    if manual_excluded_tails is not None
                    else "尾數分佈均勻、無極端訊號(側欄可調低判定門檻)"
                )
            )
        st.markdown(
            "**自動雙膽**：" +
            (" ".join(f"`{n:02d}`" for n in analysis.auto_keys) or "—")
        )

    with col_bonus:
        st.subheader("⚡ 第二區訊號 (1-8)")
        st.markdown("**熱號**：" +
                    " ".join(f"`{n}`" for n in analysis.bonus_hot))
        st.markdown("**冷號**：" +
                    (" ".join(f"`{n}`" for n in analysis.bonus_cold) or "—"))
        st.markdown(f"**自動選號**：`{analysis.bonus_auto_pick}`")

    # --- v6.18: 主面板生效快照(§1 Fail Loud 眼見為憑) ---
    _effective_pool = {
        n for n in range(MAIN_POOL_MIN, MAIN_POOL_MAX + 1)
        if (n % 10) not in set(_effective_tails)
    } - set(excl_arg or [])
    st.caption(
        f"🎯 **實際生效**:排除尾數 {len(_effective_tails)} 種"
        f"(={len(_expand_tails_to_numbers(_effective_tails, MAIN_POOL_MIN, MAIN_POOL_MAX))} 顆)"
        f" + 排除特定號碼 {len(excl_arg or [])} 顆"
        f" → 第一區選號池剩 **{len(_effective_pool)}** 顆"
    )

    st.divider()

    # --- 🔮 回測(v6.25;always-on,獨立於「產生選號」按鈕;威力彩無霍華德)---
    with st.expander("🔮 回測(依現在策略每期重選,比對歷史開獎)", expanded=False):
        backtest_panel(
            key_prefix="pb", show_howard=False,
            run=lambda c: run_backtest_cached(
                str(sample_csv_path), "powerball", c["num_tickets"],
                c["max_periods"], c["lookback"], c["batch_disjoint"],
                c["howard_mode"], hot_sigma, cold_sigma, sma_window, range_pad,
                overheat_recent, overheat_min, dormant_periods, c["seed"],
                c["apply_manual"],
                tuple(manual_keys) if manual_keys else None,
                tuple(manual_excluded_tails) if manual_excluded_tails else None,
                tuple(excl_arg) if excl_arg else None,
            ),
        )

    if not go:
        st.info("⬆️ 展開上方「參數設定」調整後按『產生威力彩選號』。預設使用倉庫內附歷史資料。")
        return

    if not (history and specials):
        st.warning("⚠️ 尚無歷史資料 — 請先載入 CSV 或等 cron 抓檔。")
        return

    # DR-2(v6.24 T2):膽碼 ∩ 排除 衝突檢查(對齊大樂透;否則使用者只會吃 picker
    # raise 的generic 訊息)。picker resolve_pool_and_keys 仍會擋,此處給友善前置回饋。
    if manual_keys and excl_arg:
        _conflict = sorted(set(manual_keys) & set(excl_arg))
        if _conflict:
            st.error(
                f"參數衝突：號碼 {_conflict} 同時被列為膽碼與排除清單，請擇一。"
            )
            return

    keys_arg = manual_keys
    if batch_disjoint and (manual_keys or analysis.auto_keys):
        st.info("🧩 批次不重複模式已停用膽碼，確保組與組之間 6 號完全不重複。")

    rng = analysis_rng(int(seed_input))
    try:
        tickets, bonus_pick, _ = generate_tickets(
            history_draws=history,
            history_specials=specials,
            num_tickets=num_tickets,
            manual_keys=keys_arg,
            manual_excluded_tails=manual_excluded_tails,
            manual_excluded_numbers=excl_arg,
            manual_sum_range=manual_sum_range,
            manual_bonus=manual_bonus,
            precomputed_analysis=analysis,
            batch_disjoint=batch_disjoint,
            rng=rng,
        )
    except ValueError as exc:
        st.error(f"❌ 生成失敗：{exc}")
        return

    if not tickets:
        st.warning("⚠️ 五大濾網篩光所有候選 — 請放寬和值區間或減少排除號碼。")
        return

    # v6.13: 嚴格 pair-disjoint — 任意 2 顆配對在所有注中至多出現一次
    # v6.15: 均衡硬上限 — 每號出現次數 ≤ ⌈6N/P⌉ + 1
    if batch_disjoint and len(tickets) < num_tickets:
        st.warning(
            f"🧩 批次不重複模式:已產出 **{len(tickets)} / {num_tickets}** 注 · "
            f"第二區 ⚡`{bonus_pick}` — 濾網/池太緊,「pair 不重複 + 號碼出現次數均衡」"
            "的雙約束下湊不到目標。請放寬尾數排除、減少注數,或在「🎚️ 尾數訊號」"
            "section 把判定門檻拉高。"
        )
    elif batch_disjoint:
        st.success(
            f"✅ 產出 {len(tickets)} 注 · 第二區 ⚡`{bonus_pick}` · "
            "🧩 pair 不重複 + 號碼出現次數均衡"
        )
    else:
        st.subheader(f"✅ 產出 {len(tickets)} 注 · 第二區 ⚡`{bonus_pick}`")

    header = (
        f"| # | 號碼 | ⚡ | 和 | 奇 | >{BIG_THRESHOLD} | 質 |\n"
        "|---|---|---|---|---|---|---|\n"
    )
    rows = []
    for i, t in enumerate(tickets, 1):
        s = ticket_stats(t)
        nums_str = " ".join(f"`{n:02d}`" for n in t)
        rows.append(
            f"| {i} | {nums_str} | ⚡`{bonus_pick}` "
            f"| {s['sum']} | {s['odd_count']} | {s['big_count']} | {s['prime_count']} |"
        )
    st.markdown(header + "\n".join(rows))

    st.caption(
        "提醒：本工具僅為數學優化器，無法改變獨立隨機事件之期望值；理性投注。"
    )
