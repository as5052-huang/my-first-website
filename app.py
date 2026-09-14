from __future__ import annotations

import html
import json
import logging
import os
import uuid
from datetime import datetime

# 配置日志输出到控制台
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from openai import APIError, AuthenticationError, RateLimitError

from ai import checklist_to_txt, optimize_resume, result_to_txt
from license import (
    _build_status_info, check_permission, consume_single_use,
    decrement_trial, redeem_code, _get_stable_device_id,
)
from parser import ResumeParseError, extract_resume_text
from persist import init_and_restore_state, persist_ui_state
from templates import INDUSTRY_NAMES, TEMPLATES

load_dotenv()

st.set_page_config(
    page_title="AI 简历一键优化",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 全局中文适配：修复中文缺字、中英混排错乱，并适配电脑 / 手机
_ZH_FONT = (
    '"PingFang SC", "Hiragino Sans GB", "Noto Sans SC", '
    '"Microsoft YaHei UI", "Microsoft YaHei", "Source Han Sans SC", '
    "sans-serif"
)
GLOBAL_ZH_CSS = f"""
<style>
    html {{
        -webkit-text-size-adjust: 100%;
        text-size-adjust: 100%;
    }}
    html, body, .stApp, .stAppViewContainer, .main, [data-testid="stAppViewContainer"],
    [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stSidebar"],
    [data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"],
    [data-testid="stMetricValue"], [data-testid="stMetricLabel"],
    .stMarkdown, .stCaption, .stText, .stAlert, .stExpander,
    h1, h2, h3, h4, h5, h6, p, li, label, span, a, button, input, textarea, select,
    .stButton>button, .stDownloadButton>button, .stTextInput input,
    .stTextArea textarea, .stSelectbox, .stRadio, .stTabs,
    [data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"],
    [data-baseweb="tab"], [data-baseweb="modal"] {{
        font-family: {_ZH_FONT} !important;
        font-synthesis: none;
        text-rendering: optimizeLegibility;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }}
    html, body, .stApp {{
        color: #0f172a;
        line-height: 1.75;
        word-break: break-word;
        overflow-wrap: anywhere;
        line-break: auto;
        letter-spacing: 0;
    }}
    h1, h2, h3, h4 {{
        line-height: 1.45 !important;
        font-weight: 700 !important;
        letter-spacing: 0.01em;
    }}
    p, li, label, .stMarkdown p, [data-testid="stWidgetLabel"] {{
        line-height: 1.75 !important;
        word-break: break-word !important;
        overflow-wrap: anywhere !important;
    }}
    code, pre, kbd, samp, .stCode, [data-testid="stCode"] {{
        font-family: {_ZH_FONT} !important;
        white-space: pre-wrap !important;
        word-break: break-word !important;
        line-height: 1.75 !important;
    }}
    .stTextInput input, .stTextArea textarea, [data-baseweb="input"] input,
    [data-baseweb="textarea"] textarea {{
        font-size: 15px !important;
        line-height: 1.75 !important;
        letter-spacing: 0 !important;
    }}
    .material-icons, .material-symbols-rounded, .material-symbols-outlined,
    span[data-testid="stIconMaterial"], span[data-testid="stExpanderToggleIcon"] {{
        font-family: "Material Symbols Rounded", "Material Icons" !important;
        letter-spacing: 0 !important;
        word-break: normal !important;
    }}
    .stApp {{ overflow-x: hidden; }}
    .block-container {{ max-width: 1200px; }}

    /* 桌面端：双栏布局容器 */
    .main-layout {{
        display: flex;
        gap: 1.2rem;
        align-items: flex-start;
    }}
    .main-layout .input-col {{
        flex: 1.05;
        min-width: 0;
    }}
    .main-layout .result-col {{
        flex: 1;
        min-width: 0;
    }}

    /* 移动端（<= 768px）：单栏堆叠 */
    @media (max-width: 768px) {{
        .main-layout {{
            display: block;
        }}
        .main-layout .input-col,
        .main-layout .result-col {{
            width: 100%;
        }}
        .block-container {{
            padding-top: 0.6rem !important;
            padding-bottom: 1.8rem !important;
            padding-left: 0.6rem !important;
            padding-right: 0.6rem !important;
        }}
        h1 {{ font-size: 1.45rem !important; }}
        h2 {{ font-size: 1.18rem !important; }}
        h3 {{ font-size: 1.05rem !important; }}
        .stTextArea textarea {{
            height: 180px !important;
        }}
        [data-testid="stHorizontalBlock"] {{
            flex-wrap: wrap !important;
        }}
        .stButton>button, .stDownloadButton>button {{
            min-height: 46px !important;
            width: 100% !important;
            font-size: 14px !important;
        }}
        [data-testid="stSidebar"] {{
            font-size: 14px;
            background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
            border-right: 3px solid #3b82f6;
        }}
        /* 侧边栏标题样式 */
        .sidebar-header {{
            background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
            color: white;
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1rem;
            text-align: center;
            box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
        }}
        .sidebar-header h2 {{
            margin: 0;
            font-size: 1.1rem;
            font-weight: 600;
        }}
        .sidebar-header p {{
            margin: 0.3rem 0 0;
            font-size: 0.8rem;
            opacity: 0.9;
        }}
        /* 移动端：返回顶端按钮位置 */
        #back-to-top {{
            bottom: 20px !important;
            right: 16px !important;
            width: 42px !important;
            height: 42px !important;
            line-height: 42px !important;
            font-size: 16px !important;
        }}
        .card {{
            padding: 0.8rem 0.75rem 0.7rem !important;
        }}
        /* 指标三栏 -> 单栏 */
        [data-testid="stHorizontalBlock"]:has([data-testid="stMetricValue"]) {{
            flex-direction: column !important;
        }}
        /* 下载按钮四列 -> 两行两列 */
        .download-row {{
            display: grid !important;
            grid-template-columns: 1fr 1fr !important;
            gap: 0.4rem !important;
        }}
        .download-row > div {{
            width: 100% !important;
        }}
        .download-row .stButton > button,
        .download-row .stDownloadButton > button {{
            width: 100% !important;
        }}
        /* 复制按钮独立一行 */
        .copy-row {{
            display: block !important;
        }}
        .copy-row > div {{
            width: 100% !important;
            margin-bottom: 0.4rem !important;
        }}
        .copy-row .stButton > button {{
            width: 100% !important;
        }}
    }}

    @media (min-width: 769px) {{
        .block-container {{
            padding-top: 1rem;
            padding-left: 1.1rem;
            padding-right: 1.1rem;
        }}
        .download-row {{
            display: grid !important;
            grid-template-columns: 1fr 1fr !important;
            gap: 0.5rem !important;
        }}
        .download-row > div {{
            width: 100% !important;
        }}
        .copy-row {{
            display: grid !important;
            grid-template-columns: 1fr 1fr !important;
            gap: 0.5rem !important;
        }}
        .copy-row > div {{
            width: 100% !important;
        }}
    }}
</style>
"""
st.markdown(GLOBAL_ZH_CSS, unsafe_allow_html=True)

CUSTOM_CSS = """
<style>
    .stApp { background: linear-gradient(180deg, #eef3ff 0%, #f6f8fb 240px); }
    .block-container { padding-bottom: 2.4rem; }
    h1, h2, h3 { font-weight: 700; }
    p, li, label, .stMarkdown { line-height: 1.75; word-break: break-word; }
    .hero-sub {
        color: #475569;
        font-size: 0.98rem;
        margin: -0.35rem 0 1rem;
        line-height: 1.75;
    }
    .card {
        background: #fff;
        border: 1px solid #e2e8f0;
        border-radius: 16px;
        padding: 1rem 1.1rem 0.85rem;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
        margin-bottom: 0.85rem;
    }
    .card h3 { margin: 0 0 0.5rem; font-size: 1.05rem; }
    .muted { color: #64748b; font-size: 0.88rem; line-height: 1.7; }
    .chip {
        display: inline-block;
        background: #eff6ff;
        color: #1d4ed8;
        border-radius: 999px;
        padding: 0.18rem 0.7rem;
        font-size: 0.78rem;
        margin: 0 0.3rem 0.3rem 0;
        font-weight: 600;
        line-height: 1.6;
    }
    .chip.warn { background: #fff7ed; color: #c2410c; }
    .chip.ok { background: #ecfdf5; color: #047857; }
    .issue, .detect {
        border-left: 3px solid #2563eb;
        padding: 0.55rem 0.75rem;
        background: #f8fafc;
        border-radius: 0 10px 10px 0;
        margin-bottom: 0.55rem;
        line-height: 1.75;
        word-break: break-word;
    }
    .detect.fluff { border-left-color: #64748b; }
    .detect.pitfall { border-left-color: #ea580c; background: #fff7ed; }
    .detect.error { border-left-color: #dc2626; background: #fef2f2; }
    .quote { color: #334155; }
    .compare {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
    }
    .pane {
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        background: #f8fafc;
        min-width: 0;
    }
    .pane h4 {
        margin: 0;
        padding: 0.55rem 0.8rem;
        font-size: 0.92rem;
        border-bottom: 1px solid #e2e8f0;
        background: #fff;
        border-radius: 12px 12px 0 0;
    }
    .pane pre {
        margin: 0;
        padding: 0.75rem 0.85rem 1rem;
        white-space: pre-wrap;
        word-break: break-word;
        overflow-wrap: anywhere;
        font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
        font-size: 13.5px;
        line-height: 1.8;
        max-height: 520px;
        overflow: auto;
    }
    /* 移动端：对比区 / 指标 / 按钮强制单列 */
    @media (max-width: 900px) {
        .compare { grid-template-columns: 1fr; }
        .pane pre { max-height: 300px; }
        [data-testid="stMetricValue"] { font-size: 1.35rem; }
    }
    div[data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
    button[kind="primary"] { font-weight: 600; }
    /* 引导区 */
    .tips-card {
        background: #fff;
        border: 1px solid #e2e8f0;
        border-radius: 16px;
        padding: 1.1rem 1.25rem 1rem;
        box-shadow: 0 4px 16px rgba(15,23,42,0.05);
        margin-bottom: 0.85rem;
    }
    .tips-card h3 { margin: 0 0 0.6rem; font-size: 1rem; font-weight: 700; }
    .tips-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 0.6rem;
    }
    .tip-item {
        display: flex;
        align-items: flex-start;
        gap: 0.5rem;
        padding: 0.6rem 0.7rem;
        background: #f8fafc;
        border-radius: 10px;
        font-size: 0.85rem;
        line-height: 1.6;
    }
    .tip-item .tip-icon {
        font-size: 1.1rem;
        flex-shrink: 0;
        margin-top: 0.05rem;
    }
    .tip-item .tip-text { color: #334155; }
    .feature-tag {
        display: inline-flex;
        align-items: center;
        gap: 0.3rem;
        background: #eff6ff;
        color: #1d4ed8;
        border-radius: 8px;
        padding: 0.3rem 0.65rem;
        font-size: 0.8rem;
        font-weight: 600;
        margin: 0.2rem 0.2rem 0.2rem 0;
    }
    .feature-tag.green { background: #ecfdf5; color: #047857; }
    .feature-tag.orange { background: #fff7ed; color: #c2410c; }
    .feature-tag.purple { background: #f5f3ff; color: #6d28d9; }
    @media (max-width: 768px) {
        .tips-grid { grid-template-columns: 1fr; }
        .tip-item { padding: 0.5rem 0.6rem; }
    }

    /* ── 权限系统样式 ── */
    .perm-card {
        background: #fff;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 0.9rem 1rem 0.8rem;
        box-shadow: 0 4px 16px rgba(15,23,42,0.06);
        margin-bottom: 0.75rem;
    }
    .perm-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.3rem;
        border-radius: 999px;
        padding: 0.22rem 0.75rem;
        font-size: 0.82rem;
        font-weight: 700;
        margin-bottom: 0.5rem;
    }
    .perm-badge.free    { background:#f1f5f9; color:#475569; }
    .perm-badge.single  { background:#fff7ed; color:#c2410c; }
    .perm-badge.monthly { background:#eff6ff; color:#1d4ed8; }
    .perm-info { font-size: 0.82rem; color: #64748b; line-height: 1.7; }
    .perm-info strong { color: #1e293b; }
    .perm-warn {
        background: #fef3c7;
        border: 1px solid #f59e0b;
        border-radius: 10px;
        padding: 0.5rem 0.7rem;
        font-size: 0.82rem;
        color: #92400e;
        margin-top: 0.4rem;
        line-height: 1.6;
    }
    .lock-overlay {
        background: rgba(241,245,249,0.92);
        border: 2px dashed #cbd5e1;
        border-radius: 16px;
        padding: 2rem 1.5rem;
        text-align: center;
        margin: 1rem 0;
    }
    .lock-overlay .lock-icon { font-size: 2.4rem; margin-bottom: 0.5rem; }
    .lock-overlay h3 { color: #334155; font-size: 1.05rem; margin-bottom: 0.4rem; }
    .lock-overlay p  { color: #64748b; font-size: 0.88rem; line-height: 1.65; }
    .code-input-box {
        border: 1.5px solid #e2e8f0;
        border-radius: 10px;
        padding: 0.6rem 0.75rem;
        margin-top: 0.5rem;
    }
    .code-input-box:focus-within { border-color: #2563eb; }
    /* 兑换码区域 - 始终可见 */
    .redeem-section {
        background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
        border: 2px solid #f59e0b;
        border-radius: 12px;
        padding: 1rem;
        margin: 0.5rem 0;
    }
    .redeem-section .stTextInput input {
        border-color: #f59e0b;
        background: white;
    }
    .redeem-section h4 {
        color: #92400e;
        margin-bottom: 0.5rem;
        font-size: 0.95rem;
    }
    /* 单次/免费用户隐藏高阶功能 */
    .paid-only { display: none; }
    /* 免费用户禁止复制优化报告 */
    .no-copy {
        -webkit-user-select: none;
        -moz-user-select: none;
        -ms-user-select: none;
        user-select: none;
    }
    .no-copy * {
        -webkit-user-select: none;
        -moz-user-select: none;
        -ms-user-select: none;
        user-select: none;
    }
</style>
"""

# ═══════════════════════════════════════════════════════════════
#  权限系统
# ═══════════════════════════════════════════════════════════════

def _render_license_panel(device_id: str = "") -> None:
    """侧边栏权限面板：展示当前权限状态 + 兑换码入口。"""
    info = _build_status_info(device_id)
    tier = info["tier"]
    icon = info["icon"]
    label = info["label"]
    expires_at = info.get("expires_at")
    activated_at = info.get("activated_at")
    trials = info["remaining_trials"]

    # 权限徽章 + 状态行
    badge_cls = {"free": "free", "single": "single",
                 "monthly": "monthly"}.get(tier, "free")
    st.markdown(
        f'<div class="perm-card">'
        f'<div class="perm-badge {badge_cls}">{icon} <b>{label}</b></div>',
        unsafe_allow_html=True,
    )

    # 根据权限类型显示详细信息
    if tier == "free":
        # 检查是否从月度/年度降级
        if info.get("expired_msg"):
            st.markdown(
                f'<div class="perm-warn">⚠️ {info["expired_msg"]}</div>',
                unsafe_allow_html=True,
            )
        if trials > 0:
            st.markdown(
                f'<div class="perm-info">'
                f'🔓 <b>免费试用</b>：剩余 <strong>{trials}</strong> 次'
                f'（每人仅一次）</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="perm-info">'
                f'📭 <b>免费试用</b>：剩余 <strong>0</strong> 次（已用完）</div>',
                unsafe_allow_html=True,
            )
    elif tier == "single":
        st.markdown(
            '<div class="perm-info">🎫 <b>单次体验</b>：剩余 <strong>1</strong> 次，'
            '使用后立即作废</div>',
            unsafe_allow_html=True,
        )
        if activated_at:
            st.markdown(
                f'<div class="perm-info" style="font-size:0.82rem;color:#6b7280;">'
                f'📅 激活时间：{activated_at}</div>',
                unsafe_allow_html=True,
            )
    elif tier == "monthly":
        left = ""
        if expires_at:
            try:
                days_left = (datetime.strptime(expires_at, "%Y-%m-%d") - datetime.now()).days + 1
                left = f'，剩余 <strong>{max(0, days_left)}</strong> 天'
            except ValueError:
                pass
        st.markdown(
            f'<div class="perm-info">{info["icon"]} <b>{info["label"]}</b>{left}，不限次使用全部功能</div>',
            unsafe_allow_html=True,
        )
        if expires_at:
            st.markdown(
                f'<div class="perm-info" style="font-size:0.82rem;color:#6b7280;">'
                f'📅 到期时间：{expires_at}</div>',
                unsafe_allow_html=True,
            )
        if activated_at:
            st.markdown(
                f'<div class="perm-info" style="font-size:0.82rem;color:#6b7280;">'
                f'📅 激活时间：{activated_at}</div>',
                unsafe_allow_html=True,
            )

    # ── 兑换码处理回调 ──────────────────────────────────────
    def _do_redeem() -> None:
        code = st.session_state.get("_code_input", "").strip()
        if not code:
            st.session_state["_redeem_error"] = "请先输入兑换码"
            st.session_state["_redeem_success"] = ""
            return
        device_id = _get_stable_device_id()
        ok, msg = redeem_code(code, device_id)
        if ok:
            st.session_state["_redeem_error"] = ""
            st.session_state["_redeem_success"] = msg
            _sync_perm_to_session(device_id)
        else:
            st.session_state["_redeem_error"] = msg
            st.session_state["_redeem_success"] = ""

    # ── 套餐升级入口（仅月度/年度会员隐藏）──────────────────────
    if tier not in ("monthly",):
        upgrade_tips = {
            "free": "💡 升级月度/年度会员，解锁不限次使用、导出、模板库",
            "single": "💡 升级月度/年度会员，解锁更多功能",
            "monthly": "💡 续费或升级年度会员更多优惠，敬请期待",
        }
        placeholder = "请输入兑换码"
        if tier == "free" and trials == 0:
            placeholder = "请输入兑换码"
        st.markdown(
            f'<div class="redeem-section">'
            f'<h4>✨ 套餐升级</h4>'
            f'<p style="font-size:0.85rem;color:#6b7280;margin:0.5rem 0;">{upgrade_tips.get(tier, "")}</p>',
            unsafe_allow_html=True,
        )
        redeem_col1, redeem_col2 = st.columns([1, 1])
        with redeem_col1:
            st.text_input(
                "输入兑换码",
                placeholder=placeholder,
                key="_code_input",
            )
        with redeem_col2:
            st.button("立即升级", use_container_width=True, type="primary", on_click=_do_redeem)
        
        st.markdown('</div>', unsafe_allow_html=True)
        st.button("🔄 刷新权限状态", use_container_width=True, on_click=_sync_perm_to_session)

        # ── 兑换结果反馈（rerun 后仍能显示一次）─────────────────
        if st.session_state.get("_redeem_success"):
            st.success(st.session_state.pop("_redeem_success", ""))
            st.rerun()
        elif st.session_state.get("_redeem_error"):
            st.error(st.session_state.pop("_redeem_error", ""))

    st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("📋 权益说明", expanded=False):
        st.markdown(
            "| 权限 | 功能 | 单次码 | 月度30天 | 年度365天 |\n"
            "|------|------|--------|---------|-----------|\n"
            "| 简历优化 | ✅ 核心功能 | ✅ 限1次 | ✅ 不限次 | ✅ 不限次 |\n"
            "| 优化报告导出 | TXT 完整报告 | ❌ | ✅ | ✅ |\n"
            "| 整改清单导出 | TXT 整改清单 | ❌ | ✅ | ✅ |\n"
            "| 多行业模板库 | 12 个行业模板 | ❌ | ✅ | ✅ |\n"
            "| 免费试用 | 每人1次 | — | — | — |",
        )



def _sync_perm_to_session(device_id: str = "") -> None:
    """将权限状态同步到 session_state（用于 UI 渲染判断）。"""
    st.session_state["_perm_info"] = _build_status_info(device_id)
    st.session_state["_perm_state_synced"] = True


def _do_expand_sidebar() -> None:
    """点击升级按钮时展开侧边栏。"""
    st.session_state["_expand_sidebar"] = True


def _post_optimize_permission(tier: str, prev_trials: int, device_id: str = "") -> None:
    """优化成功后扣减权限（按设备隔离）。"""
    if tier == "free":
        if decrement_trial(device_id):
            logging.info(f"免费试用次数已扣减（原剩余 {prev_trials} 次，设备: {device_id}）")
        else:
            logging.error("免费试用次数扣减失败，请检查文件权限")
    elif tier == "single":
        consume_single_use(device_id)



# ═══════════════════════════════════════════════════════════════
#  页面主内容
# ═══════════════════════════════════════════════════════════════

def _render_hero_tips() -> None:
    """页面顶部功能简介 + 使用小贴士，引导用户快速上手。"""
    # 功能亮点标签行
    st.markdown(
        '<div class="tips-card">'
        '<h3>✨ 这个工具能做什么</h3>'
        '<div>',
        unsafe_allow_html=True,
    )
    cols = st.columns(3)
    with cols[0]:
        st.markdown(
            '<span class="feature-tag">🔍 <b>JD 精准匹配</b></span>'
            '<span class="feature-tag green">✅ <b>ATS 友好</b></span>',
            unsafe_allow_html=True,
        )
    with cols[1]:
        st.markdown(
            '<span class="feature-tag orange">⚠️ <b>空话/避雷检测</b></span>'
            '<span class="feature-tag purple">📊 <b>关键词缺口</b></span>',
            unsafe_allow_html=True,
        )
    with cols[2]:
        st.markdown(
            '<span class="feature-tag">💡 <b>亮点提炼</b></span>'
            '<span class="feature-tag green">📥 <b>TXT 导出</b></span>',
            unsafe_allow_html=True,
        )
    st.markdown('</div>', unsafe_allow_html=True)

    # 使用步骤（可折叠，减少干扰）
    with st.expander("📋 使用小贴士 / 新手必读", expanded=False):
        st.markdown(
            '<div class="tips-grid">'
            '<div class="tip-item">'
            '<span class="tip-icon">1️⃣</span>'
            '<span class="tip-text"><b>粘贴或上传简历</b>（支持 PDF / Word / TXT），上传后文字会自动提取到文本框，可手动修改。</span>'
            '</div>'
            '<div class="tip-item">'
            '<span class="tip-icon">2️⃣</span>'
            '<span class="tip-text"><b>填写目标岗位</b>和对应的 JD（招聘要求），JD 越完整匹配越准确。</span>'
            '</div>'
            '<div class="tip-item">'
            '<span class="tip-icon">3️⃣</span>'
            '<span class="tip-text"><b>点击「一键优化」</b>，等待 AI 分析，通常 10–30 秒内完成。</span>'
            '</div>'
            '<div class="tip-item">'
            '<span class="tip-icon">4️⃣</span>'
            '<span class="tip-text"><b>查看优化前后对比</b>，重点关注「缺口关键词」「避雷项」和「扣分点整改」。</span>'
            '</div>'
            '<div class="tip-item">'
            '<span class="tip-icon">5️⃣</span>'
            '<span class="tip-text"><b>复制或导出一键完成</b>，支持导出「优化报告 TXT」和「整改清单 TXT」。</span>'
            '</div>'
            '<div class="tip-item">'
            '<span class="tip-icon">💡</span>'
            '<span class="tip-text"><b>模板库</b>在左侧边栏，从中选择行业模板填入后再修改，可节省大量时间。</span>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        # 注意事项
        st.markdown("**⚠️ 注意事项**")
        st.markdown(
            "- **简历内容保密**：所有处理均在本地完成，数据不会上传到任何第三方服务器。"
            "  API 调用仅用于完成分析。"
            "\n- **PDF 扫描件**：请确保 PDF 可复制文字，扫描件请先 OCR 识别后再粘贴。"
            "\n- **结果仅供参考**：AI 生成内容建议人工核实，尤其是数据、项目经历等关键信息。"
        )
    st.markdown('</div>', unsafe_allow_html=True)


def main() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    init_and_restore_state()

    # 设备 ID 基于机器特征生成，刷新/重启不变
    device_id = _get_stable_device_id()
    _sync_perm_to_session(device_id)

    # 处理侧边栏展开请求
    if st.session_state.pop("_expand_sidebar", False):
        st.markdown(
            '<script>'
            'setTimeout(() => {'
            '  const sidebar = window.parent.document.querySelector("[data-testid=\"stSidebar\"]");'
            '  if (sidebar) sidebar.classList.add("expanded");'
            '  const toggle = window.parent.document.querySelector("[data-testid=\"stSidebarCollapsedControl\"] button");'
            '  if (toggle) toggle.click();'
            '}, 100);'
            '</script>',
            unsafe_allow_html=True,
        )

    st.title("📄 AI 简历一键优化")
    _render_hero_tips()

    # 获取当前会员状态（按设备隔离）
    perm_info = st.session_state.get("_perm_info") or {}
    if not perm_info:
        perm_info = _build_status_info(device_id)
        st.session_state["_perm_info"] = perm_info
    tier = perm_info["tier"]

    with st.sidebar:
        # 侧边栏标题（会员状态在下方权限面板显示，避免重复）
        st.markdown(
            '<div class="sidebar-header">'
            '<h2>🎫 会员中心</h2>'
            '</div>',
            unsafe_allow_html=True,
        )
        _render_license_panel(device_id)
        _render_template_library()

    # PC 端双栏布局，移动端（CSS）自动切换为单栏
    st.markdown('<div class="main-layout">', unsafe_allow_html=True)
    with st.container():
        st.markdown('<div class="input-col">', unsafe_allow_html=True)
        _render_resume_input()
        _render_job_input()
        st.markdown('</div>', unsafe_allow_html=True)
    run = st.session_state.pop("_run_clicked", False)
    with st.container():
        st.markdown('<div class="result-col">', unsafe_allow_html=True)
        if run:
            _run_optimize(
                st.session_state.get("resume_draft", ""),
                st.session_state.get("job_title_input", ""),
                st.session_state.get("job_description_input", ""),
                st.session_state.get("industry", INDUSTRY_NAMES[0]),
            )
        persist_ui_state()
        result = st.session_state.get("result")
        if not result:
            st.markdown(
                '<div class="card"><h3>优化结果</h3>'
                '<p class="muted">完成后将显示：双栏对比、JD 匹配分、智能检测、'
                "亮点、ATS 建议、扣分整改，以及全部结果 TXT 导出。刷新页面会保留当前输入与结果。</p></div>",
                unsafe_allow_html=True,
            )
        else:
            _render_result()
        st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # 优化完成后弹出成功提示（仅显示一次）
    if st.session_state.get("result") and st.session_state.pop("_just_optimized", False):
        st.toast("✅ 简历优化完成！向下滚动查看结果 👇", icon="✅")

    # 浮动「返回顶端」按钮
    _back_to_top_button()


def _render_template_library() -> None:
    info = st.session_state.get("_perm_info") or _build_status_info(_get_stable_device_id())
    if not info.get("can_template"):
        st.subheader("🔒 多行业模板库")
        st.markdown(
            '<div style="font-size:0.85rem;color:#64748b;line-height:1.7;padding:0.5rem;'
            'background:#fff7ed;border-radius:8px;border:1px solid #fed7aa;">'
            '此功能需要 <b>月度会员</b> 或 <b>年度会员</b> 才能使用。<br>'
            '💡 请在侧边栏上方「🎫 兑换会员」处输入兑换码解锁。'
            '</div>',
            unsafe_allow_html=True,
        )
        return
    st.subheader("多行业模板库")
    industry = st.selectbox("行业方向", INDUSTRY_NAMES, key="industry")
    st.caption("填入后可直接改【】占位符，再点一键优化。不会覆盖你已优化的结果，除非重新生成。")
    if st.button("填入编辑器", use_container_width=True):
        st.session_state["resume_draft"] = TEMPLATES[industry]
        st.session_state["source_mode"] = "粘贴文本"
        persist_ui_state()
        st.toast(f"✅ 已填入「{industry}」模板，请按需修改后再优化", icon="✅")
        st.rerun()
    with st.expander("预览模板结构", expanded=False):
        st.text(TEMPLATES[industry])


def _render_resume_input() -> None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 1. 简历内容")
    source = st.radio(
        "输入方式",
        ["粘贴文本", "上传文件"],
        horizontal=True,
        key="source_mode",
    )
    if source == "上传文件":
        uploaded = st.file_uploader(
            "上传 PDF / DOCX / DOC / RTF / TXT",
            type=["pdf", "docx", "doc", "rtf", "txt"],
            help="优先上传可复制文字的 PDF 或 Word 另存的 .docx。扫描件请先识别文字或直接粘贴。",
        )
        if uploaded is not None:
            file_id = f"{uploaded.name}-{uploaded.size}"
            if st.session_state.get("last_file_id") != file_id:
                try:
                    text = extract_resume_text(uploaded.name, uploaded.getvalue())
                    st.session_state["resume_draft"] = text
                    st.session_state["last_file_id"] = file_id
                    st.toast(f"✅ 已提取 {len(text)} 字，可直接编辑后再优化", icon="✅")
                except ResumeParseError as exc:
                    st.error(str(exc))
        st.text_area(
            "提取结果（可再编辑）",
            key="resume_draft",
            height=280,
            placeholder="上传后文本会出现在这里…",
        )
    else:
        st.text_area(
            "粘贴简历",
            key="resume_draft",
            height=280,
            placeholder="把完整简历粘贴到这里，或从左侧模板库填入…",
        )
    st.markdown("</div>", unsafe_allow_html=True)


def _render_job_input() -> None:
    info = st.session_state.get("_perm_info") or _build_status_info(_get_stable_device_id())
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 2. 目标岗位")
    st.text_input("岗位名称", placeholder="例如：产品经理 / Java 后端开发", key="job_title_input")
    st.text_area(
        "岗位 JD（建议粘贴，匹配更准）",
        height=150,
        placeholder="粘贴职责、任职要求、加分项… 越完整，关键词匹配越准。",
        key="job_description_input",
    )
    if info.get("can_optimize"):
        st.button("一键优化", type="primary", use_container_width=True,
                  on_click=lambda: st.session_state.update({"_run_clicked": True}))
    else:
        st.button("🔒 一键优化（功能已锁定）", disabled=True, use_container_width=True)
        st.markdown(
            '<div class="lock-overlay">'
            '<div class="lock-icon">🔒</div>'
            '<h3>核心功能已锁定</h3>'
            '<p>免费试用次数已用完，请在左侧边栏「🎫 兑换会员」处输入兑换码解锁全部功能<br>'
            '💡 单次体验码仅可使用1次，导出/模板等功能需月度或年度会员</p>'
            '</div>',
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def _run_optimize(
    resume_text: str,
    job_title: str,
    job_description: str,
    industry: str,
) -> None:
    # ── 参数校验（原有逻辑）─────────────────────────────────
    api_key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        st.error("未配置 DEEPSEEK_API_KEY，请在项目根目录 .env 中填写后重启应用。")
        return
    if not resume_text.strip():
        st.error("请粘贴简历，或上传可提取文字的文件，也可使用行业模板。")
        return
    if not job_title.strip():
        st.error("请填写目标岗位名称。")
        return

    # ── 权限校验（复用 UI 状态，避免重复检查）──────────────────
    device_id = _get_stable_device_id()
    perm_info = st.session_state.get("_perm_info") or {}
    if not perm_info:
        perm_info = _build_status_info(device_id)
        st.session_state["_perm_info"] = perm_info
    tier = perm_info["tier"]
    remaining = perm_info["remaining_trials"]
    expired_msg = perm_info.get("expired_msg")

    # 免费用户且无剩余次数
    if tier == "free" and remaining <= 0:
        st.error("免费试用次数已用完，请先兑换会员再继续使用。")
        st.session_state["_expand_sidebar"] = True
        return

    # 月度/年度会员已到期
    if expired_msg:
        st.warning(expired_msg)

    with st.spinner("⏳ 正在分析简历 + JD 匹配 + 智能检测，请稍候（通常 10–30 秒）…"):
        try:
            result = optimize_resume(
                api_key=api_key,
                resume=resume_text,
                job_title=job_title,
                job_description=job_description,
                industry=industry,
                model=os.getenv("DEEPSEEK_MODEL") or None,
            )
        except AuthenticationError:
            st.error("API Key 无效，请到 DeepSeek 开放平台核对。")
            return
        except RateLimitError:
            st.error("请求过于频繁或额度不足，请稍后再试。")
            return
        except APIError as exc:
            msg = str(exc)
            if "402" in msg or "Insufficient Balance" in msg or getattr(exc, "status_code", None) == 402:
                st.error("API 账户余额不足，请前往 DeepSeek 开放平台充值。")
            else:
                st.error(f"DeepSeek 接口出错：{exc}")
            return
        except Exception as exc:
            st.error(f"发生未知错误：{exc}")
            return

    st.session_state["result"] = result
    st.session_state["job_title"] = job_title.strip()
    st.session_state["original_resume"] = resume_text.strip()
    st.session_state["job_description_saved"] = job_description.strip()
    st.session_state["export_stamp"] = datetime.now().strftime("%Y%m%d")
    st.session_state["_just_optimized"] = True
    # ── 权限后处理（按设备隔离）───────────────────────────────
    _post_optimize_permission(tier, remaining, device_id)
    persist_ui_state()
    # 同步权限状态到 UI
    _sync_perm_to_session(device_id)


def _render_result() -> None:
    result = st.session_state.get("result")
    perm_info = st.session_state.get("_perm_info") or {}
    if not perm_info:
        perm_info = _build_status_info(_get_stable_device_id())
        st.session_state["_perm_info"] = perm_info
    can_export = perm_info.get("can_export", False)
    tier = perm_info.get("tier", "free")
    job_title = st.session_state.get("job_title", "")
    original = st.session_state.get("original_resume", "")
    industry = st.session_state.get("industry", "")
    jd = st.session_state.get("job_description_saved", "")
    export_txt = result_to_txt(
        job_title,
        result,
        original_resume=original,
        industry=industry,
        job_description=jd,
    )
    checklist_txt = checklist_to_txt(job_title, result, industry=industry)
    stamp = st.session_state.get("export_stamp") or datetime.now().strftime("%Y%m%d")
    report_name = _export_filename("优化报告", job_title, stamp)
    checklist_name = _export_filename("整改清单", job_title, stamp)
    match = result.get("jd_match") or {}
    chips = "".join(
        f'<span class="chip">{html.escape(item)}</span>'
        for item in (result.get("highlights") or [])[:4]
    )

    # 免费用户禁止复制优化报告
    if not can_export:
        st.markdown('<div class="no-copy">', unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 优化前后对比")
    st.markdown(_compare_html(original, result["optimized_resume"]), unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    m1, m2, m3 = st.columns(3)
    m1.metric("JD 匹配分", f"{match.get('score', 0)}")
    m2.metric("已覆盖关键词", f"{len(match.get('matched_keywords') or [])}")
    m3.metric("缺口关键词", f"{len(match.get('missing_keywords') or [])}")
    if match.get("summary"):
        st.caption(match["summary"])

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 优化后简历")
    if chips:
        st.markdown(chips, unsafe_allow_html=True)
    st.text_area("正文", value=result["optimized_resume"], height=300, label_visibility="collapsed")
    st.markdown('<div class="copy-row">', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        _copy_button(result["optimized_resume"], "copy-resume")
    with c2:
        if can_export:
            st.download_button(
                "导出优化报告 TXT",
                data=export_txt.encode("utf-8-sig"),
                file_name=report_name,
                mime="text/plain",
                use_container_width=True,
                help="含优化前/后、JD 匹配、检测、ATS、扣分整改等全部板块",
            )
        else:
            st.download_button(
                "🔒 导出优化报告 TXT（需会员）",
                data="",
                file_name="need_vip.txt",
                disabled=True,
                use_container_width=True,
            )
    st.markdown('</div>', unsafe_allow_html=True)
    # 整改清单单独下载
    st.markdown('<div class="download-row">', unsafe_allow_html=True)
    c3, c4 = st.columns(2)
    with c3:
        if can_export:
            st.download_button(
                "导出整改清单 TXT",
                data=checklist_txt.encode("utf-8-sig"),
                file_name=checklist_name,
                mime="text/plain",
                use_container_width=True,
                help="含扣分点、空话、避雷、错误、ATS 建议、JD 缺口等整改指引",
            )
        else:
            st.download_button(
                "🔒 整改清单 TXT（需会员）",
                data="",
                file_name="need_vip.txt",
                disabled=True,
                use_container_width=True,
            )
    # 只在功能锁定时在c4列显示升级按钮
    with c4:
        if not can_export:
            st.button(
                "🎫 升级解锁全部功能",
                use_container_width=True,
                type="primary",
                on_click=_do_expand_sidebar,
            )
        else:
            st.button("🎫 功能已解锁", disabled=True, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### JD 精准匹配")
    st.markdown("**已覆盖**")
    _keyword_chips(match.get("matched_keywords"), kind="ok")
    st.markdown("**待补齐**")
    _keyword_chips(match.get("missing_keywords"), kind="warn")
    st.markdown("**硬性缺口**")
    _bullets(match.get("must_have_gaps"))
    st.markdown("**改写提示**")
    _bullets(match.get("rewrite_hints"))
    st.markdown("**岗位匹配说明**")
    _bullets(result.get("jd_alignment"))
    st.markdown("</div>", unsafe_allow_html=True)

    detections = result.get("detections") or {}
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 空话 / 避雷 / 错误检测")
    t1, t2, t3 = st.tabs(["空话套话", "避雷项", "错误点"])
    with t1:
        _render_detects(detections.get("fluff"), kind="fluff", a="why", b="rewrite", la="原因", lb="改写")
        st.markdown("**模型清理说明**")
        _bullets(result.get("removed_fluff"))
    with t2:
        _render_detects(detections.get("pitfalls"), kind="pitfall", a="risk", b="fix", la="风险", lb="处理")
    with t3:
        _render_detects(detections.get("errors"), kind="error", a="type", b="fix", la="类型", lb="改法")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 工作亮点")
    _bullets(result.get("highlights"))
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### ATS 优化建议")
    _bullets(result.get("ats_suggestions"))
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 扣分点整改")
    issues = result.get("score_issues") or []
    if not issues:
        st.caption("未检出明显扣分项。")
    for item in issues:
        st.markdown(
            f'<div class="issue"><b>{html.escape(item["issue"])}</b><br>'
            f'<span class="muted">{html.escape(item["why"])}</span><br>'
            f"{html.escape(item['fix'])}</div>",
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    if can_export:
        with st.expander("复制完整报告"):
            st.text_area("完整报告", value=export_txt, height=240, label_visibility="collapsed")
            _copy_button(export_txt, "copy-report")
    else:
        with st.expander("🔒 完整报告（需会员）"):
            st.caption("完整报告包含优化前后、JD 匹配、检测、ATS 建议、扣分整改等全部内容。")
            st.caption("请兑换月度或年度会员解锁此功能。")

    # 免费用户结束防复制区域
    if not can_export:
        st.markdown('</div>', unsafe_allow_html=True)


def _compare_html(before: str, after: str) -> str:
    left = html.escape(before or "（无原文）")
    right = html.escape(after or "")
    return (
        '<div class="compare">'
        f'<div class="pane"><h4>优化前</h4><pre>{left}</pre></div>'
        f'<div class="pane"><h4>优化后</h4><pre>{right}</pre></div>'
        "</div>"
    )


def _keyword_chips(items, *, kind: str) -> None:
    items = [str(x).strip() for x in (items or []) if str(x).strip()]
    if not items:
        st.caption("暂无")
        return
    chips = "".join(f'<span class="chip {kind}">{html.escape(item)}</span>' for item in items)
    st.markdown(chips, unsafe_allow_html=True)


def _render_detects(items, *, kind: str, a: str, b: str, la: str, lb: str) -> None:
    rows = [x for x in (items or []) if isinstance(x, dict)]
    if not rows:
        st.caption("未检出该项。")
        return
    for item in rows:
        st.markdown(
            f'<div class="detect {kind}"><span class="quote">「{html.escape(item.get("quote", ""))}」</span><br>'
            f"<b>{html.escape(la)}：</b>{html.escape(str(item.get(a) or '—'))}<br>"
            f"<b>{html.escape(lb)}：</b>{html.escape(str(item.get(b) or '—'))}</div>",
            unsafe_allow_html=True,
        )


def _bullets(items) -> None:
    items = [str(x).strip() for x in (items or []) if str(x).strip()]
    if not items:
        st.caption("暂无")
        return
    st.markdown("\n".join(f"- {item}" for item in items))


def _export_filename(prefix: str, job_title: str, stamp: str) -> str:
    """生成规范的文件名：{前缀}_{岗位}_{日期}.txt"""
    safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in job_title).strip() or "optimized"
    safe = safe[:40].replace(" ", "_")
    return f"{prefix}_{safe}_{stamp}.txt"


def _copy_button(text: str, element_id: str) -> None:
    payload = json.dumps(text, ensure_ascii=False)
    components.html(
        f"""
        <button id="{element_id}" style="
            width:100%;height:42px;border:0;border-radius:10px;
            background:#2563eb;color:#fff;font-size:14px;font-weight:600;cursor:pointer;
            font-family:Microsoft YaHei,PingFang SC,sans-serif;">
            复制内容
        </button>
        <script>
          const btn = document.getElementById("{element_id}");
          const text = {payload};
          btn.addEventListener("click", async () => {{
            try {{
              await navigator.clipboard.writeText(text);
              btn.innerText = "已复制";
              setTimeout(() => btn.innerText = "复制内容", 1600);
            }} catch (e) {{
              btn.innerText = "复制失败，请手动全选";
            }}
          }});
        </script>
        """,
        height=52,
    )


def _back_to_top_button() -> None:
    """页面底部浮动「返回顶端」按钮，PC / 手机均适用。"""
    components.html(
        """
        <a id="back-to-top" href="javascript:void(0)" style="
            display: block;
            position: fixed;
            bottom: 28px;
            right: 28px;
            width: 46px;
            height: 46px;
            background: #2563eb;
            color: #fff;
            border-radius: 50%;
            text-align: center;
            line-height: 46px;
            font-size: 18px;
            text-decoration: none;
            box-shadow: 0 4px 16px rgba(37,99,235,0.4);
            z-index: 9999;
            font-family: 'PingFang SC','Microsoft YaHei',sans-serif;
            font-weight: 700;
            letter-spacing: 0;
            transition: background 0.2s, transform 0.15s;
        " title="返回顶端"
        onclick="
            // 尝试多个滚动目标，兼容 Streamlit 不同渲染环境
            var targets = [
                document.documentElement,
                document.body,
                window.parent.document.documentElement,
                window.parent.document.body
            ];
            for (var i = 0; i < targets.length; i++) {
                targets[i].scrollTo({top: 0, behavior: 'smooth'});
            }
            return false;
        "
        onmouseover="this.style.background='#1d4ed8';this.style.transform='scale(1.08)';"
        onmouseout="this.style.background='#2563eb';this.style.transform='scale(1)';"
        >↑</a>
        """,
        height=0,
    )


if __name__ == "__main__":
    main()
