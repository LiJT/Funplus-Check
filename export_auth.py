#!/usr/bin/env python3
"""
本地导出 FunPlus 登录态（Cookie + localStorage），用于 GitHub Actions。

用法：
  pip install -r requirements.txt
  playwright install chromium
  python export_auth.py

浏览器打开后请手动完成邮箱验证码登录；脚本检测到登录成功后会写出：
  .auth/funplus_auth.json
  .auth/funplus_auth.b64.txt   （可直接粘贴到 GitHub Secret: FUNPLUS_AUTH）
"""

from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from funplus.client import extract_token_from_storage

LOGIN_URL = "https://zone.funplus.com/tilessurvive/benefits"
OUT_DIR = Path(".auth")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("即将打开浏览器，请手动登录 FunPlus Zone（邮箱验证码）。")
    print("登录成功并进入福利页后，回到终端按 Enter 继续导出…")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(locale="zh-CN")
        page = context.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")

        input(">>> 登录完成后按 Enter 导出登录态：")

        # Give SPA a moment to persist tokens
        page.wait_for_timeout(1500)
        storage = context.storage_state()
        extracted = extract_token_from_storage(storage)

        # Also read live localStorage as a stronger signal
        live = page.evaluate(
            """() => {
              const ls = {};
              for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                ls[k] = localStorage.getItem(k);
              }
              return { ls, cookie: document.cookie, href: location.href };
            }"""
        )
        ls = live.get("ls") or {}
        if not extracted.get("h5_auth"):
            candidates = []
            for k, v in ls.items():
                if not v:
                    continue
                if any(x in str(k).lower() for x in ("auth", "token", "h5")) and len(str(v)) > 20:
                    candidates.append(str(v))
                elif len(str(v)) >= 32 and re.fullmatch(r"[A-Za-z0-9._\\-=]+", str(v)):
                    candidates.append(str(v))
            if candidates:
                extracted["h5_auth"] = max(candidates, key=len)

        cookie_header = live.get("cookie") or ""
        payload = {
            "h5_auth": extracted.get("h5_auth") or "",
            "fp_uid": extracted.get("fp_uid") or "",
            "cookies": cookie_header,
            "storage_state": storage,
            "export_url": live.get("href"),
            "localStorage_keys": sorted(ls.keys()),
        }

        json_path = OUT_DIR / "funplus_auth.json"
        b64_path = OUT_DIR / "funplus_auth.b64.txt"
        raw = json.dumps(payload, ensure_ascii=False)
        json_path.write_text(raw, encoding="utf-8")
        b64_path.write_text(base64.b64encode(raw.encode("utf-8")).decode("ascii"), encoding="utf-8")

        context.close()
        browser.close()

    print(f"\n已导出：{json_path}")
    print(f"Base64：{b64_path}")
    if payload["h5_auth"]:
        print(f"检测到 h5-auth（长度 {len(payload['h5_auth'])}）")
    else:
        print("警告：未检测到明显的 h5-auth，请确认已登录成功后再导出。")
        return 1

    print(
        "\n下一步：\n"
        "1. 打开 GitHub 仓库 Settings → Secrets and variables → Actions\n"
        "2. 新建 Secret 名称：FUNPLUS_AUTH\n"
        "3. 把 funplus_auth.b64.txt 的全部内容粘贴进去\n"
        "4. （可选）PUSHPLUS_TOKEN 用于推送\n"
        "5. Actions 里手动 Run workflow 测试\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
