"""权限与兑换码模块（纯本地缓存，无数据库）"""

from __future__ import annotations

import hashlib
import json
import logging
import platform
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FREE_TRIAL_COUNT = 1

_STATE_DIR = Path(__file__).resolve().parent / ".state"
_LICENSE_FILE = _STATE_DIR / "license.json"
_USED_CODES_FILE = _STATE_DIR / "used_codes.json"
_CODES_POOL_FILE = Path(__file__).resolve().parent / "codes_pool.json"
_DEVICE_ID_FILE = _STATE_DIR / "device_id.txt"


def _get_stable_device_id() -> str:
    """获取稳定设备 ID（基于机器特征生成，刷新/重启不变）。"""
    try:
        if _DEVICE_ID_FILE.is_file():
            stored = _DEVICE_ID_FILE.read_text(encoding="utf-8").strip()
            if stored:
                return stored
    except OSError:
        pass

    machine_id = "|".join([
        platform.node() or "unknown",
        platform.system() or "unknown",
        platform.machine() or "unknown",
        str(Path(__file__).resolve()),
    ])
    new_id = f"device_{hashlib.md5(machine_id.encode('utf-8')).hexdigest()[:16]}"

    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        _DEVICE_ID_FILE.write_text(new_id, encoding="utf-8")
    except OSError:
        pass
    return new_id


# ─── 兑换码池（启动时加载） ─────────────────────────────

def load_codes_pool() -> dict[str, dict[str, Any]]:
    """从 codes_pool.json 动态加载可用兑换码池。"""
    try:
        if _CODES_POOL_FILE.is_file():
            content = _CODES_POOL_FILE.read_text(encoding="utf-8")
            if content.strip():
                codes = json.loads(content)
                if isinstance(codes, dict):
                    return {
                        str(k).strip().upper(): v
                        for k, v in codes.items()
                        if isinstance(v, dict) and "tier" in v
                    }
                logger.warning("codes_pool.json 根类型应为对象")
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"加载 codes_pool.json 失败：{e}")
    return {}


_CODE_REGISTRY: dict[str, dict[str, Any]] = load_codes_pool()


# ─── 文件读写辅助 ──────────────────────────────────────

def _load_json(path: Path) -> dict[str, Any]:
    """安全加载 JSON，文件不存在或损坏时返回空字典。"""
    try:
        if path.is_file():
            content = path.read_text(encoding="utf-8")
            if content.strip():
                return json.loads(content)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"读取 {path.name} 失败：{e}")
    return {}


def _save_json(path: Path, data: dict[str, Any]) -> bool:
    """原子写入 JSON（先写临时文件再替换）。"""
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError as e:
        logger.error(f"写入 {path.name} 失败：{e}")
        return False


# ─── 设备状态存储（统一 license.json） ──────────────────

def _save_state_for_device(device_id: str, state: dict[str, Any]) -> bool:
    """保存某个设备的状态到 license.json。"""
    if not device_id:
        return _save_json(_LICENSE_FILE, state)
    all_states = _load_json(_LICENSE_FILE)
    state["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    all_states[device_id] = state
    return _save_json(_LICENSE_FILE, all_states)


# ─── 核心 API ──────────────────────────────────────────

def get_license_state(device_id: str = "") -> dict[str, Any]:
    """读取设备权限状态（统一 license.json 存储）。"""
    all_states = _load_json(_LICENSE_FILE)
    return all_states.get(device_id, {}) if device_id else all_states


def check_permission(device_id: str = "") -> tuple[str, str | None, int]:
    """
    检查设备权限状态。
    返回 (tier, expired_msg, remaining_trials)
    """
    state = get_license_state(device_id)
    tier = state.get("tier", "free")
    remaining_trials = state.get("remaining_trials", FREE_TRIAL_COUNT)

    if tier == "monthly":
        days = state.get("days", 30)
        tier_label = "年度会员" if days == 365 else "月度会员"
        expires = state.get("expires_at", "")
        if expires:
            try:
                if datetime.now() > datetime.strptime(expires, "%Y-%m-%d"):
                    state["tier"] = "free"
                    _save_state_for_device(device_id, state)
                    return "free", f"{tier_label}已于 {expires} 到期，已恢复免费权限", remaining_trials
                return tier, None, remaining_trials
            except ValueError:
                pass
        return tier, None, remaining_trials

    if tier == "single":
        return ("free", None, remaining_trials) if state.get("single_used") else (tier, None, remaining_trials)

    return "free", None, remaining_trials


def check_code_valid(code: str) -> tuple[bool, str]:
    """检查兑换码是否有效（仅校验，不执行兑换）。"""
    code = code.strip().upper()
    if not code:
        return False, "请输入兑换码"
    if code not in _CODE_REGISTRY:
        return False, "兑换码无效，请核对后重新输入"
    if code in _load_json(_USED_CODES_FILE):
        return False, "该兑换码已被使用"
    return True, "兑换码有效"


def redeem_code(code: str, device_id: str = "") -> tuple[bool, str]:
    """兑换码激活（全局防重复，按设备隔离存储权限）。"""
    code = code.strip().upper()
    if not code:
        return False, "请输入兑换码"
    if code not in _CODE_REGISTRY:
        return False, "兑换码无效，请核对后重新输入"
    if code in _load_json(_USED_CODES_FILE):
        return False, "此兑换码已被使用过，无法重复兑换"

    # 防止降级
    state = get_license_state(device_id)
    cur_tier, cur_days = state.get("tier", "free"), state.get("days", 0)
    info = _CODE_REGISTRY[code]
    new_tier, new_days = info["tier"], info.get("days", 0)
    if cur_tier == "monthly" and cur_days == 365:
        return False, "您已是年度会员，功能已全部解锁，无需再降级"
    if cur_tier == "monthly" and cur_days == 30 and new_tier == "single":
        return False, "您已是月度会员，功能已全部解锁，无需再兑换单次码"
    if cur_tier == "single" and new_tier == "single":
        return False, "您已是单次体验会员，请兑换月度或年度会员解锁更多功能"

    # 激活新权限
    tier, label, days = info["tier"], info["label"], info.get("days")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_state: dict[str, Any] = {
        "tier": tier,
        "remaining_trials": FREE_TRIAL_COUNT,
        "activated_at": now_str,
        "days": days,
    }
    if tier == "monthly" and days:
        new_state["expires_at"] = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    if tier == "single":
        new_state["single_used"] = False

    if not _save_state_for_device(device_id, new_state):
        return False, "保存权限状态失败，请重试"

    # 标记码为已使用
    used = _load_json(_USED_CODES_FILE)
    used[code] = {"redeemed_at": now_str, "tier": tier, "label": label, "device_id": device_id}
    if not _save_json(_USED_CODES_FILE, used):
        logger.warning(f"兑换码 {code} 已激活，但标记已使用记录失败")

    return True, f"✅ 兑换成功！您已成为「{label}」，请刷新页面查看权限状态"


# 权限等级展示元数据
_TIER_META = {
    "free":    ("免费游客", "🚪"),
    "single":  ("单次体验", "🎫"),
    "monthly": ("月度会员", "🌙"),
}


def _build_status_info(device_id: str = "") -> dict[str, Any]:
    """构建用于 UI 展示的权限状态信息。"""
    tier, expired_msg, remaining_trials = check_permission(device_id)
    state = get_license_state(device_id)

    if tier == "monthly":
        days = state.get("days", 30)
        tier_label, tier_icon = ("年度会员", "📅") if days == 365 else ("月度会员", "📅")
    else:
        tier_label, tier_icon = _TIER_META.get(tier, ("未知权限", "❓"))

    info: dict[str, Any] = {
        "tier": tier,
        "label": tier_label,
        "icon": tier_icon,
        "expired_msg": expired_msg,
        "remaining_trials": remaining_trials,
        "expires_at": state.get("expires_at"),
        "activated_at": state.get("activated_at"),
        "can_optimize": False,
        "can_export": False,
        "can_template": False,
        "lock_reason": None,
    }

    if tier == "monthly":
        info.update(can_optimize=True, can_export=True, can_template=True)
    elif tier == "single":
        if not state.get("single_used"):
            info.update(can_optimize=True)
        else:
            info["lock_reason"] = "单次体验码已使用，请兑换正式会员继续使用"
    elif remaining_trials > 0:
        info["can_optimize"] = True
    else:
        info["lock_reason"] = "免费试用次数已用完，请兑换会员解锁全部功能"

    return info


def consume_single_use(device_id: str = "") -> bool:
    """将单次码标记为已消费。"""
    state = get_license_state(device_id)
    if state.get("tier") == "single" and not state.get("single_used"):
        state["single_used"] = True
        state["single_used_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state["tier"] = "free"
        state["remaining_trials"] = 0
        return _save_state_for_device(device_id, state)
    return True


def decrement_trial(device_id: str = "") -> bool:
    """免费试用次数 -1。"""
    state = get_license_state(device_id)
    state["tier"] = "free"
    state["remaining_trials"] = max(0, state.get("remaining_trials", FREE_TRIAL_COUNT) - 1)
    return _save_state_for_device(device_id, state)


__all__ = [
    "check_permission", "redeem_code", "consume_single_use",
    "decrement_trial", "_build_status_info", "get_license_state",
    "check_code_valid", "FREE_TRIAL_COUNT", "_get_stable_device_id",
]
