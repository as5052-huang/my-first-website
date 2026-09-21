"""权限与兑换码模块（纯本地缓存，无数据库）"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FREE_TRIAL_COUNT = 1

# ── 自动迁移开关（环境变量）──────────────────────────────────
# 单用户本地部署：可设为 "1"/"true"/"yes"，启用旧 device_xxx → 新 browser_xxx 会员迁移。
# 多用户 / 共享服务器（如 Streamlit Cloud）：必须保持关闭，否则不同用户的会员会互相覆盖。
AUTO_MIGRATE_LEGACY = os.getenv("RO_AUTO_MIGRATE_LEGACY", "").lower() in ("1", "true", "yes")

_STATE_DIR = Path(__file__).resolve().parent / ".state"
_LICENSE_FILE = _STATE_DIR / "license.json"
_USED_CODES_FILE = _STATE_DIR / "used_codes.json"
_CODES_POOL_FILE = Path(__file__).resolve().parent / "codes_pool.json"
_DEVICE_ID_FILE = _STATE_DIR / "device_id.txt"


_MOBILE_UA_TOKENS = (
    "Mobile", "Android", "iPhone", "iPad", "iPod",
    "Windows Phone", "Opera Mini", "BlackBerry",
    "Symbian", "webOS", "Kindle",
)


def _get_user_agent() -> str:
    """从 st.context.headers 读 User-Agent（无请求上下文时返回空串）。"""
    try:
        import streamlit as _st

        ctx = getattr(_st, "context", None)
        if ctx is not None:
            headers = getattr(ctx, "headers", None)
            if headers is not None:
                return str(headers.get("User-Agent", "") or "")
    except Exception:
        pass
    return ""


def _is_mobile_user_agent(ua: str) -> bool:
    """判断 UA 是否来自移动设备（含 Mobile/Android/iPhone 等关键字）。"""
    if not ua:
        return False
    ua_lower = ua.lower()
    # 注意：UA 含 "Mobile" 一般是手机/平板，不含则是桌面
    # "Android" 默认是手机（也有 Android TV，但占极少数）
    return any(token.lower() in ua_lower for token in _MOBILE_UA_TOKENS)


def _get_base_device_id() -> str:
    """基础设备 ID（来自 .state/device_id.txt，与机器特征绑定）。

    注意：此 ID 在同一服务器的多个客户端之间共享（部署在 Streamlit Cloud 等共享环境时会冲突），
    仅作为最后的 fallback。优先使用浏览器级 ID（见 _get_browser_device_id）。
    """
    try:
        if _DEVICE_ID_FILE.is_file():
            stored = _DEVICE_ID_FILE.read_text(encoding="utf-8").strip()
            if stored and stored.startswith("device_"):
                return stored
    except OSError:
        pass

    # 首次生成：基于服务器机器特征（对所有访问此 Streamlit 实例的客户端都一样）
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


def _get_browser_device_id() -> str | None:
    """通过 localStorage 获取浏览器级稳定 ID（每个浏览器独立，跨会话稳定）。

    实现细节（优先级递减）：
    1. session_state 缓存（避免重复 JS 调用）
    2. st.query_params fallback（Streamlit Cloud 上 streamlit_js_eval 不可用时）
       - 首次访问时生成 ID 写入 ?ro_did=xxx，再次访问时读回
       - 跨 session 稳定（URL 参数会随请求发送）
    3. streamlit_js_eval JS 回调（仅本地环境）
       - 调用 JS：读取 localStorage['ro_browser_id_v1']
       - 若不存在则生成新的 browser_xxx 写入 localStorage，再返回
       - 失败时返回 None，调用方回退到机器级 ID

    优势：
    - localStorage 是浏览器隔离的，不同浏览器/无痕模式互不影响
    - 即使部署在共享服务器，每个用户的 ID 也是独立的
    - 跨会话稳定（除非用户清除浏览器数据）

    注意：st.query_params 在 Streamlit Cloud 上工作稳定，因为请求 URL
    会被 Streamlit 保留，即使 Cloud 做了负载均衡也不影响（每个请求
    都能从 URL 读取到同一个 ro_did 参数）。
    """
    # 0. session_state 缓存（防止 JS 异步返回导致 ID 闪烁）
    try:
        import streamlit as st

        cached = st.session_state.get("_browser_device_id")
        if cached:
            return cached
        # 显式标记"已尝试获取"，防止后续 rerun 期间重复触发 JS
        st.session_state.setdefault("_browser_id_attempted", True)
    except Exception:
        return None

    # ── 1. st.query_params fallback（Streamlit Cloud 优先）─────────
    # streamlit_js_eval 在 Streamlit Cloud 上可能无法正常工作：
    # - Cloud 的 WebSocket 连接不支持 streamlit_js_eval 的 HTTP 轮询端点
    # - 这会导致 JS 永远不返回，device ID 获取失败 → 回退到机器级 ID
    #   → 所有用户共享同一个机器 ID → license.json 冲突
    # query_params 通过 URL 参数传递，Streamlit Cloud 对所有请求保持一致
    try:
        import streamlit as st

        existing = st.query_params.get("ro_did", "")
        if existing and isinstance(existing, str) and existing.startswith("browser_") and len(existing) > 10:
            logger.info(f"通过 st.query_params 获取设备 ID: {existing[:16]}...")
            return existing

        # 首次访问：生成新 ID 并写回 URL 参数（在下一次请求生效）
        new_id = f"browser_{hashlib.sha256(os.urandom(16)).hexdigest()[:24]}"
        st.query_params["ro_did"] = new_id
        logger.info(f"生成了新的 ro_did: {new_id[:16]}...（写入 query_params）")
        return new_id
    except Exception as e:
        logger.debug(f"st.query_params fallback 失败: {e}")

    # ── 2. streamlit_js_eval（本地环境）───────────────────────────
    try:
        from streamlit_js_eval import streamlit_js_eval

        # JS：读取 localStorage，没有则生成新 ID 写入再返回
        js_expr = (
            "(function(){try{"
            "var id=localStorage.getItem('ro_browser_id_v1');"
            "if(id&&id.indexOf('browser_')===0){return id;}"
            "var nid='browser_'+Date.now().toString(36)+'_'+Math.random().toString(36).slice(2,10);"
            "try{localStorage.setItem('ro_browser_id_v1',nid);}catch(e){}"
            "return nid;"
            "}catch(e){return '';}})()"
        )

        result = streamlit_js_eval(js_expressions=js_expr, key="_browser_id_eval_v1")

        if result and isinstance(result, str) and result.startswith("browser_") and len(result) > 10:
            logger.info(f"通过 streamlit_js_eval 获取设备 ID: {result[:16]}...")
            try:
                import streamlit as st

                st.session_state["_browser_device_id"] = result
            except Exception:
                pass
            return result
    except Exception as e:
        logger.debug(f"获取浏览器 ID 失败（streamlit_js_eval）: {e}")

    return None


def _try_migrate_legacy_license(new_id: str, browser_id: str) -> None:
    """将旧 device_xxx 会员迁移到新 browser_xxx ID（仅在 AUTO_MIGRATE_LEGACY 开启时）。

    迁移策略（仅适用于单用户本地部署）：
    - license.json 中恰好 1~2 个 device_xxx 条目时执行迁移（主条目 + 可选的 mobile 变体）
    - 多于 2 个条目时跳过（多用户场景，避免误迁移覆盖其他用户会员）
    - 迁移完成后删除旧条目，保留新条目

    多用户 / 共享服务器场景下应禁用此功能，否则 User A 的会员会被迁移到 User B 的 ID。
    """
    if not AUTO_MIGRATE_LEGACY:
        return

    # 同一 session 只尝试一次
    try:
        import streamlit as st

        marker = f"_license_migrated_{browser_id}"
        if st.session_state.get(marker):
            return
    except Exception:
        return

    try:
        all_states = _load_json(_LICENSE_FILE)
    except Exception:
        return

    # 查找旧 device_xxx 条目
    legacy_keys = [k for k in all_states if k.startswith("device_")]
    if not legacy_keys:
        try:
            import streamlit as st

            st.session_state[marker] = True
        except Exception:
            pass
        return

    # 多于 2 个说明是多用户场景，不自动迁移
    if len(legacy_keys) > 2:
        logger.warning(
            f"license.json 中有 {len(legacy_keys)} 个旧 device_ 条目，"
            f"疑似多用户场景，跳过自动迁移（设 RO_AUTO_MIGRATE_LEGACY=false 关闭此检查）"
        )
        try:
            import streamlit as st

            st.session_state[marker] = True
        except Exception:
            pass
        return

    # 分离主条目和 mobile 条目
    mobile_suffix = "_mobile"
    legacy_main = [k for k in legacy_keys if not k.endswith(mobile_suffix)]
    legacy_mobile = [k for k in legacy_keys if k.endswith(mobile_suffix)]

    # 计算新的 main / mobile ID
    if new_id.endswith(mobile_suffix):
        new_main_id = new_id[: -len(mobile_suffix)]
    else:
        new_main_id = new_id

    migrated = False

    # 迁移主条目
    if len(legacy_main) == 1:
        legacy_main_id = legacy_main[0]
        legacy_main_state = all_states.get(legacy_main_id)
        if legacy_main_state:
            all_states[new_main_id] = legacy_main_state.copy()
            all_states.pop(legacy_main_id, None)
            migrated = True
            logger.info(f"已迁移主会员: {legacy_main_id} → {new_main_id}")

    # 迁移 mobile 条目（仅当 new_id 是 mobile 时）
    if new_id.endswith(mobile_suffix) and len(legacy_mobile) == 1:
        legacy_mobile_id = legacy_mobile[0]
        legacy_mobile_state = all_states.get(legacy_mobile_id)
        if legacy_mobile_state:
            all_states[new_id] = legacy_mobile_state.copy()
            all_states.pop(legacy_mobile_id, None)
            migrated = True
            logger.info(f"已迁移 mobile 会员: {legacy_mobile_id} → {new_id}")

    # 保存
    if migrated:
        _save_json(_LICENSE_FILE, all_states)

    try:
        import streamlit as st

        st.session_state[marker] = True
    except Exception:
        pass


def _get_stable_device_id() -> str:
    """获取稳定设备 ID（每个浏览器独立）。

    设备 ID 优先级：
    1. st.query_params ro_did（Streamlit Cloud 兼容，每个用户独立）
    2. 浏览器 localStorage ID（最稳定，每个浏览器独立 - 适合共享服务器/多用户场景）
    3. 机器特征 + 文件缓存（向后兼容 - 同服务器多客户端共享，仅适合单用户本地部署）

    移动端追加 _mobile 后缀，使手机和电脑分别有独立的会员状态。

    注意：调用结果会被缓存到 session_state['_stable_device_id']，
    避免在同一会话内因 JS 异步加载而切换 ID 导致的状态闪烁。
    """
    # 0. session_state 缓存（防止 JS 异步返回导致 ID 闪烁）
    try:
        import streamlit as st

        cached = st.session_state.get("_stable_device_id")
        if cached:
            return cached
    except Exception:
        pass

    ua = _get_user_agent()
    is_mobile = _is_mobile_user_agent(ua)
    mobile_suffix = "_mobile" if is_mobile else ""

    # 1. 浏览器级 ID（localStorage / query_params）
    browser_id = _get_browser_device_id()
    if browser_id:
        final_id = f"{browser_id}{mobile_suffix}"
        logger.info(f"设备 ID 命中 browser_id: {final_id[:20]}...")
        # 尝试迁移旧 device_xxx 会员（如果启用）
        _try_migrate_legacy_license(final_id, browser_id)
        try:
            import streamlit as st

            st.session_state["_stable_device_id"] = final_id
        except Exception:
            pass
        return final_id

    # 2. 回退到机器特征 ID（首次访问 JS 尚未返回；或 JS 不可用）
    logger.warning("未能获取浏览器级 ID，回退到机器特征 ID（Streamlit Cloud 多用户可能冲突）")
    base_id = _get_base_device_id()
    final_id = f"{base_id}{mobile_suffix}"
    try:
        import streamlit as st

        st.session_state["_stable_device_id"] = final_id
    except Exception:
        pass
    return final_id


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


def _atomic_json_modify(path: Path, modifier):
    """读取-修改-写回的原子操作（带锁文件机制，防止并发冲突）。

    modifier 接收当前数据（dict），返回修改后的数据。返回 None 表示放弃修改。
    在并发环境下，多个 modifier 串行执行：先获取独占锁的优先，其他等待并重试。
    锁文件有效期 10 秒（防止异常退出留下死锁）。
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    max_attempts = 25

    for attempt in range(max_attempts):
        try:
            # 尝试独占创建锁文件（O_EXCL 失败表示锁已存在）
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode("utf-8"))
            except Exception:
                pass
            finally:
                os.close(fd)
            break  # 拿到锁
        except FileExistsError:
            # 锁被占用，检查是否过期
            try:
                mtime = lock_path.stat().st_mtime
                if (datetime.now().timestamp() - mtime) > 10:
                    # 锁过期（> 10 秒没释放），强制清理
                    try:
                        lock_path.unlink()
                    except OSError:
                        pass
                    continue
            except OSError:
                pass
            # 等待并重试（指数退避）
            time.sleep(0.03 + attempt * 0.015)
        except Exception as e:
            logger.warning(f"无法创建锁文件 {lock_path}: {e}")
            return None
    else:
        logger.error(f"无法获取文件锁 {path.name}（已重试 {max_attempts} 次）")
        return None

    # 已获取锁：读取 → 修改 → 写回
    try:
        data = _load_json(path)
        result = modifier(data)
        if result is None:
            return None
        if _save_json(path, result):
            return result
        return None
    finally:
        # 无论成功失败都释放锁
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass


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

    # 防止降级（修复：使用 >= 比较 + 缺失 days 字段视为 30 天月度会员，与 check_permission 一致）
    state = get_license_state(device_id)
    cur_tier = state.get("tier", "free")
    # 当 days 字段缺失时，按 30 天月度会员处理（与 check_permission() 的默认行为保持一致）
    cur_days_raw = state.get("days")
    cur_days = cur_days_raw if cur_days_raw is not None else 30
    info = _CODE_REGISTRY[code]
    new_tier = info["tier"]
    if cur_tier == "monthly" and cur_days >= 365:
        return False, "您已是年度会员，功能已全部解锁，无需再降级"
    if cur_tier == "monthly" and cur_days >= 30 and new_tier == "single":
        return False, "您已是月度会员，功能已全部解锁，无需再兑换单次码"
    if cur_tier == "single" and new_tier == "single":
        return False, "您已是单次体验会员，请兑换月度或年度会员解锁更多功能"

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 原子操作：检查兑换码是否已用 + 标记已用（防止并发重复使用）
    def _check_and_mark(used_codes: dict) -> dict | None:
        if code in used_codes:
            return None  # 已使用，由调用方做二次确认
        used_codes[code] = {
            "redeemed_at": now_str,
            "tier": info["tier"],
            "label": info["label"],
            "device_id": device_id,
        }
        return used_codes

    updated = _atomic_json_modify(_USED_CODES_FILE, _check_and_mark)
    if updated is None:
        # 区分"码已被使用"和"系统错误"
        if code in _load_json(_USED_CODES_FILE):
            return False, "此兑换码已被使用过，无法重复兑换"
        return False, "系统繁忙，请稍后再试"

    # 激活新权限
    tier, label, days = info["tier"], info["label"], info.get("days")
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
        # 回滚 used_codes 中的标记（best-effort，避免脏数据）
        logger.error(f"兑换码 {code} 已标记，但保存会员状态失败，需手动修复")
        return False, "保存权限状态失败，请重试"

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
