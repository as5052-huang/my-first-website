from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

from templates import INDUSTRY_NAMES

STATE_DIR = Path(__file__).resolve().parent / ".state"
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
    # ── 权限状态（从 license.py 的本地缓存读取，此处只保留会话层默认值）──
    "_perm_state_synced",
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
}


def init_and_restore_state() -> None:
    """Fill session_state, then hydrate once from disk after a browser refresh."""
    for key, value in _DEFAULTS.items():
        st.session_state.setdefault(key, value)

    if st.session_state.get("_state_hydrated"):
        return
    st.session_state["_state_hydrated"] = True

    saved = _read_file()
    if not saved:
        return
    for key in PERSIST_KEYS:
        if key not in saved:
            continue
        st.session_state[key] = _sanitize(key, saved[key])


def persist_ui_state() -> None:
    payload = {key: _sanitize(key, st.session_state.get(key, _DEFAULTS[key])) for key in PERSIST_KEYS}
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except OSError:
        pass


def _read_file() -> dict[str, Any]:
    try:
        if not STATE_FILE.is_file():
            return {}
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


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
    return value
