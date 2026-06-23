"""大樂透 tab UI — 沿用 v5.1.2 邏輯、widget key 加 `l649_` 前綴隔離 tab 命名空間。"""

from __future__ import annotations

import random
from pathlib import Path

import streamlit as st

from src.analytics.cost_calc import UNIT_PRICE_TWD, summary as cost_summary
from src.data.freshness import LOTTO649_DRAW_WEEKDAYS, check_freshness
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
    now_utc,
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
    _count_disjoint_prefix,
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
    return check_freshness(Path(path_str), LOTTO649_DRAW_WEEKDAYS)


@st.cache_data(ttl=3600, show_spinner=False)
def _load_upload(payload: bytes, name: str) -> tuple[list[list[int]], HistoryProvenance]:
    text = payload.decode("utf-8", errors="replace")
    source = f"<upload:{name}>"
    if name.lower().endswith(".json"):
        # JSON 路徑不帶 draw_date,provenance.as_of 為 None
        draws = load_json_string(text)
        prov = HistoryProvenance(
            source=source, fetched_at=now_utc(), n_rows=len(draws),
            as_of=None, earliest=None,
        )
        return draws, prov
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

        preview_limit = st.slider(
            "📋 預覽近 N 期", 1, 20, 5,
            help="主面板頂部會顯示最近 N 期開獎，用來驗證資料是否正確下載/上傳。",
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
        hot_sigma = st.slider(
            "熱碼倍率 (μ − Nσ)", 0.0, 1.5, DEFAULTS["hot_sigma_factor"],
            step=0.1, key="l649_hot",
        )
        cold_sigma = st.slider(
            "冷碼倍率 (μ + Nσ)", 0.5, 3.0, DEFAULTS["cold_sigma_factor"],
            step=0.1, key="l649_cold",
        )

        st.markdown("#### 📈 動態和值 (SMA)")
        sma_window = st.slider(
            "SMA 視窗 (期數)", 5, 30, DEFAULTS["sum_sma_window"], key="l649_sma",
        )
        range_pad = st.slider(
            "和值 ±pad", 10, 60, DEFAULTS["sum_range_pad"], key="l649_pad",
        )

        st.markdown("#### 🎚️ 尾數訊號")
        st.caption(
            "↗ **拉高 = 自動排除少**(條件變嚴格,較少尾數被列為過熱/死寂) ｜ "
            "↘ **拉低 = 自動排除多**(條件變寬鬆,更多尾數被列入排除)"
        )
        overheat_recent = st.slider(
            "過熱觀察期", 1, 10, DEFAULTS["overheat_recent_periods"], key="l649_oh_r",
            help="觀察近 N 期的尾數出現次數。N 越小 → 越快反應近期熱點 → 越容易判過熱。",
        )
        overheat_min = st.slider(
            "過熱判定次數", 1, 10, DEFAULTS["overheat_min_count"], key="l649_oh_m",
            help="觀察期內出現 ≥ N 次即判為過熱。**N 拉到 4-6 = 排除少**,N=2-3 = 排除多。",
        )
        dormant_periods = st.slider(
            "死寂判定期", 5, 30, DEFAULTS["dormant_periods"], key="l649_dorm",
            help="連續 N 期未出現即判為死寂。**N 拉到 12-20 = 排除少**,N=5-8 = 排除多。",
        )

        st.markdown("#### 🎯 膽碼 / 排除 (覆寫)")
        key_mode = st.radio(
            "雙膽", ["動態", "手動"], horizontal=True, key="l649_keymode",
        )
        manual_keys: list[int] | None = None
        if key_mode == "手動":
            manual_keys = st.multiselect(
                "手動膽碼 (1-5 顆)",
                options=list(range(POOL_MIN, POOL_MAX + 1)),
                default=[7, 33],
                key="l649_keys",
            )

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

        st.markdown("##### 🚫 排除特定號碼")
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
                key="l649_excl_pills",
            )
        else:
            manual_excluded_numbers = st.multiselect(
                "排除號碼（升級 streamlit≥1.39 可享按鈕點選 UI）",
                options=_excl_options,
                default=[],
                format_func=lambda n: f"{n:02d}",
                key="l649_excl_multi",
            )
        if manual_excluded_numbers:
            st.caption(
                f"已排除 **{len(manual_excluded_numbers)}** 顆："
                + ", ".join(f"{n:02d}" for n in sorted(manual_excluded_numbers))
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

        seed = st.number_input(
            "隨機種子（0 = 不固定）", min_value=0, max_value=10_000_000,
            value=0, step=1, key="l649_seed",
        )
        go = st.button(
            "🎲 產生大樂透選號", type="primary", use_container_width=True,
            key="l649_go",
        )

    with st.expander("📐 大樂透 五大濾網規則"):
        st.markdown(
            f"""
- **質數**：`{MIN_PRIME_COUNT} ≤ 質數 ≤ {MAX_PRIME_COUNT}`（質數集 {{2,3,5,7,11,13,17,19,23,29,31,37,41,43,47}}）
- **連號**：`連號對數 ≤ {MAX_CONSECUTIVE_PAIRS}`
- **動態和值**：`Phase 1 計算區間` (失敗回 `{SUM_MIN}-{SUM_MAX}`)
- **奇偶**：`奇數 ∈ {sorted(ALLOWED_ODD_COUNTS)}`
- **大數**：`> {BIG_THRESHOLD} 至少 {MIN_BIG_COUNT} 個`
"""
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
                    provenance = HistoryProvenance(
                        source="<paste:json>", fetched_at=now_utc(),
                        n_rows=len(history), as_of=None, earliest=None,
                    )
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
        except (ValueError, Exception) as exc:  # noqa: BLE001 — defensive
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
    rng = random.Random(seed) if seed else None
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
                "通過五大濾網的組合為 0；Round 2 disjoint fallback 亦無解。"
                "請放寬閾值或縮少手動限制再試。"
            )
        return

    _skip_legacy_split = False
    _disjoint_count = 0
    if batch_disjoint:
        # v6.12: 算 leading disjoint prefix(Phase 1 真不重複注數),Phase 2/3 補齊注帶共號
        _disjoint_count = _count_disjoint_prefix(tickets)
        _overlap_count = len(tickets) - _disjoint_count
        if len(tickets) < num_tickets:
            st.warning(
                f"🧩 批次不重複模式:已產出 **{len(tickets)} / {num_tickets}** 注 "
                f"(完全不重複 {_disjoint_count} + 補齊 {_overlap_count})— "
                "池過小且濾網嚴。請放寬尾數排除或減少注數。"
            )
        elif _overlap_count == 0:
            st.success(f"🧩 批次不重複模式:✅ **全部 {len(tickets)} 注完全不重複**")
        else:
            st.success(
                f"🧩 批次不重複模式:**前 {_disjoint_count} 注完全不重複** + "
                f"**後 {_overlap_count} 注允許共號補齊**(共 {len(tickets)} 注)"
            )
            st.caption(
                "池內可用號碼有限,達物理上限 ⌊pool/6⌋ 後改用標準模式補齊;"
                "後段注的部分號碼會與前段重疊(但每注 6 顆內部不重複、且整注不會與前段相同)。"
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

    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.subheader("🎟️ 推薦組合")
        for idx, ticket in enumerate(tickets, start=1):
            # v6.12: batch_disjoint 模式且發生 Phase 2/3 降級時,插分隔線
            if (
                batch_disjoint
                and _disjoint_count > 0
                and _disjoint_count < len(tickets)
                and idx == _disjoint_count + 1
            ):
                st.markdown("---")
                st.caption("⬇️ 以下為 Phase 2/3 補齊注(允許與上方共號)")
            nums_str = "   ".join(f"`{n:02d}`" for n in ticket)
            st.markdown(f"**第 {idx} 注**:{nums_str}")

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
