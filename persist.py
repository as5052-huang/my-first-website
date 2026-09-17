from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

from license import _get_stable_device_id
from templates import INDUSTRY_NAMES

STATE_DIR = Path(__file__).resolve().parent / ".state"
# 注意：STATE_FILE 保留作为「匿名/default」设备的临时 fallback 文件，
# 真正的持久化走 ui_session_<device_id>.json（per-device 隔离）。
STATE_FILE = STATE_DIR / "ui_session.json"

PERSIST_KEYS = (
    "resume_draft",
    "job_title_input",
    "job_description_input",
    "industry",
    "source_mode",
    "result",
    "original_resume",
    "job_title",
    "job_description_saved",
    "last_file_id",
    "_perm_info",
)

_DEFAULTS: dict[str, Any] = {
    "resume_draft": "",
    "job_title_input": "",
    "job_description_input": "",
    "industry": INDUSTRY_NAMES[0],
    "source_mode": "粘贴文本",
    "result": None,
    "original_resume": "",
    "job_title": "",
    "job_description_saved": "",
    "last_file_id": "",
    "_perm_state_synced": False,
    "_perm_info": None,
}


def _sanitize_device_id(device_id: str | None) -> str:
    """规范化 device_id 用于文件名。空值时返回空串（走匿名 fallback 文件）。"""
    if not device_id:
        return ""
    # 仅保留字母数字下划线连字符，避免路径注入 & 跨平台文件名校验问题
    return "".join(c for c in str(device_id) if c.isalnum() or c in ("_", "-"))[:64] or ""


def _state_file_for(device_id: str | None) -> Path:
    """根据 device_id 返回持久化文件路径。"""
    safe = _sanitize_device_id(device_id)
    if safe:
        return STATE_DIR / f"ui_session_{safe}.json"
    return STATE_FILE  # 匿名/default fallback


def init_and_restore_state() -> None:
    """Fill session_state, then hydrate from the per-device disk file.

    关键修复：原版的 hydration 用一个全局 ui_session.json，会导致电脑/手机共用同一份缓存。
    现在改成按 device_id（HTTP 请求头 User-Agent 哈希）拆分：
      - ui_session_<device_id>.json  → 每个设备（phone/computer）一份
      - phone UA 含 "Mobile"、computer 不含，天然区分两个设备。
    """
    for key, value in _DEFAULTS.items():
        st.session_state.setdefault(key, value)

    # 防御性清理：移除已废弃的旧字段（防止客户端缓存导致 KeyError）
    for legacy_key in ("_device_id",):
        st.session_state.pop(legacy_key, None)

    # 防御性重置：每次脚本启动都把 _is_optimizing 置为 False。
    # 极端情况下（如上次崩溃、网络中断导致 try/finally 未执行），
    # 浏览器 session_state 可能残留 _is_optimizing=True，
    # 会让按钮永远卡在「优化中…」。这里兜底重置。
    st.session_state["_is_optimizing"] = False

    # ── per-device hydration ─────────────────────────────────
    device_id = _get_stable_device_id()
    safe_id = _sanitize_device_id(device_id)
    hydrated_marker = f"_state_hydrated_{safe_id}"
    if st.session_state.get(hydrated_marker):
        return  # 已为当前 device_id hydrate 过
    st.session_state[hydrated_marker] = True

    saved = _read_file(device_id=device_id)
    if not saved:
        return
    for key in PERSIST_KEYS:
        if key not in saved:
            continue
        st.session_state[key] = _sanitize(key, saved[key])


def persist_ui_state() -> None:
    """把当前 session_state 写到 per-device 文件（基于 HTTP UA 检测）。"""
    device_id = _get_stable_device_id()
    payload = {key: _sanitize(key, st.session_state.get(key, _DEFAULTS[key])) for key in PERSIST_KEYS}
    _write_file(payload, device_id=device_id)


def _read_file(device_id: str | None = None) -> dict[str, Any]:
    """读取 per-device 的 session 文件，不存在则返回 {}。"""
    target = _state_file_for(device_id)
    try:
        if not target.is_file():
            return {}
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_file(payload: dict[str, Any], device_id: str | None = None) -> None:
    """原子写入 per-device session 文件。"""
    target = _state_file_for(device_id)
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)
    except OSError:
        pass


def _sanitize(key: str, value: Any) -> Any:
    if key == "industry":
        name = str(value or "").strip()
        return name if name in INDUSTRY_NAMES else INDUSTRY_NAMES[0]
    if key == "source_mode":
        return value if value in ("粘贴文本", "上传文件") else "粘贴文本"
    if key == "result":
        return value if isinstance(value, dict) else None
    if key in {
        "resume_draft",
        "job_title_input",
        "job_description_input",
        "original_resume",
        "job_title",
        "job_description_saved",
        "last_file_id",
    }:
        return "" if value is None else str(value)
    if key == "_perm_state_synced":
        return bool(value) if value is not None else False
    if key == "_perm_info":
        # 仅持久化最关键的字段（can_optimize / tier / remaining_trials / lock_reason）
        # 其他字段（expired_msg 等）每次从 JSON 文件重新计算，避免长期不一致
        return value if isinstance(value, dict) else None
    return value
