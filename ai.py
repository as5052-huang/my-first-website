from __future__ import annotations

import json
import os
import re
from typing import Any

from openai import OpenAI

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

SYSTEM_PROMPT = """你是资深招聘顾问兼 ATS（申请人跟踪系统）优化专家。
任务：根据目标岗位与可选 JD，优化中文简历，做到真实、可核验、针对岗位，不编造经历、公司、学历、证书或量化结果。
缺失数据时用「待补充：…」标注，不要虚构数字。
只输出一个 JSON 对象，不要 Markdown 围栏或其他说明。JSON schema：
{
  "optimized_resume": "完整优化后简历纯文本，分节清晰，适合复制进 Word",
  "highlights": ["3-8条可量化或可验证的工作亮点"],
  "jd_alignment": ["针对岗位/JD 的匹配说明，每条一句"],
  "removed_fluff": ["被删改的空话套话及原因"],
  "ats_suggestions": ["ATS 关键词、格式、标题、技能写法建议"],
  "score_issues": [
    {"issue": "扣分点", "why": "为何影响筛选", "fix": "具体改法"}
  ]
}
optimized_resume 必须包含：个人信息（仅保留原文已有字段）、求职意向、专业摘要、核心技能、工作/项目经历、教育背景；原文没有的板块不要硬造。
经历条目优先「动作 + 场景 + 结果」，关键词自然融入，避免堆砌。
"""


def build_user_prompt(resume: str, job_title: str, job_description: str) -> str:
    jd = job_description.strip() or "（未提供 JD，请按常见该岗位要求优化，并在建议中标明假设。）"
    return (
        f"目标岗位：{job_title.strip()}\n\n"
        f"岗位 JD：\n{jd}\n\n"
        f"原始简历：\n{resume.strip()}\n"
    )


def optimize_resume(
    *,
    api_key: str,
    resume: str,
    job_title: str,
    job_description: str = "",
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
            {"role": "user", "content": build_user_prompt(resume, job_title, job_description)},
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
    }


def result_to_txt(job_title: str, result: dict[str, Any]) -> str:
    blocks = [
        f"目标岗位：{job_title}",
        "",
        "======== 优化后简历 ========",
        result["optimized_resume"],
        "",
        "======== 工作亮点 ========",
        _bullets(result.get("highlights")),
        "",
        "======== 岗位匹配 ========",
        _bullets(result.get("jd_alignment")),
        "",
        "======== 空话清理 ========",
        _bullets(result.get("removed_fluff")),
        "",
        "======== ATS 优化建议 ========",
        _bullets(result.get("ats_suggestions")),
        "",
        "======== 扣分点整改 ========",
    ]
    for item in result.get("score_issues") or []:
        blocks.append(f"- 问题：{item['issue']}")
        blocks.append(f"  原因：{item['why']}")
        blocks.append(f"  改法：{item['fix']}")
    return "\n".join(blocks).strip() + "\n"


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


def _bullets(items: Any) -> str:
    lines = [str(item).strip() for item in (items or []) if str(item).strip()]
    if not lines:
        return "（无）"
    return "\n".join(f"- {line}" for line in lines)
