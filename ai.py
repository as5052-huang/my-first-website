from __future__ import annotations

import json
import os
import re
from typing import Any

from openai import OpenAI

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

SYSTEM_PROMPT = """你是资深招聘顾问兼 ATS（申请人跟踪系统）优化专家。
任务：根据目标岗位、可选行业模板方向与岗位 JD，优化中文简历。
硬性规则：
1. 真实、可核验；不编造经历、公司、学历、证书或量化结果。缺失数据用「待补充：…」。
2. 必须对照 JD 做关键词级匹配：抽出必须项/加分项，标出已覆盖与缺口，并在优化稿中自然融入已有证据对应的关键词（禁止无中生有）。
3. 必须做智能检测：空话套话、职场避雷（歧视信息、精通夸大、主观评价、薪资照片婚姻等）、事实/格式/错别字/时间线错误。
4. 优化稿用中文，分节清晰，适合复制进 Word；原文没有的板块不要硬造。
5. 经历条目优先「动作 + 场景 + 结果」，关键词自然融入。
只输出一个 JSON 对象，不要 Markdown 围栏或其他说明。必须包含以下字段（原有字段不可省略）：
{
  "optimized_resume": "完整优化后简历纯文本",
  "highlights": ["3-8条工作亮点"],
  "jd_alignment": ["针对岗位/JD 的匹配说明，每条一句"],
  "removed_fluff": ["被删改的空话套话及原因"],
  "ats_suggestions": ["ATS 建议"],
  "score_issues": [{"issue": "扣分点", "why": "原因", "fix": "改法"}],
  "jd_match": {
    "score": 0,
    "summary": "一句话总评",
    "matched_keywords": ["JD中已覆盖的关键词"],
    "missing_keywords": ["JD要求但简历证据不足的词"],
    "must_have_gaps": ["硬性缺口及可否用现有经历改写"],
    "rewrite_hints": ["把经历改写成贴合 JD 的具体句子级建议"]
  },
  "detections": {
    "fluff": [{"quote": "原文摘录", "why": "为何是空话", "rewrite": "可落地改写"}],
    "pitfalls": [{"quote": "原文摘录", "risk": "避雷原因", "fix": "处理建议"}],
    "errors": [{"quote": "原文摘录", "type": "错别字/时间矛盾/联系方式/格式等", "fix": "改法"}]
  }
}
score 为 0-100 整数，综合技能覆盖、经历相关度、关键词密度与风险项。
"""


def build_user_prompt(
    resume: str,
    job_title: str,
    job_description: str,
    industry: str = "",
) -> str:
    jd = job_description.strip() or "（未提供 JD，请按该岗位常见要求做匹配分析，并在 missing_keywords 中标明假设来源。）"
    industry_line = industry.strip() or "（未指定，按岗位自行判断行业语境。）"
    return (
        f"目标岗位：{job_title.strip()}\n"
        f"行业方向：{industry_line}\n\n"
        f"岗位 JD：\n{jd}\n\n"
        f"原始简历：\n{resume.strip()}\n"
    )


def optimize_resume(
    *,
    api_key: str,
    resume: str,
    job_title: str,
    job_description: str = "",
    industry: str = "",
    base_url: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    client = OpenAI(
        api_key=api_key,
        base_url=(base_url or os.getenv("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
    )
    used_model = model or os.getenv("DEEPSEEK_MODEL") or DEFAULT_MODEL
    kwargs: dict[str, Any] = {
        "model": used_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_user_prompt(resume, job_title, job_description, industry),
            },
        ],
    }
    if used_model != "deepseek-reasoner":
        kwargs["temperature"] = 0.3
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(**kwargs)
    content = (response.choices[0].message.content or "").strip()
    return parse_result(content)


def parse_result(content: str) -> dict[str, Any]:
    payload = _load_json(content)
    resume = str(payload.get("optimized_resume") or "").strip()
    if not resume:
        raise ValueError("模型未返回优化后的简历正文。")

    return {
        "optimized_resume": resume,
        "highlights": _str_list(payload.get("highlights")),
        "jd_alignment": _str_list(payload.get("jd_alignment")),
        "removed_fluff": _str_list(payload.get("removed_fluff")),
        "ats_suggestions": _str_list(payload.get("ats_suggestions")),
        "score_issues": _issue_list(payload.get("score_issues")),
        "jd_match": _jd_match(payload.get("jd_match")),
        "detections": _detections(payload.get("detections")),
    }


def result_to_txt(
    job_title: str,
    result: dict[str, Any],
    *,
    original_resume: str = "",
    industry: str = "",
    job_description: str = "",
) -> str:
    match = result.get("jd_match") or {}
    det = result.get("detections") or {}
    blocks = [
        "AI 简历优化完整报告",
        f"目标岗位：{job_title}",
        f"行业方向：{industry or '未指定'}",
        f"JD 匹配分：{match.get('score', '—')}",
        f"匹配总评：{match.get('summary') or '—'}",
        "",
        "======== 岗位 JD ========",
        (job_description or "").strip() or "（未提供）",
        "",
        "======== 优化前简历 ========",
        (original_resume or "").strip() or "（未保存原文）",
        "",
        "======== 优化后简历 ========",
        result.get("optimized_resume") or "",
        "",
        "======== 工作亮点 ========",
        _bullets(result.get("highlights")),
        "",
        "======== 岗位匹配说明 ========",
        _bullets(result.get("jd_alignment")),
        "",
        "======== JD 已覆盖关键词 ========",
        _bullets(match.get("matched_keywords")),
        "",
        "======== JD 缺口关键词 ========",
        _bullets(match.get("missing_keywords")),
        "",
        "======== 硬性缺口 ========",
        _bullets(match.get("must_have_gaps")),
        "",
        "======== JD 改写提示 ========",
        _bullets(match.get("rewrite_hints")),
        "",
        "======== 空话清理 ========",
        _bullets(result.get("removed_fluff")),
        "",
        "======== 空话检测 ========",
        _detect_block(det.get("fluff"), quote="quote", extra=("why", "rewrite")),
        "",
        "======== 避雷检测 ========",
        _detect_block(det.get("pitfalls"), quote="quote", extra=("risk", "fix")),
        "",
        "======== 错误点检测 ========",
        _detect_block(det.get("errors"), quote="quote", extra=("type", "fix")),
        "",
        "======== ATS 优化建议 ========",
        _bullets(result.get("ats_suggestions")),
        "",
        "======== 扣分点整改 ========",
        _score_issue_block(result.get("score_issues")),
    ]
    return "\n".join(blocks).strip() + "\n"


def checklist_to_txt(
    job_title: str,
    result: dict[str, Any],
    *,
    industry: str = "",
) -> str:
    match = result.get("jd_match") or {}
    det = result.get("detections") or {}
    blocks = [
        "AI 简历整改清单",
        f"目标岗位：{job_title or '未填写'}",
        f"行业方向：{industry or '未指定'}",
        f"JD 匹配分：{match.get('score', '—')}",
        "",
        "======== 一、优先整改（扣分点） ========",
        _score_issue_block(result.get("score_issues")),
        "",
        "======== 二、空话套话 ========",
        _detect_block(det.get("fluff"), quote="quote", extra=("why", "rewrite")),
        "",
        "======== 三、避雷项 ========",
        _detect_block(det.get("pitfalls"), quote="quote", extra=("risk", "fix")),
        "",
        "======== 四、错误点 ========",
        _detect_block(det.get("errors"), quote="quote", extra=("type", "fix")),
        "",
        "======== 五、ATS 建议 ========",
        _bullets(result.get("ats_suggestions")),
        "",
        "======== 六、JD 缺口与改写 ========",
        "【缺口关键词】",
        _bullets(match.get("missing_keywords")),
        "",
        "【硬性缺口】",
        _bullets(match.get("must_have_gaps")),
        "",
        "【改写提示】",
        _bullets(match.get("rewrite_hints")),
        "",
        "======== 七、空话清理说明 ========",
        _bullets(result.get("removed_fluff")),
    ]
    return "\n".join(blocks).strip() + "\n"


def _score_issue_block(items: Any) -> str:
    rows = [item for item in (items or []) if isinstance(item, dict)]
    if not rows:
        return "（无）"
    lines: list[str] = []
    for idx, item in enumerate(rows, start=1):
        lines.append(f"{idx}. 问题：{item.get('issue') or '—'}")
        lines.append(f"   原因：{item.get('why') or '—'}")
        lines.append(f"   改法：{item.get('fix') or '—'}")
    return "\n".join(lines)


def _load_json(content: str) -> dict[str, Any]:
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", content)
    if not match:
        raise ValueError("模型返回不是有效 JSON，请重试。")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("模型返回格式异常，请重试。")
    return data


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _issue_list(value: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if not isinstance(value, list):
        return items
    for raw in value:
        if not isinstance(raw, dict):
            continue
        issue = str(raw.get("issue") or "").strip()
        if not issue:
            continue
        items.append(
            {
                "issue": issue,
                "why": str(raw.get("why") or "").strip() or "影响 ATS 或招聘官快速筛选。",
                "fix": str(raw.get("fix") or "").strip() or "按岗位关键词改写对应条目，并补充可验证结果。",
            }
        )
    return items


def _jd_match(value: Any) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    score_raw = data.get("score", 0)
    try:
        score = int(float(score_raw))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(100, score))
    return {
        "score": score,
        "summary": str(data.get("summary") or "").strip(),
        "matched_keywords": _str_list(data.get("matched_keywords")),
        "missing_keywords": _str_list(data.get("missing_keywords")),
        "must_have_gaps": _str_list(data.get("must_have_gaps")),
        "rewrite_hints": _str_list(data.get("rewrite_hints")),
    }


def _detections(value: Any) -> dict[str, list[dict[str, str]]]:
    data = value if isinstance(value, dict) else {}
    return {
        "fluff": _detect_items(data.get("fluff"), "why", "rewrite"),
        "pitfalls": _detect_items(data.get("pitfalls"), "risk", "fix"),
        "errors": _detect_items(data.get("errors"), "type", "fix"),
    }


def _detect_items(value: Any, field_a: str, field_b: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if not isinstance(value, list):
        return items
    for raw in value:
        if not isinstance(raw, dict):
            continue
        quote = str(raw.get("quote") or "").strip()
        if not quote:
            continue
        items.append(
            {
                "quote": quote,
                field_a: str(raw.get(field_a) or "").strip(),
                field_b: str(raw.get(field_b) or "").strip(),
            }
        )
    return items


def _bullets(items: Any) -> str:
    lines = [str(item).strip() for item in (items or []) if str(item).strip()]
    if not lines:
        return "（无）"
    return "\n".join(f"- {line}" for line in lines)


_DETECT_LABELS = {
    "why": "原因",
    "rewrite": "改写",
    "risk": "风险",
    "fix": "处理",
    "type": "类型",
}


def _detect_block(items: Any, *, quote: str, extra: tuple[str, str]) -> str:
    rows = [item for item in (items or []) if isinstance(item, dict)]
    if not rows:
        return "（无）"
    lines: list[str] = []
    for idx, item in enumerate(rows, start=1):
        lines.append(f"{idx}. 摘录：{item.get(quote, '')}")
        for key in extra:
            val = str(item.get(key) or "").strip()
            if val:
                label = _DETECT_LABELS.get(key, key)
                lines.append(f"   {label}：{val}")
    return "\n".join(lines)
