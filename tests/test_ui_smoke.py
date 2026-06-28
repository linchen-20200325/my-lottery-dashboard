"""Headless render() smoke test (v6.24 #36 — UI 執行覆蓋).

本專案的兩個 Streamlit view 過去**完全沒有自動測試**(streamlit 未安裝於測試環境)。
本檔注入一個可執行的 streamlit stub,讓 `render()` 在 headless 下實跑端到端,捕捉
import 檢查抓不到的問題:render 路徑的 NameError、重複 widget key
(StreamlitDuplicateElementKey)、整體控制流是否走得通。

**不驗證**視覺版面與真實 rerun/callback 語義(那需人工 `streamlit run`)。但能證明
render() 可端到端執行且 widget-key 契約無衝突 — 對 _view_base/_widgets 重構是有效回歸網。
"""

import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class _SessionState(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)

    def __setattr__(self, k, v):
        self[k] = v


def _build_stub(*, button_returns: bool):
    st = types.ModuleType("streamlit")
    seen_keys: list = []

    def rec(kw):
        k = kw.get("key")
        if k is not None:
            if k in seen_keys:
                raise AssertionError(f"DUPLICATE widget key: {k!r}")
            seen_keys.append(k)

    def radio(label, options, index=0, **kw):
        rec(kw)
        opts = list(options)
        return opts[index] if opts else None

    def selectbox(label, options, index=0, **kw):
        rec(kw)
        opts = list(options)
        return opts[index] if opts else None

    def pills(label, options, default=None, selection_mode="single", **kw):
        rec(kw)
        return default

    def slider(label, lo=None, hi=None, value=None, **kw):
        rec(kw)
        return value if value is not None else lo

    def number_input(label, min_value=None, value=0, **kw):
        rec(kw)
        return value

    def checkbox(label, value=False, **kw):
        rec(kw)
        return value

    def multiselect(label, options, default=None, **kw):
        rec(kw)
        return list(default) if default else []

    def text_area(label, value="", **kw):
        rec(kw)
        return value

    def text_input(label, value="", **kw):
        rec(kw)
        return value

    def file_uploader(label, **kw):
        rec(kw)
        return None

    def button(label, on_click=None, **kw):
        rec(kw)
        return button_returns

    def noop(*a, **k):
        rec(k)
        return None

    def metric(label, value, *a, **k):
        return None

    class _Proxy:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __getattr__(self, name):
            return getattr(st, name)

    def ctx(*a, **k):
        return _Proxy()

    def columns(spec, **k):
        n = spec if isinstance(spec, int) else len(spec)
        return [_Proxy() for _ in range(n)]

    def tabs(labels, **k):
        return [_Proxy() for _ in labels]

    def cache_data(*a, **k):
        def deco(fn):
            return fn
        return deco

    st.radio = radio
    st.selectbox = selectbox
    st.pills = pills
    st.slider = slider
    st.number_input = number_input
    st.checkbox = checkbox
    st.multiselect = multiselect
    st.text_area = text_area
    st.text_input = text_input
    st.file_uploader = file_uploader
    st.button = button
    st.metric = metric
    st.columns = columns
    st.tabs = tabs
    st.expander = ctx
    st.container = ctx
    st.form = ctx
    st.spinner = ctx
    st.cache_data = cache_data
    st.session_state = _SessionState()
    for name in (
        "markdown", "caption", "divider", "subheader", "title", "header",
        "write", "code", "text", "link_button", "error", "warning", "info",
        "success", "dataframe", "table", "json", "image", "latex", "toast",
        "set_page_config", "stop", "rerun", "download_button", "progress",
        "badge",
    ):
        setattr(st, name, noop)
    return st, seen_keys


def _run_view(module_name: str, csv_name: str, *, button_returns: bool) -> list:
    st, keys = _build_stub(button_returns=button_returns)
    saved = sys.modules.get("streamlit")
    sys.modules["streamlit"] = st
    for m in [m for m in sys.modules if m.startswith("src.ui.")]:
        del sys.modules[m]
    try:
        import importlib
        view = importlib.import_module(module_name)
        view.render(REPO / "data" / csv_name)
    finally:
        for m in [m for m in sys.modules if m.startswith("src.ui.")]:
            del sys.modules[m]
        if saved is not None:
            sys.modules["streamlit"] = saved
        else:
            sys.modules.pop("streamlit", None)
    return keys


class TestRenderSmoke(unittest.TestCase):
    """render() 端到端可執行 + 無重複 widget key(go 按鈕 False / True 兩路徑)。"""

    def test_lotto_render_runs(self):
        for btn in (False, True):
            keys = _run_view("src.ui.lotto649_view", "lotto649.csv", button_returns=btn)
            self.assertGreater(len(keys), 10)
            self.assertEqual(len(keys), len(set(keys)), "duplicate widget key")

    def test_powerball_render_runs(self):
        for btn in (False, True):
            keys = _run_view("src.ui.powerball_view", "powerball.csv", button_returns=btn)
            self.assertGreater(len(keys), 10)
            self.assertEqual(len(keys), len(set(keys)), "duplicate widget key")

    def test_widget_keys_stable_across_button_state(self):
        # settings 階梯的 key 集合不應受 go 按鈕狀態影響(防 key 漂移)
        off = set(_run_view("src.ui.lotto649_view", "lotto649.csv", button_returns=False))
        on = set(_run_view("src.ui.lotto649_view", "lotto649.csv", button_returns=True))
        self.assertTrue(off.issubset(on))


if __name__ == "__main__":
    unittest.main()
