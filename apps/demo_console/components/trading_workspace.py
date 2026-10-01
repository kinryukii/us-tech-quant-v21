"""Local presentation bridge to the existing trading component; no broker calls."""
from __future__ import annotations

import http.client
import json

import streamlit as st

from apps.demo_console.components.visuals import apply_style, sidebar_brand


_ORIGIN = "http://127.0.0.1:8766"
_PAGES = {"paper": ("模拟盘", ":material/science:"), "live": ("实盘", ":material/lock:")}
_START_COMMAND = ('powershell -NoProfile -File '
                  '"D:\\us-tech-quant\\apps\\moomoo_trading_component\\start.ps1"')


def trading_url(mode: str, *, embed: bool = False) -> str:
    """Only the two fixed local destinations may be embedded."""
    if mode not in _PAGES:
        raise ValueError("Unknown trading workspace")
    return f"{_ORIGIN}/{mode}" + ("?embed=1" if embed else "")


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
        st.page_link(pages["research"], label="研究工作台", icon=":material/monitoring:", width="stretch")
    if "strategies" in pages:
        st.page_link(pages["strategies"], label="已应用策略 · 3", icon=":material/strategy:", width="stretch")
    st.caption("交易工作台")
    for mode, (label, icon) in _PAGES.items():
        st.page_link(pages[mode], label=label, icon=icon, width="stretch")


def render_trading_workspace(mode: str, pages) -> None:
    url = trading_url(mode)
    title, icon = _PAGES[mode]
    apply_style(presentation=st.session_state.get("presentation_mode", True))
    with st.sidebar:
        sidebar_brand()
        render_trading_links(pages, include_research=True)
        st.divider()
        st.caption("本机 DEMO · 独立交易工作台")
        st.caption("三策略各自维护模拟现金、持仓与成交；共用冻结模型和信号日期。")

    st.title(title, icon=icon)
    if mode == "live":
        st.warning("实盘未授权，交易已锁定。此页不解锁账户、不发送实盘订单。", icon=":material/lock:")
    else:
        st.caption("三套独立纸面账户，各 10,000 USD · 下一交易日开盘后按当时 MOOMOO 合格盘口执行")
    with st.container(horizontal=True, vertical_alignment="center"):
        st.link_button("独立窗口打开", url, icon=":material/open_in_new:")
        st.button("重新检查连接", key=f"trading_connection_{mode}", icon=":material/refresh:")
    st.caption("仅供运行此 DEMO 的同一台电脑使用，组件地址 127.0.0.1:8766。")

    ready, message = component_health()
    if not ready:
        st.info(message)
        with st.container(border=True):
            st.subheader("启动交易组件")
            st.write("在本机 PowerShell 运行下方命令，保持终端打开，然后点击“重新检查连接”。")
            st.code(_START_COMMAND, language="powershell")
            st.caption("此命令只启动控制台，不会自动启动策略或解锁实盘。")
        return
    st.iframe(trading_url(mode, embed=True), height=1650 if mode == "paper" else 1050, width="stretch")
