from __future__ import annotations

import html
import json
import os

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from openai import APIError, AuthenticationError, RateLimitError

from ai import optimize_resume, result_to_txt
from parser import ResumeParseError, extract_resume_text

load_dotenv()

st.set_page_config(
    page_title="AI 简历一键优化",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed",
)

CUSTOM_CSS = """
<style>
    .stApp { background: linear-gradient(180deg, #eef3ff 0%, #f6f8fb 220px); }
    .block-container { padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1120px; }
    h1 { letter-spacing: -0.03em; }
    .hero-sub { color: #475569; font-size: 0.98rem; margin: -0.4rem 0 1.2rem; line-height: 1.6; }
    .card {
        background: #fff;
        border: 1px solid #e2e8f0;
        border-radius: 16px;
        padding: 1rem 1.1rem;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
        margin-bottom: 0.85rem;
    }
    .card h3 { margin: 0 0 0.55rem; font-size: 1.02rem; }
    .muted { color: #64748b; font-size: 0.88rem; }
    .chip {
        display: inline-block;
        background: #eff6ff;
        color: #1d4ed8;
        border-radius: 999px;
        padding: 0.18rem 0.7rem;
        font-size: 0.78rem;
        margin: 0 0.3rem 0.3rem 0;
        font-weight: 600;
    }
    .issue {
        border-left: 3px solid #2563eb;
        padding: 0.55rem 0.75rem;
        background: #f8fafc;
        border-radius: 0 10px 10px 0;
        margin-bottom: 0.55rem;
    }
    .issue b { color: #0f172a; }
    textarea { font-size: 0.95rem !important; }
    @media (max-width: 768px) {
        .block-container { padding-left: 0.85rem; padding-right: 0.85rem; }
    }
</style>
"""


def main() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    _init_state()

    st.title("AI 简历一键优化")
    st.markdown(
        '<p class="hero-sub">粘贴或上传简历，填写目标岗位。DeepSeek 会针对性润色、提炼亮点、去掉空话，并给出 ATS 建议与扣分整改。</p>',
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.subheader("接口设置")
        default_key = os.getenv("DEEPSEEK_API_KEY", "")
        api_key = st.text_input(
            "DeepSeek API Key",
            value=default_key,
            type="password",
            help="也可在项目根目录 .env 中配置 DEEPSEEK_API_KEY",
        )
        model = st.selectbox("模型", ["deepseek-chat", "deepseek-reasoner"], index=0)
        st.caption("Key 只在本地会话中使用，不会写入仓库。")

    left, right = st.columns((1.05, 1), gap="large")

    with left:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("### 1. 简历内容")
        source = st.radio("输入方式", ["粘贴文本", "上传文件"], horizontal=True, label_visibility="collapsed")
        resume_text = ""
        if source == "上传文件":
            uploaded = st.file_uploader("上传 PDF / DOCX / TXT", type=["pdf", "docx", "txt"])
            if uploaded is not None:
                try:
                    resume_text = extract_resume_text(uploaded.name, uploaded.getvalue())
                    st.session_state["parsed_resume"] = resume_text
                    st.success(f"已提取 {len(resume_text)} 字")
                except ResumeParseError as exc:
                    st.error(str(exc))
            resume_text = st.text_area(
                "提取结果（可再编辑）",
                value=st.session_state.get("parsed_resume", ""),
                height=280,
                placeholder="上传后文本会出现在这里…",
            )
        else:
            resume_text = st.text_area(
                "粘贴简历",
                height=280,
                placeholder="把完整简历粘贴到这里…",
            )
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("### 2. 目标岗位")
        job_title = st.text_input("岗位名称", placeholder="例如：产品经理 / Java 后端开发")
        job_description = st.text_area(
            "岗位 JD（可选，越完整匹配越准）",
            height=140,
            placeholder="粘贴招聘启事中的职责与要求…",
        )
        run = st.button("一键优化", type="primary", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        if run:
            _run_optimize(api_key, model, resume_text, job_title, job_description)

        result = st.session_state.get("result")
        if not result:
            st.markdown(
                '<div class="card"><h3>优化结果</h3>'
                '<p class="muted">完成后，这里会显示润色后的简历、亮点、ATS 建议和整改方案。</p></div>',
                unsafe_allow_html=True,
            )
            return
        _render_result(st.session_state.get("job_title", job_title), result)


def _init_state() -> None:
    st.session_state.setdefault("result", None)
    st.session_state.setdefault("parsed_resume", "")
    st.session_state.setdefault("job_title", "")


def _run_optimize(api_key: str, model: str, resume_text: str, job_title: str, job_description: str) -> None:
    if not api_key.strip():
        st.error("请先在左侧栏填写 DeepSeek API Key。")
        return
    if not resume_text.strip():
        st.error("请粘贴简历，或上传可提取文字的文件。")
        return
    if not job_title.strip():
        st.error("请填写目标岗位名称。")
        return

    with st.spinner("正在针对岗位优化简历…"):
        try:
            result = optimize_resume(
                api_key=api_key.strip(),
                resume=resume_text,
                job_title=job_title,
                job_description=job_description,
                model=model,
            )
        except AuthenticationError:
            st.error("API Key 无效，请到 DeepSeek 开放平台核对。")
            return
        except RateLimitError:
            st.error("请求过于频繁或额度不足，请稍后再试。")
            return
        except APIError as exc:
            st.error(f"DeepSeek 接口出错：{exc}")
            return
        except Exception as exc:
            st.error(str(exc))
            return

    st.session_state["result"] = result
    st.session_state["job_title"] = job_title.strip()
    st.rerun()


def _render_result(job_title: str, result: dict) -> None:
    export_txt = result_to_txt(job_title, result)
    chips = "".join(f'<span class="chip">{html.escape(item)}</span>' for item in (result.get("highlights") or [])[:4])

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 优化后简历")
    if chips:
        st.markdown(chips, unsafe_allow_html=True)
    st.text_area("正文", value=result["optimized_resume"], height=360, label_visibility="collapsed")
    c1, c2 = st.columns(2)
    with c1:
        _copy_button(result["optimized_resume"], "copy-resume")
    with c2:
        st.download_button(
            "导出 TXT",
            data=export_txt.encode("utf-8"),
            file_name=f"resume_{_safe_name(job_title)}.txt",
            mime="text/plain",
            use_container_width=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 工作亮点")
    _bullets(result.get("highlights"))
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 岗位匹配")
    _bullets(result.get("jd_alignment"))
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 空话清理")
    _bullets(result.get("removed_fluff"))
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
            f'{html.escape(item["fix"])}</div>',
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("复制完整报告"):
        st.text_area("完整报告", value=export_txt, height=220, label_visibility="collapsed")
        _copy_button(export_txt, "copy-report")


def _bullets(items) -> None:
    items = [str(x).strip() for x in (items or []) if str(x).strip()]
    if not items:
        st.caption("暂无")
        return
    st.markdown("\n".join(f"- {item}" for item in items))


def _safe_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in name).strip()
    return (cleaned or "optimized")[:40].replace(" ", "_")


def _copy_button(text: str, element_id: str) -> None:
    payload = json.dumps(text, ensure_ascii=False)
    components.html(
        f"""
        <button id="{element_id}" style="
            width:100%;height:42px;border:0;border-radius:10px;
            background:#2563eb;color:#fff;font-size:14px;font-weight:600;cursor:pointer;">
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


if __name__ == "__main__":
    main()
