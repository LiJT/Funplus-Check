"""Browser helpers for session bootstrap and community browsing."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

ZONE_HOME = "https://zone.funplus.com/tilessurvive?community-app=%2Fhome"
ZONE_BASE = "https://zone.funplus.com/tilessurvive"


async def create_context(
    storage_state: Optional[Dict[str, Any]] = None,
    headless: bool = True,
) -> tuple[Any, Browser, BrowserContext]:
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=headless)
    context = await browser.new_context(
        storage_state=storage_state,
        locale="zh-CN",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
    )
    return playwright, browser, context


async def read_auth_from_page(page: Page) -> Dict[str, str]:
    """Inspect localStorage/cookies inside a live page for h5 auth token."""
    data = await page.evaluate(
        """() => {
          const ls = {};
          for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            ls[k] = localStorage.getItem(k);
          }
          return { ls, cookie: document.cookie };
        }"""
    )
    ls = data.get("ls") or {}
    cookie = data.get("cookie") or ""
    h5_auth = ""
    fp_uid = ""
    candidates: List[str] = []

    for key, value in ls.items():
        if not value:
            continue
        lower = str(key).lower()
        val = str(value)
        if any(x in lower for x in ("auth", "token", "h5")) and len(val) > 20:
            candidates.append(val)
        if "fp_uid" in lower or "fpuid" in lower:
            fp_uid = val
        if len(val) >= 32 and re.fullmatch(r"[A-Za-z0-9._+=/-]+", val):
            candidates.append(val)

    for part in cookie.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        lower = key.lower()
        if any(x in lower for x in ("auth", "token", "h5")) and len(value) > 20:
            candidates.append(value)
        if "fp_uid" in lower or "fpuid" in lower:
            fp_uid = value

    if candidates:
        h5_auth = max(candidates, key=len)
    return {"h5_auth": h5_auth, "fp_uid": fp_uid}


async def ensure_logged_in(page: Page, timeout_ms: int = 20000) -> bool:
    await page.goto(f"{ZONE_BASE}/benefits", wait_until="domcontentloaded")
    try:
        # Logged-out pages show a prominent Log In button / CTA.
        login_visible = await page.get_by_role("button", name=re.compile("Log In|登录|登入", re.I)).count()
        # Also probe localStorage token
        auth = await read_auth_from_page(page)
        if auth.get("h5_auth"):
            return True
        if login_visible > 0:
            # Wait a bit for SPA hydration then recheck
            await page.wait_for_timeout(2500)
            auth = await read_auth_from_page(page)
            if auth.get("h5_auth"):
                return True
            text = await page.locator("body").inner_text(timeout=timeout_ms)
            if re.search(r"Log in to|登录.*账号|登入.*帳戶", text, re.I):
                return False
        return bool(auth.get("h5_auth"))
    except Exception:
        auth = await read_auth_from_page(page)
        return bool(auth.get("h5_auth"))


async def browse_community_posts(page: Page, target: int = 5) -> Dict[str, Any]:
    """Open community home and visit several post detail pages."""
    visited: List[str] = []
    discovered: List[str] = []

    def _on_response(response) -> None:
        try:
            url = response.url
            if any(
                k in url.lower()
                for k in ("article", "post", "feed", "dynamic", "thread", "content/detail")
            ):
                discovered.append(url)
        except Exception:
            pass

    page.on("response", _on_response)
    await page.goto(ZONE_HOME, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)

    # Community may load inside iframe / wujie micro-app. Collect candidate links broadly.
    hrefs = await page.evaluate(
        """() => {
          const out = [];
          const push = (href) => {
            if (!href) return;
            if (href.startsWith('javascript:')) return;
            if (out.includes(href)) return;
            if (/article|post|detail|thread|feed|dynamic|content|community/i.test(href)) out.push(href);
          };
          document.querySelectorAll('a[href]').forEach(a => {
            const raw = a.getAttribute('href') || '';
            const abs = raw.startsWith('/') ? (location.origin + raw) : a.href;
            push(abs);
          });
          document.querySelectorAll('[data-id], [data-article-id], [data-post-id]').forEach(el => {
            const id = el.getAttribute('data-id') || el.getAttribute('data-article-id') || el.getAttribute('data-post-id');
            if (id) push(location.origin + location.pathname + '?community-app=%2Farticle%2F' + id);
          });
          document.querySelectorAll('iframe').forEach(f => {
            try {
              f.contentDocument && f.contentDocument.querySelectorAll('a[href]').forEach(a => push(a.href));
            } catch (e) {}
          });
          document.querySelectorAll('*').forEach(el => {
            if (el.shadowRoot) {
              el.shadowRoot.querySelectorAll('a[href]').forEach(a => push(a.href));
            }
          });
          return out;
        }"""
    )

    # Also synthesize detail URLs from zone community-app deep links found in page HTML
    html = await page.content()
    for match in re.findall(r"community-app=%2F([^\\&\"']+)", html):
        decoded = match.replace("%2F", "/")
        discovered.append(f"{ZONE_BASE}?community-app=%2F{match}")
        if any(k in decoded.lower() for k in ("article", "post", "detail", "dynamic")):
            hrefs.append(f"{ZONE_BASE}?community-app=%2F{match}")

    # Deduplicate while preserving order
    ordered: List[str] = []
    for href in list(hrefs) + discovered:
        if href not in ordered:
            ordered.append(href)

    # Fallback: clickable cards in main page listing
    if not ordered:
        cards = page.locator(
            "[class*='post'], [class*='feed'], [class*='article'], [class*='card'], [class*='Item']"
        )
        count = await cards.count()
        for i in range(min(count, target)):
            card = cards.nth(i)
            try:
                await card.click(timeout=3000)
                await page.wait_for_timeout(2500)
                visited.append(page.url)
                await page.go_back(wait_until="domcontentloaded")
                await page.wait_for_timeout(1500)
            except Exception as exc:
                print(f"社区卡片点击失败 #{i+1}: {exc}")
        return {"visited": visited, "count": len(visited), "mode": "card-click"}

    for href in ordered:
        if len(visited) >= target:
            break
        if href in visited:
            continue
        # Skip pure asset/API noise
        if any(href.lower().endswith(ext) for ext in (".js", ".css", ".png", ".jpg", ".svg", ".woff")):
            continue
        try:
            await page.goto(href, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2500)
            visited.append(href)
            print(f"已浏览帖子：{href}")
        except Exception as exc:
            print(f"打开帖子失败：{href} ({exc})")

    # Return to task center for claim UI if needed
    try:
        await page.goto(f"{ZONE_BASE}/benefits/pointstask", wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
    except Exception:
        pass

    return {"visited": visited, "count": len(visited), "mode": "href"}


async def click_claim_buttons(page: Page) -> List[str]:
    """Best-effort UI claim for any visible 领取/Claim buttons on task page."""
    claimed: List[str] = []
    await page.goto(f"{ZONE_BASE}/benefits/pointstask", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)
    buttons = page.get_by_role("button", name=re.compile(r"领取|Claim|領取", re.I))
    count = await buttons.count()
    for i in range(count):
        btn = buttons.nth(i)
        try:
            name = (await btn.inner_text()).strip()
            await btn.click(timeout=3000)
            await page.wait_for_timeout(1200)
            claimed.append(name or f"button-{i+1}")
        except Exception as exc:
            print(f"UI 领取点击失败：{exc}")
    return claimed


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)
