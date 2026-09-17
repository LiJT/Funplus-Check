"""Daily task orchestration for FunPlus Zone / Tiles Survive."""

from __future__ import annotations

import base64
import json
import os
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from funplus.browser import (
    browse_community_posts,
    claim_benefit_packs,
    click_claim_buttons,
    create_context,
    ensure_logged_in,
    read_auth_from_page,
)
from funplus.client import (
    DEFAULT_BASENAME,
    DEFAULT_GAME_PROJECT,
    TASK_ACTIVE,
    TASK_DAILY,
    TASK_GAME,
    TASK_GROWTH,
    FunplusClient,
    can_claim_task,
    can_receive_member_gift,
    cookies_from_storage,
    extract_token_from_storage,
    gift_display_name,
    load_auth_payload,
    member_gift_id,
    needs_goto,
    parse_cookie_string,
)
from funplus.notify import push_plus

SIGNIN_KEYWORDS = ("签到", "簽到", "sign-in", "signin", "sign in", "專區簽到", "专区签到")
PURCHASE_KEYWORDS = ("储值", "儲值", "支付", "purchase", "top-up", "topup", "充值", "商城支付")
VISIT_KEYWORDS = ("帖子", "瀏覽", "浏览", "visit", "read", "posts", "查看")
EXCHANGE_TASK_KEYWORDS = (
    "积分商城",
    "積分商城",
    "兑换1次",
    "兌換1次",
    "exchange once",
    "redeem once",
    "points store",
    "point mall",
)

# Prefer the cheapest daily 10K supply crate used to unlock the mall-exchange task.
TARGET_SHOP_ITEM_IDS = ("item_resource_box_medium",)
TARGET_SHOP_NAME_KEYWORDS = (
    "10k supply crate",
    "10k資源補給箱",
    "10k资源补给箱",
    "10k資源",
    "10k资源",
)
TARGET_SHOP_COST_COIN = 2
TARGET_SHOP_BUY_ONCE = 1


def _b64_maybe_decode(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    # Heuristic: base64 JSON blob
    if not text.startswith("{") and not ("=" in text[:40] and ";" in text):
        try:
            decoded = base64.b64decode(text).decode("utf-8")
            if decoded.strip().startswith("{") or "cookie" in decoded.lower():
                return decoded
        except Exception:
            pass
    return text


def load_auth_from_env() -> Dict[str, Any]:
    """
    Supported secrets:
      FUNPLUS_AUTH          JSON / base64 JSON (recommended)
      FUNPLUS_STORAGE_STATE Playwright storage_state JSON / base64
      FUNPLUS_H5_AUTH       raw h5-auth token
      FUNPLUS_COOKIE        cookie header string
    """
    auth: Dict[str, Any] = {}

    for key in ("FUNPLUS_AUTH", "FUNPLUS_STORAGE_STATE"):
        raw = os.environ.get(key, "").strip()
        if not raw:
            continue
        text = _b64_maybe_decode(raw)
        payload = load_auth_payload(text)
        auth.update(payload)
        if "cookies" not in auth and "origins" in payload:
            auth["storage_state"] = payload
        if key == "FUNPLUS_STORAGE_STATE" and "origins" in payload:
            auth["storage_state"] = payload

    # Nested storage_state under AUTH json
    if isinstance(auth.get("storage_state"), dict):
        pass
    elif isinstance(auth.get("origins"), list):
        auth["storage_state"] = {
            "cookies": auth.get("cookies") if isinstance(auth.get("cookies"), list) else auth.get("storage_cookies", []),
            "origins": auth.get("origins"),
        }

    h5 = os.environ.get("FUNPLUS_H5_AUTH", "").strip()
    if h5:
        auth["h5_auth"] = h5

    cookie = os.environ.get("FUNPLUS_COOKIE", "").strip()
    if cookie:
        auth["cookies"] = cookie

    # File fallback for local runs
    for path in (
        Path(".auth/funplus_auth.json"),
        Path("funplus_auth.json"),
        Path("storage_state.json"),
    ):
        if path.exists() and not auth:
            auth = json.loads(path.read_text(encoding="utf-8"))
            if "origins" in auth and "storage_state" not in auth:
                auth = {"storage_state": auth}
            break

    return auth


def build_client(auth: Dict[str, Any], page_token: str = "", page_fp_uid: str = "") -> FunplusClient:
    storage = auth.get("storage_state") if isinstance(auth.get("storage_state"), dict) else None
    cookies: Dict[str, str] = {}

    if isinstance(auth.get("cookies"), str):
        cookies.update(parse_cookie_string(auth["cookies"]))
    elif isinstance(auth.get("cookies"), dict):
        cookies.update({str(k): str(v) for k, v in auth["cookies"].items()})

    h5_auth = str(auth.get("h5_auth") or auth.get("token") or "")
    fp_uid = str(auth.get("fp_uid") or "")

    if storage:
        extracted = extract_token_from_storage(storage)
        h5_auth = h5_auth or extracted.get("h5_auth") or ""
        fp_uid = fp_uid or extracted.get("fp_uid") or ""
        cookies.update(cookies_from_storage(storage))

    h5_auth = page_token or h5_auth
    fp_uid = page_fp_uid or fp_uid

    if not h5_auth:
        raise RuntimeError(
            "未找到 h5-auth。请运行 python export_auth.py 导出登录态，"
            "并设置 FUNPLUS_AUTH / FUNPLUS_H5_AUTH Secret。"
        )

    client = FunplusClient(
        h5_auth=h5_auth,
        cookies=cookies,
        basename=os.environ.get("FUNPLUS_BASENAME") or DEFAULT_BASENAME,
        game_project=os.environ.get("FUNPLUS_GAME_PROJECT") or DEFAULT_GAME_PROJECT,
        fp_uid=fp_uid,
        uid=str(auth.get("uid") or ""),
        game_id=str(auth.get("game_id") or ""),
    )
    return client


def _task_name(task: Dict[str, Any]) -> str:
    return str(task.get("task_name") or task.get("name") or task.get("task_key") or "task")


def _match(task: Dict[str, Any], keywords: Tuple[str, ...]) -> bool:
    blob = " ".join(
        str(task.get(k) or "")
        for k in ("task_name", "name", "rule_desc", "task_key", "desc", "description")
    ).lower()
    return any(k.lower() in blob for k in keywords)


def do_monthly_signin(client: FunplusClient) -> str:
    info = client.month_checkin_info()
    if not isinstance(info, dict) or not info:
        return "月签到：无法获取签到信息（可能未登录或活动未开放）"

    active_id = str(info.get("active_id") or "")
    now_day = info.get("now_day")
    has_check = bool(info.get("now_day_has_check"))
    total = info.get("total_check_days")
    month = info.get("month")

    if not active_id:
        return f"月签到：缺少 active_id，原始数据 keys={list(info.keys())}"

    if has_check:
        return (
            f"月签到：今日已签到（month={month}, day={now_day}, "
            f"累计={total}, active_id={active_id[:8]}…）"
        )

    result = client.month_checkin(active_id)
    code = result.get("code")
    msg = result.get("msg") or result.get("message") or ""
    if code in (0, "0"):
        return f"月签到：签到成功（month={month}, day={now_day}）"
    return f"月签到：失败 code={code} msg={msg}"


def do_weekly_signin(client: FunplusClient) -> str:
    info = client.week_checkin_info()
    if not isinstance(info, dict) or not info:
        return "周签到：无数据/未开放"

    active_id = str(info.get("active_id") or "")
    now_day = info.get("now_day")
    # Frontend uses separate weeklyCheckedStatus after posting; infer from gift_list if present.
    gift_list = info.get("gift_list") or []
    already = False
    if isinstance(gift_list, list) and now_day is not None:
        for item in gift_list:
            if str(item.get("day")) == str(now_day) and int(item.get("has_check") or 0) == 1:
                already = True
                break

    if not active_id:
        return "周签到：缺少 active_id"

    if already:
        return f"周签到：今日已签（day={now_day}）"

    result = client.week_checkin(active_id)
    code = result.get("code")
    msg = result.get("msg") or ""
    if code in (0, "0"):
        return f"周签到：签到成功（day={now_day}）"
    # Some games only have monthly calendar; treat business errors gently
    return f"周签到：code={code} msg={msg}"


def collect_tasks(client: FunplusClient) -> List[Dict[str, Any]]:
    tasks: List[Dict[str, Any]] = []
    for category in (TASK_DAILY, TASK_ACTIVE, TASK_GROWTH, TASK_GAME):
        try:
            items = client.task_list(category)
        except Exception as exc:
            print(f"获取任务列表 category={category} 失败：{exc}")
            continue
        for item in items:
            if isinstance(item, dict):
                item = dict(item)
                item["_category"] = category
                tasks.append(item)
    return tasks


def claim_ready_tasks(client: FunplusClient, tasks: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    for task in tasks:
        if not can_claim_task(task):
            continue
        key = str(task.get("task_key") or "")
        name = _task_name(task)
        if not key:
            continue
        result = client.claim_task(key)
        code = result.get("code")
        msg = result.get("msg") or ""
        if code in (0, "0"):
            lines.append(f"领取成功：{name}")
        else:
            lines.append(f"领取失败：{name} code={code} msg={msg}")
    return lines


def summarize_tasks(tasks: List[Dict[str, Any]]) -> str:
    lines = []
    for task in tasks:
        name = _task_name(task)
        progress = f"{task.get('now_progress')}/{task.get('progress')}"
        state = (
            "可领取"
            if can_claim_task(task)
            else ("已完成" if (not needs_goto(task)) else "进行中/需前往")
        )
        lines.append(
            f"- [{task.get('_category')}] {name} | {progress} | "
            f"get_times={task.get('get_times')} | {state}"
        )
    return "\n".join(lines) if lines else "- （无任务）"


def _product_item_blob(product: Dict[str, Any]) -> str:
    parts: List[str] = []
    for item in product.get("item_list") or []:
        if not isinstance(item, dict):
            continue
        parts.append(str(item.get("item_id") or ""))
        parts.append(str(item.get("item_name") or ""))
    parts.append(str(product.get("name") or product.get("product_name") or ""))
    return " ".join(parts).lower()


def find_daily_supply_crate(products: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Find the 2-coin 10K Supply Crate used for the daily mall-exchange task."""
    exact: List[Dict[str, Any]] = []
    fuzzy: List[Dict[str, Any]] = []
    for product in products:
        if not isinstance(product, dict):
            continue
        blob = _product_item_blob(product)
        cost = _as_int(product.get("cost_coin") or product.get("coin") or product.get("price"))
        item_ids = {
            str(item.get("item_id") or "")
            for item in (product.get("item_list") or [])
            if isinstance(item, dict)
        }
        if any(iid in TARGET_SHOP_ITEM_IDS for iid in item_ids):
            exact.append(product)
            continue
        if cost == TARGET_SHOP_COST_COIN and any(k in blob for k in TARGET_SHOP_NAME_KEYWORDS):
            fuzzy.append(product)
    if exact:
        return exact[0]
    if fuzzy:
        return fuzzy[0]
    # Last resort: cheapest cost_coin==2 product with resource box item_id
    candidates = []
    for product in products:
        if not isinstance(product, dict):
            continue
        cost = _as_int(product.get("cost_coin") or product.get("coin") or product.get("price"))
        if cost != TARGET_SHOP_COST_COIN:
            continue
        blob = _product_item_blob(product)
        if "resource_box" in blob or "supply crate" in blob or "補給箱" in blob or "补给箱" in blob:
            candidates.append(product)
    return candidates[0] if candidates else None


def exchange_daily_supply_crate(client: FunplusClient) -> str:
    """
    Exchange the 2-point 10K Supply Crate at most once per UTC day.

    This unlocks the task-center reward「在積分商城內兌換1次」(+10).
    If cycle_now_times >= 1, skip buying so a second scheduled run never double-spends.
    """
    try:
        products = client.shop_product_list(page=1, page_size=100, time_limiter=0)
        if not products:
            products = client.shop_product_list(
                page=1, page_size=100, time_limiter=2, product_type=1
            )
    except Exception as exc:
        return f"积分商城：获取商品列表失败 {exc}"

    product = find_daily_supply_crate(products)
    if not product:
        return "积分商城：未找到 10K 资源补给箱（2 积分），跳过兑换"

    product_id = product.get("id") or product.get("product_id")
    cost = _as_int(product.get("cost_coin") or product.get("coin") or product.get("price"))
    cycle_now = _as_int(product.get("cycle_now_times"))
    cycle_times = _as_int(product.get("cycle_times"))
    item_name = ""
    items = product.get("item_list") or []
    if items and isinstance(items[0], dict):
        item_name = str(items[0].get("item_name") or items[0].get("item_id") or "")
    label = item_name or f"product#{product_id}"

    if not product_id:
        return f"积分商城：商品缺少 product_id（{label}）"

    if cycle_now >= TARGET_SHOP_BUY_ONCE:
        return (
            f"积分商城：今日已兑换过 {label}（{cycle_now}/{cycle_times}），"
            "跳过购买，继续领取任务积分"
        )

    if cost > 0 and cost != TARGET_SHOP_COST_COIN:
        # Safety: only auto-buy the known cheap crate
        return (
            f"积分商城：找到 {label} 但价格为 {cost} 积分（期望 {TARGET_SHOP_COST_COIN}），"
            "为避免误购已跳过"
        )

    if not client.uid:
        client.user_info()
    result = client.shop_buy(product_id, num=1, uid=client.uid)
    code = result.get("code")
    msg = result.get("msg") or result.get("message") or ""
    if code in (0, "0"):
        return f"积分商城：兑换成功 {label}（花费 {cost} 积分，今日 1/{cycle_times or '?'}）"
    # Treat already-bought / limit errors as soft success for the daily-once goal
    soft = ("already", "limit", "times", "不足", "enough", "stock")
    if any(s in str(msg).lower() for s in soft):
        return f"积分商城：未再次购买（{label} code={code} msg={msg}）"
    return f"积分商城：兑换失败 {label} code={code} msg={msg}"


def claim_member_gifts(client: FunplusClient, vip_level: int = 0) -> List[str]:
    lines: List[str] = []
    vip = vip_level
    if not vip:
        vip = _as_int(client.user_info().get("vip_level"))

    try:
        gifts = client.iter_member_gifts()
    except Exception as exc:
        return [f"会员礼包：获取失败 {exc}"]

    claimable = [g for g in gifts if can_receive_member_gift(g, vip_level=vip)]
    if not claimable:
        lines.append("会员礼包：当前没有可领取项（每日/每周/等级礼包均已领或未到条件）")
        return lines

    for gift in claimable:
        gift_id = member_gift_id(gift)
        name = gift_display_name(gift)
        if not gift_id:
            continue
        result = client.receive_member_gift(gift_id)
        code = result.get("code")
        msg = result.get("msg") or result.get("message") or ""
        if code in (0, "0"):
            lines.append(f"礼包领取成功：{name}")
        elif msg in ("verification failed",) or "already" in str(msg).lower():
            lines.append(f"礼包已领取：{name}")
        else:
            lines.append(f"礼包领取失败：{name} code={code} msg={msg}")
    return lines


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


async def run_browser_parts(auth: Dict[str, Any]) -> Dict[str, Any]:
    storage = auth.get("storage_state") if isinstance(auth.get("storage_state"), dict) else None
    headless = os.environ.get("FUNPLUS_HEADED", "").strip() not in ("1", "true", "TRUE")
    playwright, browser, context = await create_context(storage_state=storage, headless=headless)
    page = await context.new_page()
    result: Dict[str, Any] = {
        "logged_in": False,
        "h5_auth": "",
        "fp_uid": "",
        "browse": {},
        "ui_claims": [],
        "pack_claims": [],
    }
    try:
        logged_in = await ensure_logged_in(page)
        auth_bits = await read_auth_from_page(page)
        result["logged_in"] = logged_in or bool(auth_bits.get("h5_auth"))
        result["h5_auth"] = auth_bits.get("h5_auth") or ""
        result["fp_uid"] = auth_bits.get("fp_uid") or ""
        if not result["logged_in"]:
            return result

        # Always browse community posts for active task progress
        result["browse"] = await browse_community_posts(page, target=5)
        result["ui_claims"] = await click_claim_buttons(page)
        result["pack_claims"] = await claim_benefit_packs(page)

        # Persist potentially refreshed cookies for logging only (not written back to GH secrets)
        try:
            result["storage_state"] = await context.storage_state()
        except Exception:
            pass
        return result
    finally:
        await context.close()
        await browser.close()
        await playwright.stop()


def run() -> int:
    push_token = os.environ.get("PUSHPLUS_TOKEN", "").strip()
    lines: List[str] = []
    ok = True

    try:
        auth = load_auth_from_env()
        if not auth and not os.environ.get("FUNPLUS_H5_AUTH"):
            print(
                "未配置登录凭据。请先本地运行 export_auth.py，"
                "再把导出内容写入 GitHub Secret：FUNPLUS_AUTH"
            )
            return 0

        # Browser path keeps community micro-app progress working
        browse_result: Dict[str, Any] = {}
        try:
            import asyncio

            browse_result = asyncio.run(run_browser_parts(auth))
            lines.append(
                f"登录态：{'有效' if browse_result.get('logged_in') else '无效/未登录'}"
            )
            browse = browse_result.get("browse") or {}
            lines.append(
                f"社区浏览：{browse.get('count', 0)} 帖（mode={browse.get('mode')}）"
            )
            if browse_result.get("ui_claims"):
                lines.append("UI 领取：" + ", ".join(browse_result["ui_claims"]))
            if browse_result.get("pack_claims"):
                lines.append("礼包页领取：" + ", ".join(browse_result["pack_claims"]))
        except Exception as exc:
            print(f"浏览器任务异常（将继续执行 API 任务）：{exc}")
            traceback.print_exc()
            lines.append(f"浏览器任务异常：{exc}")
            # Do not hard-fail the whole job; API claim path can still succeed.

        client = build_client(
            auth,
            page_token=str(browse_result.get("h5_auth") or ""),
            page_fp_uid=str(browse_result.get("fp_uid") or ""),
        )
        user = client.user_info()
        nickname = (
            user.get("nickname")
            or user.get("name")
            or user.get("user_name")
            or user.get("uid")
            or "unknown"
        )
        lines.append(f"用户：{nickname} uid={client.uid or user.get('uid')}")

        lines.append(do_monthly_signin(client))
        lines.append(do_weekly_signin(client))

        # Must exchange BEFORE claiming tasks: unlocks「在積分商城內兌換1次」(+10).
        # cycle_now_times>=1 makes a second daily run skip buying.
        lines.append(exchange_daily_supply_crate(client))

        tasks = collect_tasks(client)
        lines.append("任务列表：")
        lines.append(summarize_tasks(tasks))

        # Prefer claiming all claimable tasks to maximize points
        claim_lines = claim_ready_tasks(client, tasks)
        if claim_lines:
            lines.extend(claim_lines)
        else:
            lines.append("任务领取：当前没有可领取任务")

        # Re-fetch after browse + exchange + claims
        tasks_after = collect_tasks(client)
        still_claimable = claim_ready_tasks(client, tasks_after)
        if still_claimable:
            lines.append("二次领取：")
            lines.extend(still_claimable)

        lines.extend(claim_member_gifts(client, vip_level=_as_int(user.get("vip_level"))))

        # Hint unfinished goto tasks
        unfinished = [
            _task_name(t)
            for t in tasks_after
            if needs_goto(t)
            and _match(
                t,
                SIGNIN_KEYWORDS + PURCHASE_KEYWORDS + VISIT_KEYWORDS + EXCHANGE_TASK_KEYWORDS,
            )
        ]
        if unfinished:
            lines.append("仍需手动完成/未达成条件：")
            for name in unfinished:
                lines.append(f"- {name}")

    except Exception as exc:
        ok = False
        lines.append(f"运行失败：{exc}")
        traceback.print_exc()

    report = "\n".join(lines)
    print("\n======== FunPlus 签到报告 ========")
    print(report)
    print("=================================")

    if push_token:
        title = "FunPlus 签到成功" if ok else "FunPlus 签到失败"
        push_plus(push_token, title, report)

    return 0 if ok else 1
