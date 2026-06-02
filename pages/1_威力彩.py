"""威力彩量化訊號儀表板 (v6.0) — Streamlit multipage 子頁."""

from __future__ import annotations

import random
from itertools import combinations as _combs_ui
from pathlib import Path

import streamlit as st

from src.data.loader_powerball import (
    PowerballLoadError,
    load_csv_file,
    load_csv_string,
    load_json_string,
    preview_recent,
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

SAMPLE_CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "powerball.csv"

st.set_page_config(
    page_title="威力彩量化訊號儀表板 v6.0",
    page_icon="⚡",
    layout="wide",
)

st.title("⚡ 威力彩量化訊號儀表板 v6.0")
st.caption(
    "第一區 6/38 + 第二區 1/8 · Z-Score 動態冷熱 + SMA 動態和值 + 容錯架構 (Graceful Degradation)。"
    "EV<0 認知；本工具僅優化資金運用。"
)


# --- Cached load + analyze ----------------------------------------------------


@st.cache_data(ttl=3600, show_spinner=False)
def _load_bundled() -> tuple[list[list[int]], list[int]]:
    return load_csv_file(SAMPLE_CSV_PATH)


@st.cache_data(ttl=3600, show_spinner=False)
def _load_upload(payload: bytes, name: str) -> tuple[list[list[int]], list[int]]:
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
    rng = random.Random(seed) if seed else random.Random()
    return analyze(
        draws=history,
        specials=specials,
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
    st.header("📥 威力彩歷史資料")
    source = st.radio(
        "資料來源",
        options=["倉庫內附 (data/powerball.csv)", "上傳 CSV / JSON", "貼上文字"],
        index=0,
        help="Streamlit Cloud 不發外部 API；失敗會自動降級至靜態安全模式。",
    )
    uploaded_file = None
    pasted = ""
    if source == "上傳 CSV / JSON":
        uploaded_file = st.file_uploader("上傳檔案", type=["csv", "json"],
                                         key="pb_uploader")
    elif source == "貼上文字":
        pasted = st.text_area("貼上 CSV 或 JSON", height=160, key="pb_paste")

    preview_limit = st.slider(
        "📋 預覽近 N 期", 1, 20, 5, key="pb_preview",
    )

    st.divider()
    st.markdown("**🤖 自動更新威力彩歷史**")
    st.link_button(
        "🚀 觸發 GitHub Actions 抓檔",
        url="https://github.com/LinChen-20200325/my-lottery-dashboard/actions/workflows/update-powerball.yml",
        use_container_width=True,
    )
    st.caption(
        "排程：每週一、週四 24:00 GMT+8（00:07/00:37/01:07/01:37 四槽容錯）自動更新。"
        "手動：右上 **Run workflow** → 選 `main` → **Run workflow**。"
    )

    st.header("🌡️ Z-Score 冷熱閾值")
    hot_sigma = st.slider(
        "熱碼倍率 (μ − Nσ)", 0.0, 1.5, DEFAULTS["hot_sigma_factor"],
        step=0.1, key="pb_hot",
    )
    cold_sigma = st.slider(
        "冷碼倍率 (μ + Nσ)", 0.5, 3.0, DEFAULTS["cold_sigma_factor"],
        step=0.1, key="pb_cold",
    )

    st.header("📈 動態和值 (SMA)")
    sma_window = st.slider(
        "SMA 視窗 (期數)", 5, 30, DEFAULTS["sum_sma_window"], key="pb_sma",
    )
    range_pad = st.slider(
        "和值 ±pad", 10, 50, DEFAULTS["sum_range_pad"], key="pb_pad",
    )

    st.header("🎚️ 尾數訊號")
    overheat_recent = st.slider(
        "過熱觀察期", 1, 10, DEFAULTS["overheat_recent_periods"], key="pb_oh_r",
    )
    overheat_min = st.slider(
        "過熱判定次數", 1, 10, DEFAULTS["overheat_min_count"], key="pb_oh_m",
    )
    dormant_periods = st.slider(
        "死寂判定期", 5, 30, DEFAULTS["dormant_periods"], key="pb_dorm",
    )

    st.header("🎯 第一區膽碼 / 排除 (覆寫)")
    key_mode = st.radio("雙膽", ["動態", "手動"], horizontal=True, key="pb_keymode")
    manual_keys: list[int] | None = None
    if key_mode == "手動":
        manual_keys = st.multiselect(
            "手動膽碼 (1-5 顆，範圍 1-38)",
            options=list(range(MAIN_POOL_MIN, MAIN_POOL_MAX + 1)),
            default=[7, 17],
            key="pb_keys",
        )

    tail_mode = st.radio("排除尾數", ["動態", "手動"], horizontal=True, key="pb_tailmode")
    manual_excluded_tails: list[int] | None = None
    if tail_mode == "手動":
        manual_excluded_tails = st.multiselect(
            "手動排除尾數",
            options=list(range(10)),
            default=[],
            key="pb_extails",
        )

    st.subheader("🚫 排除特定號碼")
    _key_set = set(manual_keys) if manual_keys else set()
    excl_grid_cols = st.columns(10)
    manual_excluded_numbers: list[int] = []
    for n in range(MAIN_POOL_MIN, MAIN_POOL_MAX + 1):
        col = excl_grid_cols[(n - 1) % 10]
        disabled = n in _key_set
        if col.checkbox(
            f"{n:02d}",
            value=False,
            key=f"pb_excl_{n}",
            disabled=disabled,
        ) and not disabled:
            manual_excluded_numbers.append(n)
    excl_arg = manual_excluded_numbers or None

    st.header("⚡ 第二區 (1-8 特別號)")
    bonus_mode = st.radio("選號方式", ["動態 (熱號隨機)", "手動指定"],
                          horizontal=False, key="pb_bonus_mode")
    manual_bonus: int | None = None
    if bonus_mode == "手動指定":
        manual_bonus = st.selectbox(
            "選擇第二區號碼",
            options=list(range(BONUS_POOL_MIN, BONUS_POOL_MAX + 1)),
            index=0,
            key="pb_bonus_val",
        )

    st.header("🧮 和值區間 (覆寫)")
    sum_override_mode = st.radio(
        "和值來源", ["動態 (SMA ± pad)", "手動覆寫"],
        horizontal=True, key="pb_sum_mode",
    )
    manual_sum_range: tuple[int, int] | None = None
    if sum_override_mode == "手動覆寫":
        sum_lo, sum_hi = st.slider(
            "手動和值區間", 21, 213, (SUM_MIN, SUM_MAX), key="pb_sum_range",
        )
        manual_sum_range = (int(sum_lo), int(sum_hi))

    st.header("⚙️ 產生設定")
    num_tickets = st.slider("產生注數", 1, 10, 5, key="pb_num")
    seed_input = st.number_input(
        "隨機種子 (0 = 真隨機)", min_value=0, value=0, step=1, key="pb_seed",
    )

    st.subheader("🧷 進階：注間不重複")
    pair_disjoint = st.checkbox(
        "啟用 pair-disjoint (注間 2 號對不重複)",
        value=False, key="pb_pd",
    )
    pair_overlap_max = st.slider(
        "允許 pair 共享上限", 0, 3, 0,
        disabled=not pair_disjoint, key="pb_pomax",
    )


# --- 載入歷史 + fallback ------------------------------------------------------

history: list[list[int]] = []
specials: list[int] = []
load_error: str | None = None
preview_rows: list[dict] = []

try:
    if source == "倉庫內附 (data/powerball.csv)":
        history, specials = _load_bundled()
        preview_rows = _preview_bundled(preview_limit)
    elif source == "上傳 CSV / JSON" and uploaded_file is not None:
        payload = uploaded_file.getvalue()
        history, specials = _load_upload(payload, uploaded_file.name)
        preview_rows = _preview_upload(payload, uploaded_file.name, preview_limit)
    elif source == "貼上文字" and pasted.strip():
        if pasted.lstrip().startswith(("[", "{")):
            history, specials = load_json_string(pasted)
        else:
            history, specials = load_csv_string(pasted)
        preview_rows = _preview_text(pasted, preview_limit)
    else:
        load_error = "等待資料輸入：請選擇來源並上傳/貼上 CSV/JSON。"
except PowerballLoadError as exc:
    load_error = f"資料解析失敗：{exc}"
except Exception as exc:  # noqa: BLE001
    load_error = f"未預期錯誤：{exc}"

# --- 預覽近 N 期 ---
if preview_rows:
    st.subheader(f"📋 近 {len(preview_rows)} 期開獎")
    cols_per_row = 5
    for i in range(0, len(preview_rows), cols_per_row):
        cols = st.columns(min(cols_per_row, len(preview_rows) - i))
        for j, row in enumerate(preview_rows[i:i + cols_per_row]):
            with cols[j]:
                st.markdown(f"**{row['term']}** · {row['date']}")
                st.markdown(
                    " ".join(f"`{n:02d}`" for n in row["nums"])
                    + f"  ⚡`{row['special']}`"
                )
    st.divider()


# --- Analyze + fallback ---
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
    if load_error:
        st.warning(load_error + "（已啟用靜態安全模式）")

if analysis.is_fallback:
    st.info("🛡️ 目前為**靜態安全模式** (Static Fallback)：無冷熱訊號、無排除尾數、"
            "和值區間 90-144、第二區回退至 1。請於側欄載入歷史 CSV 啟用動態訊號。")


# --- 主面板 -------------------------------------------------------------------

col_signal, col_stats = st.columns([2, 1])
with col_signal:
    st.subheader("🌡️ 第一區訊號 (1-38)")
    st.markdown(f"**熱碼** (gap ≤ {analysis.hot_threshold:.1f})："
                + " ".join(f"`{n:02d}`" for n in analysis.hot) or "—")
    st.markdown(f"**冷碼** (gap ≥ {analysis.cold_threshold:.1f})："
                + " ".join(f"`{n:02d}`" for n in analysis.cold) or "—")
    st.markdown(f"**和值動態區間**：`{analysis.sum_min_dynamic} - {analysis.sum_max_dynamic}`"
                + f"（SMA={analysis.sum_sma:.1f}）")
    st.markdown("**排除尾數**：" +
                (" ".join(f"`{t}`" for t in analysis.exclude_tails) or "—"))
    st.markdown("**自動雙膽**：" +
                (" ".join(f"`{n:02d}`" for n in analysis.auto_keys) or "—"))

with col_stats:
    st.subheader("⚡ 第二區訊號 (1-8)")
    st.markdown("**熱號**：" +
                " ".join(f"`{n}`" for n in analysis.bonus_hot))
    st.markdown("**冷號**：" +
                (" ".join(f"`{n}`" for n in analysis.bonus_cold) or "—"))
    st.markdown(f"**自動選號**：`{analysis.bonus_auto_pick}`")

st.divider()


# --- 生成按鈕 -----------------------------------------------------------------

if st.button("🎲 產生威力彩選號", type="primary", use_container_width=True,
             disabled=not (history and specials)):
    # auto-key trim：pair_disjoint 模式下若 auto_keys 為雙膽 → 留熱膽
    keys_arg = manual_keys
    if (pair_disjoint and manual_keys is None
            and len(analysis.auto_keys) >= 2):
        # 留 hot bucket 中第一顆當錨點
        anchor = next((k for k in analysis.auto_keys if k in analysis.hot),
                      analysis.auto_keys[0])
        keys_arg = [anchor]
        st.info(f"🔧 pair-disjoint 模式：自動雙膽 {analysis.auto_keys} → 保留熱膽 `{anchor}` 當錨點。")

    rng = random.Random(int(seed_input)) if seed_input else random.Random()
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
            pair_disjoint=pair_disjoint,
            pair_overlap_max=pair_overlap_max,
            rng=rng,
        )
    except ValueError as exc:
        st.error(f"❌ 生成失敗：{exc}")
    else:
        if not tickets:
            st.warning("⚠️ 五大濾網篩光所有候選 — 請放寬和值區間或減少排除號碼。")
        else:
            st.subheader(f"✅ 產出 {len(tickets)} 注 + 第二區 `{bonus_pick}`")
            for i, t in enumerate(tickets, 1):
                stats = ticket_stats(t)
                cols = st.columns([3, 1, 1, 1, 1])
                cols[0].markdown(f"**第{i}注**　"
                                 + " ".join(f"`{n:02d}`" for n in t)
                                 + f"　⚡`{bonus_pick}`")
                cols[1].metric("和", stats["sum"])
                cols[2].metric("奇", stats["odd_count"])
                cols[3].metric(f">{BIG_THRESHOLD}", stats["big_count"])
                cols[4].metric("質", stats["prime_count"])

            # 注間共享 pair 診斷
            if len(tickets) >= 2:
                all_pairs: dict[frozenset[int], int] = {}
                for t in tickets:
                    for p in _combs_ui(t, 2):
                        fp = frozenset(p)
                        all_pairs[fp] = all_pairs.get(fp, 0) + 1
                shared = {p: c for p, c in all_pairs.items() if c >= 2}
                if shared:
                    st.caption(f"⚠️ 共享 pair {len(shared)} 組（pair_disjoint={'on' if pair_disjoint else 'off'}）")
                else:
                    st.caption("✅ 注間 pair 完全不重複")


# --- 濾網規則速覽 -------------------------------------------------------------
with st.expander("📐 五大濾網規則 (1-38 池重校版)"):
    st.markdown(f"""
    1. **奇數數量** ∈ `{sorted(ALLOWED_ODD_COUNTS)}`
    2. **大數 (> {BIG_THRESHOLD})** ≥ `{MIN_BIG_COUNT}` 顆
    3. **質數** ∈ `[{MIN_PRIME_COUNT}, {MAX_PRIME_COUNT}]` 顆（質數集 = 1-38 內 12 個質數）
    4. **連號對數** ≤ `{MAX_CONSECUTIVE_PAIRS}`
    5. **和值** ∈ 動態 `[{analysis.sum_min_dynamic}, {analysis.sum_max_dynamic}]`
       （fallback `[{SUM_MIN}, {SUM_MAX}]`）

    第二區為獨立池（1-8）：以遺漏期數排序、熱號 = gap ≤ mean、auto pick 從熱號隨機抽。
    """)
