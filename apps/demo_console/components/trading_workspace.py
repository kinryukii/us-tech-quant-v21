"""Local presentation bridge to the existing trading component; no broker calls."""
from __future__ import annotations

import http.client
import json

import streamlit as st

from apps.demo_console.components.visuals import apply_style
from apps.demo_console.i18n import LANGUAGES, get_language, tr


_ORIGIN = "http://127.0.0.1:8766"
_PAGES = {"paper": ("Paper trading", ":material/science:"), "live": ("Live trading", ":material/lock:")}
_START_COMMAND = ('powershell -NoProfile -File '
                  '"D:\\us-tech-quant\\apps\\moomoo_trading_component\\start.ps1" -ManualDataUpdates -WithMoomooBest')


def trading_url(mode: str, *, embed: bool = False, language: str | None = None,
                presentation: bool | None = None) -> str:
    """Fixed local destinations with finite language and display-mode values."""
    if mode not in _PAGES:
        raise ValueError("Unknown trading workspace")
    language = language or get_language()
    language = language if language in LANGUAGES else "en"
    if presentation is None:
        presentation = st.session_state.get("presentation_mode", True)
    view = "research" if presentation is False else "presentation"
    query = f"embed=1&lang={language}&view={view}" if embed else f"lang={language}&view={view}"
    return f"{_ORIGIN}/{mode}?{query}"


def component_health() -> tuple[bool, str]:
    """Bounded, unauthenticated health read; it never queries Moomoo."""
    connection = http.client.HTTPConnection("127.0.0.1", 8766, timeout=1)
    try:
        connection.request("GET", "/api/health", headers={"Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            return False, "交易组件暂不可用，或正在更新。"
        raw = response.read(8193)
        if len(raw) > 8192:
            return False, "本机端口的响应不符合交易组件协议。"
        value = json.loads(raw)
        data = value.get("data") if isinstance(value, dict) else None
        if not isinstance(value, dict) or value.get("ok") is not True or not isinstance(data, dict):
            return False, "本机端口的响应不符合交易组件协议。"
        if (data.get("component") != "moomoo-trading-component"
                or type(data.get("api_version")) is not int or data["api_version"] != 1
                or data.get("live_execution_enabled") is not False
                or data.get("pages") != ["paper", "live"]):
            return False, "交易组件版本或实盘锁定状态未通过检查，请更新后重试。"
        return True, "本机交易组件已连接"
    except (OSError, http.client.HTTPException, ValueError, UnicodeError):
        return False, "尚未连接到本机交易组件。"
    finally:
        connection.close()


def render_trading_links(pages, *, include_research: bool = False) -> None:
    """Use the objects already registered with st.navigation."""
    if include_research:
        # A default callable page has the framework's empty root URL. Use its
        # registered page identity for same-session navigation, avoiding a blank
        # anchor resolving to the current /paper-trading or /live-trading URL.
        if st.button(tr("Research workspace"), icon=":material/monitoring:", type="tertiary",
                     key="trading_research_home", width="content"):
            st.switch_page(pages["research"])
    if "strategies" in pages:
        st.page_link(pages["strategies"], label=tr("Applied strategies") + " · 5", icon=":material/strategy:", width="stretch")
    st.caption(tr("Trading workspace"))
    for mode, (label, icon) in _PAGES.items():
        st.page_link(pages[mode], label=tr(label), icon=icon, width="stretch")


def render_trading_workspace(mode: str, pages=None) -> None:
    """Only execution content; app.py owns brand, navigation and context."""
    if mode not in _PAGES:
        raise ValueError("Unknown trading workspace")
    presentation = st.session_state.get("presentation_mode", True)
    apply_style(presentation=presentation)
    if mode == "live":
        st.title(tr("Live trading"), icon=":material/lock:")
        st.warning(tr("Live trading is not authorized and remains locked. This page does not unlock accounts or send live orders."), icon=":material/lock:")
        return
    st.caption(tr("The original broker simulation and paper accounts record cash, positions and fills separately."))

    ready, message = component_health()
    # Translate presentation messages only; the bounded health protocol stays intact.
    health_labels = {
        "本机交易组件已连接": "Local trading component connected",
        "交易组件暂不可用，或正在更新。": "The trading component is unavailable or updating.",
        "本机端口的响应不符合交易组件协议。": "The local response does not match the trading component protocol.",
        "交易组件版本或实盘锁定状态未通过检查，请更新后重试。": "The component version or live-trading lock could not be verified. Update and try again.",
        "尚未连接到本机交易组件。": "The local trading component is not connected.",
    }
    message = tr(health_labels.get(message, message))
    with st.expander(tr("Daily operation and connection"), expanded=not ready):
        st.write(tr("Update the data once each trading afternoon, review the published target, then start the simulation within its execution window."))
        st.caption(tr("Refresh reads account status. It does not update market history or generate a new strategy target."))
        st.button(tr("Check connection again"), key="trading_connection_paper", icon=":material/refresh:")
        st.caption(tr("Only available on the computer running this DEMO. Component address: 127.0.0.1:8766."))
        if ready:
            st.caption(message)
    if not ready:
        st.info(message)
        with st.container(border=True):
            st.subheader(tr("Start the trading component"))
            st.write(tr("Run this command in local PowerShell, keep the terminal open, then select Check connection again."))
            st.code(_START_COMMAND, language="powershell")
            st.caption(tr("This command starts the console only. It does not automatically start strategies or unlock live trading."))
        return
    # Cross-origin URLs cannot use content-height measurement. Keep the frame
    # within the viewport and let its document own vertical scrolling.
    st.html("""<style>
    [data-testid="stLayoutWrapper"]:has(> .st-key-trading_component_frame) {
        --trading-frame-height:clamp(520px,calc(100dvh - 230px),1050px);
        height:var(--trading-frame-height)!important;
        flex:0 0 var(--trading-frame-height)!important;
        min-height:0!important;
    }
    .st-key-trading_component_frame {height:100%!important;min-height:0!important;overflow:hidden!important}
    @media(max-width:620px){[data-testid="stLayoutWrapper"]:has(> .st-key-trading_component_frame) {
        --trading-frame-height:clamp(440px,calc(100dvh - 230px),850px);
    }}
    </style>""")
    with st.container(key="trading_component_frame", height="stretch", border=False, gap=None):
        st.iframe(trading_url(mode, embed=True, presentation=presentation), height="stretch", width="stretch")
