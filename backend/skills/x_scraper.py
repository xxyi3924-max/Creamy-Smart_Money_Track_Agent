"""
X (Twitter) Post Scraper — Playwright + Cookie Injection
---------------------------------------------------------
Replaces twscrape (which caused 15-min account lockouts on expired cookies)
with a real Chromium browser that injects session cookies directly.

No login API calls → no lockout risk.
Works as long as auth_token + ct0 cookies are valid.

Env vars (set in .env):
    X_AUTH_TOKEN   — auth_token cookie from DevTools → Application → Cookies
    X_CT0          — ct0 cookie (CSRF token)
    X_GUEST_ID     — optional, helps avoid login redirect

Install:
    pip install playwright
    playwright install chromium
"""

import asyncio
import os

_TIMEOUT = 35          # total seconds (browser launch + page load + scrolling)
_MAX_POSTS = 30        # posts to collect per run
_SCROLL_STALL_LIMIT = 4  # stop after this many scrolls with no new posts

BULLISH_TERMS = {
    "bullish", "calls", "moon", "buy", "long", "breakout",
    "squeeze", "upside", "🚀", "📈", "beat", "surge", "rally", "upgrade",
}
BEARISH_TERMS = {
    "bearish", "puts", "short", "sell", "crash", "dump",
    "downside", "🐻", "📉", "miss", "cut", "warning", "downgrade",
}


def fetch_x_posts(ticker: str) -> dict:
    """Synchronous entry point. Runs Playwright in a dedicated event loop
    to avoid conflicts with uvicorn's running loop."""
    auth_token = os.getenv("X_AUTH_TOKEN", "").strip()
    ct0 = os.getenv("X_CT0", "").strip()

    if not auth_token or not ct0:
        return _empty()

    try:
        import playwright  # noqa — check if installed before spawning a loop
    except ImportError:
        print("[x_scraper] playwright not installed — skipping X data")
        return _empty()

    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                asyncio.wait_for(_scrape(ticker, auth_token, ct0), timeout=_TIMEOUT)
            )
        finally:
            loop.close()
    except asyncio.TimeoutError:
        print(f"[x_scraper] timed out after {_TIMEOUT}s")
        return _empty()
    except Exception as e:
        print(f"[x_scraper] error: {e}")
        return _empty()


async def _scrape(ticker: str, auth_token: str, ct0: str) -> dict:
    from playwright.async_api import async_playwright

    query = f"${ticker} OR #{ticker}stock lang:en -is:retweet"
    search_url = (
        f"https://x.com/search?q={query.replace(' ', '%20')}"
        f"&src=typed_query&f=live"
    )

    cookies = [
        {
            "name": "auth_token",
            "value": auth_token,
            "domain": ".x.com",
            "path": "/",
            "httpOnly": True,
            "secure": True,
            "sameSite": "None",
        },
        {
            "name": "ct0",
            "value": ct0,
            "domain": ".x.com",
            "path": "/",
            "httpOnly": False,
            "secure": True,
            "sameSite": "Lax",
        },
    ]

    guest_id = os.getenv("X_GUEST_ID", "").strip()
    if guest_id:
        cookies.append({
            "name": "guest_id",
            "value": guest_id,
            "domain": ".x.com",
            "path": "/",
            "httpOnly": False,
            "secure": True,
            "sameSite": "None",
        })

    collected = []
    seen: set[str] = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )

        await context.add_cookies(cookies)
        page = await context.new_page()

        # Remove automation fingerprint
        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )

        await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2500)

        # Bail if redirected to login — cookies are expired
        if "login" in page.url.lower():
            await browser.close()
            print("[x_scraper] cookies expired — redirected to login page")
            return _empty()

        stall_count = 0
        last_count = 0

        while len(collected) < _MAX_POSTS:
            tweet_els = await page.query_selector_all('article[data-testid="tweet"]')

            for tweet in tweet_els:
                if len(collected) >= _MAX_POSTS:
                    break
                try:
                    text_el = await tweet.query_selector('[data-testid="tweetText"]')
                    if not text_el:
                        continue
                    text = (await text_el.inner_text()).strip()
                    if not text or text in seen:
                        continue
                    seen.add(text)

                    likes = 0
                    try:
                        like_el = await tweet.query_selector('[data-testid="like"] span')
                        if like_el:
                            likes = _parse_count(await like_el.inner_text())
                    except Exception:
                        pass

                    collected.append({"text": text, "likes": likes})
                except Exception:
                    continue

            if len(collected) == last_count:
                stall_count += 1
                if stall_count >= _SCROLL_STALL_LIMIT:
                    break
            else:
                stall_count = 0

            last_count = len(collected)
            await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
            await page.wait_for_timeout(1800)

        await browser.close()

    if not collected:
        return _empty()

    bull_count = sum(1 for p in collected if _is_bullish(p["text"]))
    bear_count = sum(1 for p in collected if _is_bearish(p["text"]))
    bull_ratio = round(bull_count / len(collected), 2)

    top = sorted(collected, key=lambda p: p["likes"], reverse=True)[:3]
    sample_texts = [p["text"][:200] for p in top]

    return {
        "post_count": len(collected),
        "bull_ratio": bull_ratio,
        "bear_count": bear_count,
        "top_posts": top,
        "sample_texts": sample_texts,
    }


def _parse_count(text: str) -> int:
    """Parse display counts: '1.2K' → 1200, '5M' → 5000000."""
    text = text.strip().upper()
    if not text:
        return 0
    try:
        if text.endswith("K"):
            return int(float(text[:-1]) * 1000)
        if text.endswith("M"):
            return int(float(text[:-1]) * 1_000_000)
        return int(text.replace(",", ""))
    except (ValueError, TypeError):
        return 0


def _is_bullish(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in BULLISH_TERMS)


def _is_bearish(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in BEARISH_TERMS)


def _empty() -> dict:
    return {
        "post_count": 0,
        "bull_ratio": 0.5,
        "bear_count": 0,
        "top_posts": [],
        "sample_texts": [],
    }
