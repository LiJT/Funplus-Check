"""FunPlus Zone (Tiles Survive) API client."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

import requests

API_BASE = "https://zone-api.funplus.com/api/"
ZONE_ORIGIN = "https://zone.funplus.com"
DEFAULT_BASENAME = "/tilessurvive"
DEFAULT_GAME_PROJECT = "ts_global"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 45

# Task category enum from frontend
TASK_DAILY = 1
TASK_ACTIVE = 2
TASK_GROWTH = 3
TASK_GAME = 4

# reward_issue_type
REWARD_MANUAL = 1
REWARD_AUTO = 2


def parse_cookie_string(cookie: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for part in cookie.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def cookie_header(cookies: Dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def is_auto_reward(task: Dict[str, Any]) -> bool:
    return _as_int(task.get("reward_issue_type")) == REWARD_AUTO


def can_claim_task(task: Dict[str, Any]) -> bool:
    """Mirrors frontend pe/kx: manual reward and get_times > 0."""
    return (not is_auto_reward(task)) and _as_int(task.get("get_times")) > 0


def is_task_finished(task: Dict[str, Any]) -> bool:
    """Mirrors frontend he/xH."""
    return (is_auto_reward(task) or _as_int(task.get("get_times")) == 0) and (
        _as_int(task.get("now_times_in_cycle")) >= _as_int(task.get("times_in_cycle"))
    )


def needs_goto(task: Dict[str, Any]) -> bool:
    return (not can_claim_task(task)) and (not is_task_finished(task))


@dataclass
class FunplusClient:
    h5_auth: str
    cookies: Dict[str, str] = field(default_factory=dict)
    basename: str = DEFAULT_BASENAME
    game_project: str = DEFAULT_GAME_PROJECT
    uid: str = ""
    game_id: str = ""
    fp_uid: str = ""
    session: requests.Session = field(default_factory=requests.Session)

    def __post_init__(self) -> None:
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Origin": ZONE_ORIGIN,
                "Referer": f"{ZONE_ORIGIN}{self.basename}/",
                "Content-Type": "application/json",
            }
        )
        if self.h5_auth:
            self.session.headers["h5-auth"] = self.h5_auth
        if self.cookies:
            self.session.headers["Cookie"] = cookie_header(self.cookies)
            for key, value in self.cookies.items():
                self.session.cookies.set(
                    key, unquote(value), domain=".funplus.com", path="/"
                )
        self._sync_priv_headers()

    def _sync_priv_headers(self) -> None:
        if self.uid:
            self.session.headers["Priv-Uid"] = str(self.uid)
        if self.game_id:
            self.session.headers["Priv-Game-Id"] = str(self.game_id)

    def post(self, path: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = path if path.startswith("http") else f"{API_BASE}{path.lstrip('/')}"
        response = self.session.post(url, json=data or {}, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return {"code": -1, "msg": "invalid response", "data": payload}
        return payload

    def get(self, path: str) -> Dict[str, Any]:
        url = path if path.startswith("http") else f"{API_BASE}{path.lstrip('/')}"
        response = self.session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return {"code": -1, "msg": "invalid response", "data": payload}
        return payload

    def user_info(self) -> Dict[str, Any]:
        result = self.post("user/info")
        data = (result.get("data") or {}) if result.get("code") == 0 else {}
        if isinstance(data, dict):
            # Some responses nest again under data
            inner = data.get("data") if isinstance(data.get("data"), dict) else data
            if inner.get("uid"):
                self.uid = str(inner.get("uid"))
            if inner.get("game_id"):
                self.game_id = str(inner.get("game_id"))
            if inner.get("fp_uid"):
                self.fp_uid = str(inner.get("fp_uid"))
            self._sync_priv_headers()
            return inner if isinstance(inner, dict) else data
        return {}

    def month_checkin_info(self) -> Dict[str, Any]:
        result = self.post("checkin/month/info")
        return _unwrap(result)

    def month_checkin(self, active_id: str, uid: Optional[str] = None) -> Dict[str, Any]:
        return self.post(
            "checkin/month",
            {"active_id": active_id, "uid": uid or self.uid},
        )

    def week_checkin_info(self) -> Dict[str, Any]:
        result = self.post("checkin/week/info")
        return _unwrap(result)

    def week_checkin(self, active_id: str, uid: Optional[str] = None) -> Dict[str, Any]:
        return self.post(
            "checkin/week",
            {"active_id": active_id, "uid": uid or self.uid},
        )

    def task_list(self, category: int) -> List[Dict[str, Any]]:
        result = self.post("task/task_list", {"task_category": category})
        data = _unwrap(result)
        if isinstance(data, dict):
            tasks = data.get("task_list") or []
            return tasks if isinstance(tasks, list) else []
        return []

    def claim_task(self, task_key: str) -> Dict[str, Any]:
        return self.post("task/get", {"task_key": task_key})

    def member_gift_list(self) -> List[Dict[str, Any]]:
        result = self.post("member_gift/list")
        data = _unwrap(result)
        if isinstance(data, dict):
            items = data.get("list") or data.get("items") or data.get("gift_list") or []
            return items if isinstance(items, list) else []
        if isinstance(data, list):
            return data
        return []

    def member_gift_list_grouped(self) -> Dict[str, Any]:
        result = self.post("member_gift/list_grouped")
        return _unwrap(result) if isinstance(_unwrap(result), dict) else {}

    def receive_member_gift(self, gift_id: str) -> Dict[str, Any]:
        return self.post(f"member_gift/receive?id={gift_id}")

    def vip_rights_get(self, rights_key: str) -> Dict[str, Any]:
        return self.post("vip/rights_get", {"rights_key": rights_key})


def _unwrap(result: Dict[str, Any]) -> Any:
    if not isinstance(result, dict):
        return {}
    if result.get("code") not in (0, "0", None):
        return result
    data = result.get("data")
    if isinstance(data, dict) and "data" in data and len(data) <= 3:
        return data.get("data")
    return data if data is not None else {}


def extract_token_from_storage(storage_state: Dict[str, Any]) -> Dict[str, str]:
    """Best-effort extraction of h5-auth / fp_uid from Playwright storage_state."""
    found: Dict[str, str] = {"h5_auth": "", "fp_uid": ""}
    origins = storage_state.get("origins") or []
    candidates: List[str] = []

    for origin in origins:
        for item in origin.get("localStorage") or []:
            name = str(item.get("name") or "")
            value = str(item.get("value") or "")
            lower = name.lower()
            if not value:
                continue
            if any(k in lower for k in ("auth", "token", "h5")) and len(value) > 20:
                candidates.append(value)
                if not found["h5_auth"]:
                    found["h5_auth"] = value
            if "fp_uid" in lower or lower.endswith("bV".lower()) or "fpuid" in lower:
                found["fp_uid"] = value
            # Some keys are obfuscated; collect long opaque strings
            if len(value) >= 32 and re.fullmatch(r"[A-Za-z0-9._\-=]+", value):
                candidates.append(value)

    for cookie in storage_state.get("cookies") or []:
        name = str(cookie.get("name") or "")
        value = str(cookie.get("value") or "")
        lower = name.lower()
        if not value:
            continue
        if any(k in lower for k in ("auth", "token", "h5")) and len(value) > 20:
            if not found["h5_auth"] or len(value) > len(found["h5_auth"]):
                found["h5_auth"] = value
        if "fp_uid" in lower or "fpuid" in lower:
            found["fp_uid"] = value
        if len(value) >= 32 and re.fullmatch(r"[A-Za-z0-9._\-=]+", value):
            candidates.append(value)

    if not found["h5_auth"] and candidates:
        # Prefer the longest opaque candidate
        found["h5_auth"] = max(candidates, key=len)

    return found


def cookies_from_storage(storage_state: Dict[str, Any]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for cookie in storage_state.get("cookies") or []:
        name = cookie.get("name")
        value = cookie.get("value")
        if name and value is not None:
            result[str(name)] = str(value)
    return result


def load_auth_payload(raw: str) -> Dict[str, Any]:
    """Accept JSON auth blob, storage_state JSON, or raw cookie string."""
    text = raw.strip()
    if not text:
        return {}
    if text.startswith("{"):
        return json.loads(text)
    # Cookie header string only
    return {"cookies": text}
