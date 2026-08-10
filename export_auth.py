#!/usr/bin/env python3
"""
本地导出 FunPlus 登录态（Cookie + localStorage），用于 GitHub Actions。

用法：
  python -u export_auth.py
  python -u export_auth.py --push-secret
  或直接双击 refresh_auth.bat
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

from funplus.client import extract_token_from_storage

LOGIN_URL = "https://zone.funplus.com/tilessurvive/benefits"
OUT_DIR = Path(".auth")
POLL_SECONDS = 300
POLL_INTERVAL = 2
API_USER_INFO = "https://zone-api.funplus.com/api/user/info"
DEFAULT_REPO = "LiJT/Funplus-Check"


def _extract_live(page) -> dict:
    return page.evaluate(
        """() => {
          const ls = {};
          for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            ls[k] = localStorage.getItem(k);
          }
          const ss = {};
          for (let i = 0; i < sessionStorage.length; i++) {
            const k = sessionStorage.key(i);
            ss[k] = sessionStorage.getItem(k);
          }
          const bodyText = (document.body && document.body.innerText || '').slice(0, 2000);
          const hasLoginCta = /Log in to FunPlus|登录.*账号|登入.*帳戶|Log In|登入|登录/.test(bodyText);
          const loginButtons = Array.from(document.querySelectorAll('button,a'))
            .filter(el => /^(Log In|登录|登入)$/i.test((el.textContent || '').trim())).length;
          return {
            ls,
            ss,
            cookie: document.cookie,
            href: location.href,
            hasLoginCta,
            loginButtons,
            title: document.title,
          };
        }"""
    )


def _candidate_tokens(ls: dict, cookies: str) -> list[str]:
    candidates: list[str] = []
    for source in (ls,):
        for k, v in (source or {}).items():
            if not v:
                continue
            key = str(k).lower()
            val = str(v).strip()
            if val.startswith("{") and "token" in val.lower():
                try:
                    obj = json.loads(val)
                    for nk, nv in obj.items():
                        if isinstance(nv, str) and len(nv) >= 16:
                            if any(x in str(nk).lower() for x in ("auth", "token", "h5")):
                                candidates.append(nv)
                except Exception:
                    pass
            if any(x in key for x in ("auth", "token", "h5", "wb")) and len(val) >= 16:
                candidates.append(val)
            elif len(val) >= 20 and re.fullmatch(r"[A-Za-z0-9._+=/-]+", val):
                candidates.append(val)

    for part in (cookies or "").split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        key = k.lower()
        if any(x in key for x in ("auth", "token", "h5", "wb")) and len(v) >= 16:
            candidates.append(v)
        elif len(v) >= 20 and re.fullmatch(r"[A-Za-z0-9._+=/-]+", v):
            candidates.append(v)
    uniq = []
    seen = set()
    for c in candidates:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def _probe_user_info(token: str, cookie: str) -> bool:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "h5-auth": token,
            "Content-Type": "application/json",
            "Origin": "https://zone.funplus.com",
            "Referer": "https://zone.funplus.com/tilessurvive/",
        }
        if cookie:
            headers["Cookie"] = cookie
        resp = requests.post(API_USER_INFO, json={}, headers=headers, timeout=20)
        data = resp.json()
        return isinstance(data, dict) and data.get("code") in (0, "0")
    except Exception:
        return False


def _pick_token(candidates: list[str], cookie: str) -> str:
    for token in sorted(candidates, key=len, reverse=True):
        if _probe_user_info(token, cookie):
            print(f"token 校验成功（长度 {len(token)}）", flush=True)
            return token
    return candidates[0] if candidates else ""


def _detect_repo() -> str:
    try:
        out = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        m = re.search(r"github\.com[:/]([^/]+/[^/.]+)", out)
        if m:
            return m.group(1)
    except Exception:
        pass
    return DEFAULT_REPO


def _push_secret(b64_path: Path, repo: str) -> bool:
    if not b64_path.exists():
        print("找不到 b64 文件，无法上传 Secret。", flush=True)
        return False
    try:
        subprocess.check_call(["gh", "auth", "status"], stdout=subprocess.DEVNULL)
    except Exception:
        print("gh 未登录。请先运行：gh auth login", flush=True)
        return False

    print(f"正在更新 GitHub Secret FUNPLUS_AUTH → {repo} …", flush=True)
    try:
        with b64_path.open("rb") as fh:
            subprocess.check_call(
                ["gh", "secret", "set", "FUNPLUS_AUTH", "--repo", repo],
                stdin=fh,
            )
        print("Secret 已更新成功。", flush=True)
        return True
    except subprocess.CalledProcessError as exc:
        print(f"Secret 更新失败：{exc}", flush=True)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="导出 FunPlus 登录态")
    parser.add_argument(
        "--push-secret",
        action="store_true",
        help="导出成功后自动更新 GitHub Secret FUNPLUS_AUTH",
    )
    parser.add_argument(
        "--repo",
        default="",
        help="目标仓库，默认自动检测 origin 或 LiJT/Funplus-Check",
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("即将打开 Chromium（Chrome for Testing），请手动登录 FunPlus Zone。", flush=True)
    print(f"登录成功后脚本会自动导出（最长等待 {POLL_SECONDS} 秒）…", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(locale="zh-CN")
        page = context.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")

        deadline = time.time() + POLL_SECONDS
        live = {}
        chosen = ""
        while time.time() < deadline:
            page.wait_for_timeout(POLL_INTERVAL * 1000)
            try:
                if "zone.funplus.com" not in (page.url or ""):
                    page.goto(LOGIN_URL, wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)
                live = _extract_live(page)
            except Exception as exc:
                print(f"读取页面状态失败：{exc}", flush=True)
                continue

            candidates = _candidate_tokens(live.get("ls") or {}, live.get("cookie") or "")
            ls_keys = sorted((live.get("ls") or {}).keys())
            print(
                f"轮询中… loginButtons={live.get('loginButtons')} "
                f"ls_keys={len(ls_keys)} candidates={len(candidates)} url={live.get('href')}",
                flush=True,
            )

            if candidates:
                chosen = _pick_token(candidates, live.get("cookie") or "")
                if chosen and _probe_user_info(chosen, live.get("cookie") or ""):
                    print("已检测到有效登录态，开始导出…", flush=True)
                    break

            try:
                btn = page.get_by_role(
                    "button", name=re.compile(r"Log In|登录|登入", re.I)
                ).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=1500)
                    print("已点击登录入口", flush=True)
                    page.wait_for_timeout(1000)
            except Exception:
                pass
        else:
            diag = {
                "href": (live or {}).get("href"),
                "loginButtons": (live or {}).get("loginButtons"),
                "ls_keys": sorted(((live or {}).get("ls") or {}).keys()),
                "ls_preview": {
                    k: (str(v)[:40] + ("…" if len(str(v)) > 40 else ""))
                    for k, v in ((live or {}).get("ls") or {}).items()
                },
                "cookie": (live or {}).get("cookie"),
            }
            (OUT_DIR / "export_debug.json").write_text(
                json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print("超时：仍未检测到可用登录态。已写入 .auth/export_debug.json", flush=True)
            context.close()
            browser.close()
            return 1

        page.wait_for_timeout(1500)
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            live = _extract_live(page)
            candidates = _candidate_tokens(live.get("ls") or {}, live.get("cookie") or "")
            if candidates:
                probed = _pick_token(candidates, live.get("cookie") or "")
                if probed:
                    chosen = probed
        except Exception:
            pass

        storage = context.storage_state()
        extracted = extract_token_from_storage(storage)
        h5_auth = chosen or extracted.get("h5_auth") or ""
        fp_uid = extracted.get("fp_uid") or ""

        payload = {
            "h5_auth": h5_auth,
            "fp_uid": fp_uid,
            "cookies": live.get("cookie") or "",
            "storage_state": storage,
            "export_url": live.get("href"),
            "localStorage_keys": sorted((live.get("ls") or {}).keys()),
        }

        json_path = OUT_DIR / "funplus_auth.json"
        b64_path = OUT_DIR / "funplus_auth.b64.txt"
        raw = json.dumps(payload, ensure_ascii=False)
        json_path.write_text(raw, encoding="utf-8")
        b64_path.write_text(
            base64.b64encode(raw.encode("utf-8")).decode("ascii"), encoding="utf-8"
        )

        context.close()
        browser.close()

    print(f"\n已导出：{json_path}", flush=True)
    print(f"Base64：{b64_path}", flush=True)
    if not h5_auth:
        print("警告：未提取到 h5-auth，Actions 可能无法调 API；请重试登录。", flush=True)
        return 1
    print(f"h5-auth 长度：{len(h5_auth)}", flush=True)

    if args.push_secret:
        repo = args.repo.strip() or _detect_repo()
        if not _push_secret(b64_path, repo):
            return 2
        print("\n完成：本地登录态已刷新，GitHub Actions 将使用新 Secret。", flush=True)
    else:
        print(
            "\n如需同步到 GitHub，请运行：\n"
            "  refresh_auth.bat\n"
            "或：\n"
            "  python -u export_auth.py --push-secret",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
