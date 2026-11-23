# /// script
# dependencies = ["playwright", "playwright-stealth"]
# ///
import json, re, sys, random, asyncio
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

sys.path.insert(0, sys.argv[2])
NAMES = ["ceneo", "allegro", "euro", "oleole", "mediaexpert", "electro", "avans",
         "komputronik", "asus_estore", "empik"]
URLS = json.load(open(f"{sys.argv[1]}/results.json"))

PRICE_RE = re.compile(r'(\d{1,2}[\s ]?\d{3}(?:,\d{2})?)\s?zł')

async def main():
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(locale="pl-PL", viewport={"width": 1366, "height": 850})
        for name in NAMES:
            url = URLS[name]["url"]
            page = await ctx.new_page()
            r = {}
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(8000)
                html = await page.content()
                open(f"{sys.argv[1]}/{name}.pw.html", "w").write(html)
                text = await page.inner_text("body")
                r["status"] = resp.status if resp else None
                r["title"] = (await page.title())[:80]
                r["bytes"] = len(html)
                r["jsonld_product"] = '"@type":"Product"' in html.replace(" ", "")
                r["has_model"] = "SN515X" in html or "SN129X" in html or "SN169X" in html
                r["prices"] = list(dict.fromkeys(PRICE_RE.findall(text)))[:5]
                r["blocked_words"] = [w for w in ["captcha", "Blokada", "Just a moment", "zweryfikuj", "robot", "Access denied"] if w.lower() in text.lower()]
            except Exception as e:
                r["error"] = repr(e)[:150]
            print(name, json.dumps(r, ensure_ascii=False), flush=True)
            await page.close()
            await asyncio.sleep(random.uniform(2, 5))
        await browser.close()

asyncio.run(main())
