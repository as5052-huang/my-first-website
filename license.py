"""
权限与兑换码模块（无数据库，纯本地缓存）
─────────────────────────────────────────
码表存储在 codes_pool.json（本地文件），已使用码记录在 .state/used_codes.json。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# 日志配置
logger = logging.getLogger(__name__)

# 免费试用次数（全局）
FREE_TRIAL_COUNT = 1

# ─────────────────────────────────────────
# 1. 本地缓存路径
# ─────────────────────────────────────────
_STATE_DIR = Path(__file__).resolve().parent / ".state"
_LICENSE_FILE = _STATE_DIR / "license.json"
_USED_CODES_FILE = _STATE_DIR / "used_codes.json"
_CODES_POOL_FILE = Path(__file__).resolve().parent / "codes_pool.json"


def _get_device_license_file(device_id: str) -> Path:
    """根据设备 ID 获取对应的 license 文件路径。"""
    safe_id = "".join(c if c.isalnum() else "_" for c in device_id)
    return _STATE_DIR / f"license_{safe_id}.json"


# ─────────────────────────────────────────
# 2. 兑换码池（动态加载）
# ─────────────────────────────────────────

def load_codes_pool() -> dict[str, dict[str, Any]]:
    """
    从 codes_pool.json 动态加载可用兑换码池。
    文件不存在或损坏时返回空字典。
    
    格式示例：
    {
        "RS2026-SINGLE-001": {"tier": "single", "days": null, "label": "单次体验码"},
        "RS2026-MONTH-001":  {"tier": "monthly", "days": 30, "label": "月度会员"},
        "RS2026-YEAR-001":   {"tier": "monthly", "days": 365, "label": "年度会员"}
    }
    """
    try:
        if _CODES_POOL_FILE.is_file():
            content = _CODES_POOL_FILE.read_text(encoding="utf-8")
            if content.strip():
                codes = json.loads(content)
                # 验证格式：确保值是字典
                if isinstance(codes, dict):
                    valid_codes = {}
                    for k, v in codes.items():
                        if isinstance(v, dict) and "tier" in v:
                            valid_codes[str(k).strip().upper()] = v
                    return valid_codes
                logger.warning(f"codes_pool.json 格式错误：根类型应为对象，已返回空字典")
    except json.JSONDecodeError as e:
        logger.warning(f"codes_pool.json 解析失败：{e}，返回空字典")
    except OSError as e:
        logger.warning(f"读取 codes_pool.json 失败：{e}，返回空字典")
    except Exception as e:
        logger.error(f"加载 codes_pool.json 时发生未知错误：{e}")
    return {}


# 启动时加载兑换码池（模块级缓存）
_CODE_REGISTRY: dict[str, dict[str, Any]] = {}


def _reload_codes_pool() -> None:
    """重新加载兑换码池（供外部调用刷新）。"""
    global _CODE_REGISTRY
    _CODE_REGISTRY = load_codes_pool()


# 初始化加载
_reload_codes_pool()


# ─────────────────────────────────────────
# 3. 文件操作辅助函数
# ─────────────────────────────────────────

def _ensure_state_dir() -> bool:
    """确保状态目录存在，创建失败返回 False。"""
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        return True
    except OSError as e:
        logger.error(f"无法创建状态目录 {_STATE_DIR}: {e}")
        return False


def _load_json(path: Path) -> dict[str, Any]:
    """安全加载 JSON 文件，文件不存在或损坏时返回空字典。"""
    try:
        if path.is_file():
            content = path.read_text(encoding="utf-8")
            if content.strip():
                return json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON 解析失败 {path}: {e}，返回空字典")
    except OSError as e:
        logger.warning(f"文件读取失败 {path}: {e}")
    except Exception as e:
        logger.error(f"未知错误读取 {path}: {e}")
    return {}


def _save_json(path: Path, data: dict[str, Any]) -> bool:
    """安全保存 JSON 文件，使用原子写入（先写临时文件再替换）。"""
    try:
        if not _ensure_state_dir():
            return False
        tmp = path.with_suffix(".json.tmp")
        content = json.dumps(data, ensure_ascii=False, indent=2)
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError as e:
        logger.error(f"文件写入失败 {path}: {e}")
    except Exception as e:
        logger.error(f"未知错误写入 {path}: {e}")
    return False


# ─────────────────────────────────────────
# 4. 核心 API
# ─────────────────────────────────────────

def get_license_state(device_id: str = "") -> dict[str, Any]:
    """
    读取当前设备权限状态（从本地缓存文件）。
    优先使用设备专属文件，支持多设备隔离。
    """
    if device_id:
        return _load_json(_get_device_license_file(device_id))
    return _load_json(_LICENSE_FILE)


def check_permission(device_id: str = "") -> tuple[str, str | None, int]:
    """
    检查当前设备权限状态。
    返回 (tier, expired_msg, remaining_trials)
    - tier: "free" | "single" | "monthly"
    - expired_msg: 若年度到期，返回友好提示；否则 None
    - remaining_trials: 免费试用剩余次数（仅 free 时有效）
    """
    state = get_license_state(device_id)
    tier = state.get("tier", "free")
    remaining_trials = state.get("remaining_trials", FREE_TRIAL_COUNT)

    # 月度/年度会员：检查是否到期（按 days 区分显示）
    if tier == "monthly":
        days = state.get("days", 30)
        tier_label = "年度会员" if days == 365 else "月度会员"
        expires = state.get("expires_at", "")
        if expires:
            try:
                exp_date = datetime.strptime(expires, "%Y-%m-%d")
                now = datetime.now()
                if now > exp_date:
                    # 到期：自动降级为 free，并更新本地状态
                    state["tier"] = "free"
                    state["remaining_trials"] = remaining_trials
                    _save_json(_get_device_license_file(device_id) if device_id else _LICENSE_FILE, state)
                    return "free", f"{tier_label}已于 {expires} 到期，已恢复免费权限", remaining_trials
                return tier, None, remaining_trials
            except ValueError:
                pass
        return tier, None, remaining_trials

    # 单次体验：检查是否已消费
    if tier == "single":
        if state.get("single_used"):
            return "free", None, remaining_trials
        return tier, None, remaining_trials

    # 免费用户
    return "free", None, remaining_trials


def check_code_valid(code: str) -> tuple[bool, str]:
    """
    检查兑换码是否有效（仅校验码本身，不执行兑换）。
    返回 (is_valid, message)
    """
    code = code.strip().upper()
    if not code:
        return False, "请输入兑换码"

    # 校验码是否在码池中
    if code not in _CODE_REGISTRY:
        return False, "兑换码无效，请核对后重新输入"

    # 校验是否已使用（仅检查全局已使用记录）
    used = _load_json(_USED_CODES_FILE)
    if code in used:
        return False, "该兑换码已被使用"

    return True, "兑换码有效"


def redeem_code(code: str, device_id: str = "") -> tuple[bool, str]:
    """
    兑换码校验与激活。
    兑换码全局唯一（防止重复使用），但权限按设备隔离存储。
    返回 (success, message)
    """
    code = code.strip().upper()
    if not code:
        return False, "请输入兑换码"

    # 校验码是否存在
    if code not in _CODE_REGISTRY:
        return False, "兑换码无效，请核对后重新输入"

    # 查本地已使用记录
    used = _load_json(_USED_CODES_FILE)
    if code in used:
        return False, "此兑换码已被使用过，无法重复兑换"

    # 获取当前设备状态（不重复调用，内部共享）
    state = get_license_state(device_id)
    current_tier = state.get("tier", "free")
    current_days = state.get("days", 0)
    new_tier = _CODE_REGISTRY[code]["tier"]
    new_info = _CODE_REGISTRY[code]
    new_days = new_info.get("days", 0)

    # 防止降级逻辑
    # 月度会员（30天）不能降级到单次
    if current_tier == "monthly" and current_days == 30 and new_tier == "single":
        return False, "您已是月度会员，功能已全部解锁，无需再兑换单次码"
    # 年度会员（365天）不能降级到月度或单次
    if current_tier == "monthly" and current_days == 365:
        if new_tier == "single" or (new_tier == "monthly" and new_days == 30):
            return False, "您已是年度会员，功能已全部解锁，无需再降级"
        # 年度会员也不能重复兑换年度
        if new_tier == "monthly" and new_days == 365:
            return False, "您已是年度会员，功能已全部解锁，无需重复兑换"
    if current_tier == "single" and new_tier == "single":
        return False, "您已是单次体验会员，请兑换月度或年度会员解锁更多功能"

    # 激活新权限
    info = _CODE_REGISTRY[code]
    tier = info["tier"]
    label = info["label"]
    days = info.get("days")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    new_state: dict[str, Any] = {
        "tier": tier,
        "remaining_trials": FREE_TRIAL_COUNT,
        "activated_at": now_str,
        "days": days,
    }

    # 月度/年度会员：计算到期时间
    if tier == "monthly" and info.get("days"):
        expires = (datetime.now() + timedelta(days=info["days"])).strftime("%Y-%m-%d")
        new_state["expires_at"] = expires

    # 单次体验：初始化未使用状态
    if tier == "single":
        new_state["single_used"] = False

    # 写入设备专属缓存（支持多设备隔离）
    license_file = _get_device_license_file(device_id) if device_id else _LICENSE_FILE
    if not _save_json(license_file, new_state):
        return False, "保存权限状态失败，请重试"

    # 标记码为已使用（全局记录，防止重复兑换）
    used[code] = {
        "redeemed_at": now_str,
        "tier": tier,
        "label": label,
        "device_id": device_id,  # 记录兑换设备
    }
    if not _save_json(_USED_CODES_FILE, used):
        logger.warning(f"兑换码 {code} 已激活，但标记已使用记录失败")

    return True, f"✅ 兑换成功！您已成为「{label}」，请刷新页面查看权限状态"


def _build_status_info(device_id: str = "") -> dict[str, Any]:
    """构建用于 UI 展示的权限状态信息（按设备隔离）。"""
    tier, expired_msg, remaining_trials = check_permission(device_id)
    state = get_license_state(device_id)

    # 根据 days 区分月度/年度会员的显示标签
    if tier == "monthly":
        days = state.get("days", 30)
        tier_label = "年度会员" if days == 365 else "月度会员"
        tier_icon = "📅"
    else:
        tier_label = _tier_label(tier)
        tier_icon = _tier_icon(tier)

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

    # 权限功能映射
    if tier == "monthly":
        info.update(can_optimize=True, can_export=True, can_template=True)
    elif tier == "single":
        if not state.get("single_used"):
            info.update(can_optimize=True, can_export=False, can_template=False)
        else:
            info["lock_reason"] = "单次体验码已使用，请兑换正式会员继续使用"
    else:  # free
        if remaining_trials > 0:
            info["can_optimize"] = True
        else:
            info["lock_reason"] = "免费试用次数已用完，请兑换会员解锁全部功能"

    return info


def _tier_label(tier: str) -> str:
    """获取权限等级的中文标签。"""
    labels = {
        "free":     "免费游客",
        "single":   "单次体验",
        "monthly":  "月度会员",
    }
    return labels.get(tier, "未知权限")


def _tier_icon(tier: str) -> str:
    """获取权限等级的图标。"""
    icons = {
        "free":     "🚪",
        "single":   "🎫",
        "monthly":  "🌙",
    }
    return icons.get(tier, "❓")


def consume_single_use(device_id: str = "") -> bool:
    """
    将当前单次码标记为已消费（按设备隔离）。
    返回是否成功。
    """
    state = get_license_state(device_id)
    license_file = _get_device_license_file(device_id) if device_id else _LICENSE_FILE
    if state.get("tier") == "single" and not state.get("single_used"):
        state["single_used"] = True
        state["single_used_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state["tier"] = "free"
        state["remaining_trials"] = 0
        return _save_json(license_file, state)
    return True


def decrement_trial(device_id: str = "") -> bool:
    """
    免费试用次数 -1（按设备隔离写入本地缓存）。
    返回是否成功。
    """
    state = get_license_state(device_id)
    license_file = _get_device_license_file(device_id) if device_id else _LICENSE_FILE
    remaining = state.get("remaining_trials", FREE_TRIAL_COUNT)
    # 确保 tier 为 free，remaining_trials 不小于 0
    state["tier"] = "free"
    state["remaining_trials"] = max(0, remaining - 1)
    return _save_json(license_file, state)


# ─────────────────────────────────────────
# 导出供 app.py 内部使用的函数
# ─────────────────────────────────────────
__all__ = [
    "check_permission", "redeem_code", "consume_single_use",
    "decrement_trial", "_build_status_info", "get_license_state",
    "check_code_valid", "load_codes_pool", "_reload_codes_pool",
    "FREE_TRIAL_COUNT",
]
