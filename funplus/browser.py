"""Browser helpers for session bootstrap and community browsing."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

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
        if lower in ("priv-auth",) or (
            any(x in lower for x in ("auth", "token", "h5")) and len(value) > 20
        ):
            candidates.append(value)
        if lower in ("priv-auth-fpuid",) or "fp_uid" in lower or "fpuid" in lower:
            fp_uid = value

    if candidates:
        # Prefer priv-auth-like longer tokens
        h5_auth = max(candidates, key=len)
    return {"h5_auth": h5_auth, "fp_uid": fp_uid}


async def ensure_logged_in(page: Page, timeout_ms: int = 20000) -> bool:
    await page.goto(f"{ZONE_BASE}/benefits", wait_until="domcontentloaded")
    try:
        login_visible = await page.get_by_role(
            "button", name=re.compile("Log In|登录|登入", re.I)
        ).count()
        auth = await read_auth_from_page(page)
        if auth.get("h5_auth") and len(auth["h5_auth"]) >= 80:
            return True
        if login_visible > 0:
            await page.wait_for_timeout(2500)
            auth = await read_auth_from_page(page)
            if auth.get("h5_auth") and len(auth["h5_auth"]) >= 80:
                return True
            text = await page.locator("body").inner_text(timeout=timeout_ms)
            if re.search(r"Log in to|登录.*账号|登入.*帳戶", text, re.I):
                return False
        return bool(auth.get("h5_auth") and len(auth["h5_auth"]) >= 80)
    except Exception:
        auth = await read_auth_from_page(page)
        return bool(auth.get("h5_auth") and len(auth["h5_auth"]) >= 80)


def _article_detail_url(article: Dict[str, Any]) -> str:
    aid = article.get("id") or article.get("article_id")
    atype = article.get("type", 0)
    author = article.get("author_fpid", article.get("fpid", 0))
    app_path = f"/article/{aid}?type={atype}&author_fpid={author}"
    return (
        f"{ZONE_BASE}/communityDetail/articleDetail"
        f"?community-app={quote(app_path, safe='')}"
    )


async def browse_community_posts(page: Page, target: int = 5) -> Dict[str, Any]:
    """Open community home, capture latest articles, visit detail pages."""
    articles: List[Dict[str, Any]] = []
    visited: List[str] = []

    async def _on_response(response) -> None:
        nonlocal articles
        url = response.url
        if "vertical/article/lists" not in url:
            return
        if response.status != 200:
            return
        try:
            data = await response.json()
        except Exception:
            return
        payload = (data or {}).get("data") or {}
        items = payload.get("articles") or []
        if isinstance(items, list) and items:
            articles = [x for x in items if isinstance(x, dict) and x.get("id")]
            print(f"捕获到社区帖子列表：{len(articles)} 条")

    page.on("response", _on_response)
    await page.goto(ZONE_HOME, wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)

    # Retry once if list not captured (slow network / tab not ready)
    if not articles:
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_timeout(8000)

    if not articles:
        # Fallback: click cards inside page / wujie if API capture failed
        return await _browse_by_clicking_cards(page, target)

    for art in articles:
        if len(visited) >= target:
            break
        aid = art.get("id")
        url = _article_detail_url(art)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(4000)
            visited.append(str(aid))
            title = str(art.get("title") or aid)
            print(f"已浏览帖子：{aid} {title[:40]}")
        except Exception as exc:
            print(f"打开帖子失败：{aid} ({exc})")

    try:
        await page.goto(f"{ZONE_BASE}/benefits/pointstask", wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
    except Exception:
        pass

    return {
        "visited": visited,
        "count": len(visited),
        "mode": "article-detail",
        "available": len(articles),
    }


async def _browse_by_clicking_cards(page: Page, target: int) -> Dict[str, Any]:
    visited: List[str] = []
    print("未捕获到帖子 API，改用页面点击兜底…")
    # Try clicking in main frame and known iframe
    frames = [page] + [
        f for f in page.frames if "community" in (f.url or "") or f.name == "community-app"
    ]
    for frame in frames:
        cards = frame.locator(
            ".article-item, .article_item, [class*='article'], [class*='ArticleCard'], "
            "[class*='feed-item'], [class*='list-item']"
        )
        try:
            count = await cards.count()
        except Exception:
            count = 0
        for i in range(min(count, target * 2)):
            if len(visited) >= target:
                break
            card = cards.nth(i)
            try:
                await card.click(timeout=3000)
                await page.wait_for_timeout(3500)
                visited.append(page.url)
                await page.goto(ZONE_HOME, wait_until="domcontentloaded")
                await page.wait_for_timeout(2500)
            except Exception as exc:
                print(f"社区卡片点击失败 #{i+1}: {exc}")
    return {"visited": visited, "count": len(visited), "mode": "card-click"}


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


async def claim_benefit_packs(page: Page) -> List[str]:
    """Visit /benefits/pack and click any enabled claim buttons (weekly/level packs)."""
    claimed: List[str] = []
    await page.goto(f"{ZONE_BASE}/benefits/pack", wait_until="domcontentloaded")
    await page.wait_for_timeout(4500)

    # Match Claim Now / 立即領取 / 领取, but skip disabled Already Claimed buttons.
    pattern = re.compile(r"立即[领取領取]|领取|領取|Claim\s*Now", re.I)
    skip_pattern = re.compile(r"已[领取領取]|Already\s*Claimed|Claimed", re.I)

    for _ in range(6):
        buttons = page.get_by_role("button", name=pattern)
        count = await buttons.count()
        clicked_any = False
        for i in range(count):
            btn = buttons.nth(i)
            try:
                if not await btn.is_enabled():
                    continue
                label = (await btn.inner_text()).strip()
                if not label or skip_pattern.search(label):
                    continue
                await btn.click(timeout=4000)
                await page.wait_for_timeout(1800)
                claimed.append(label)
                clicked_any = True
            except Exception as exc:
                print(f"礼包页领取点击失败：{exc}")
        if not clicked_any:
            break
        await page.wait_for_timeout(1500)
    return claimed


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)
