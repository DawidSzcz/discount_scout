# /// script
# dependencies = ["curl_cffi", "selectolax"]
# ///
import json, re, sys, time, random
from curl_cffi import requests
from selectolax.lexbor import LexborHTMLParser as HTMLParser

URLS = {
    "asus_estore": "https://estore.asus.com/pl/90nb16v1-m00uw0-asus-zenbook-duo-ux8407-copilot-pc.html",
    "xkom": "https://www.x-kom.pl/p/1610557-laptop-14-asus-zenbook-duo-ultra-x9-378h-32gb-1tb-win11p-oled.html",
    "komputronik": "https://www.komputronik.pl/product/1016402/laptop-asus-zenbook-duo-oled-ux8407aa-sn515x-ultra-x9-378h-14-3k-144hz-dotyk-32gb-1tb-w11p.html",
    "euro": "https://www.euro.com.pl/laptopy-i-netbooki/asus-laptop-asus-zd-14-32-1-w11p-touch.bhtml",
    "mediaexpert": "https://www.mediaexpert.pl/komputery-i-tablety/laptopy-i-ultrabooki/laptopy/laptop-asus-zenbook-duo-ux8407aa-sn515x-14-oled-144hz-ultra-x9-378h-32gb-ram-1tb-ssd-windows-11-professional-funkcje-ai",
    "neonet": "https://www.neonet.pl/p/1610557-laptop-asus-zenbook-duo-ultra-x9-378h-32gb-1tb-win11p-oled.html",
    "deluxury": "https://deluxury.pl/pl/p/Laptop-Asus-ZenBook-Duo-OLED-UX8407AA-SN515X-Ultra-X9-378H-32GB-1TB-W11P/41974",
    "techlord": "https://techlord.pl/asus-zenbook-duo-ux8407aa-ultra-x9-378h32gb1tbw11p-oled-144hz-dotyk-p-39087.html",
    "allegro": "https://allegro.pl/produkt/laptop-asus-zenbook-duo-oled-ux8407aa-sn515x-ultra-x9-378h-32gb-1tb-w11p-ea537f82-3ea8-41c2-938d-e532122b7881?offerId=18824244324",
    "empik": "https://www.empik.com/asus-zenbook-duo-oled-ux8407aa-sn515x-ultra-x9-378h-14-3k-144hz-dotyk-32gb-1tb-w11p-asus,p1778781306,elektronika-p",
    "ceneo": "https://www.ceneo.pl/199125559",
    "morele": "https://www.morele.net/laptop-asus-zenbook-duo-oled-ux8407-ultra-7-355-32-gb-1-tb-w11-pro-144-hz-ux8407aa-sn129x-16224566/",
    "oleole": "https://www.oleole.pl/laptopy-i-netbooki/asus-laptop-asus-zd-14-ux9-32-1-w11p.bhtml",
    "electro": "https://www.electro.pl/komputery-i-tablety/laptopy-i-ultrabooki/laptopy/laptop-asus-zenbook-duo-ux8407aa-sn129x-14-oled-144hz-ultra-7-355-32gb-ram-1tb-ssd-windows-11-professional-funkcje-ai",
    "avans": "https://www.avans.pl/komputery-i-tablety/laptopy-i-ultrabooki/laptopy/laptop-asus-zenbook-duo-ux8407aa-sn129x-14-oled-144hz-ultra-7-355-32gb-ram-1tb-ssd-windows-11-professional-funkcje-ai",
    "mediamarkt": "https://mediamarkt.pl/pl/product/_laptop-asus-zenbook-14-um3406ga-qd013w-wuxga-oled-amd-ryzentmai-5-430-16-gb-ram-512-gb-ssd-radeontm-windows-11-home-czarny-jade-black-1502711.html",
}

CHALLENGE = ["cf-chl", "challenge-platform", "turnstile", "captcha", "datadome", "px-captcha",
             "perimeterx", "Just a moment", "Access Denied", "akamai", "_Incapsula", "kpsdk"]

def find_products(obj, out):
    if isinstance(obj, dict):
        t = obj.get("@type")
        ts = t if isinstance(t, list) else [t]
        if "Product" in ts or "Offer" in ts or "AggregateOffer" in ts:
            out.append(obj)
        for v in obj.values():
            find_products(v, out)
    elif isinstance(obj, list):
        for v in obj:
            find_products(v, out)

def summarize(p):
    offers = p.get("offers") if p.get("@type") != "Offer" else p
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    offers = offers or {}
    return {k: v for k, v in {
        "type": p.get("@type"), "name": (p.get("name") or "")[:70],
        "sku": p.get("sku") or p.get("mpn"), "gtin": p.get("gtin13") or p.get("gtin"),
        "price": offers.get("price") or offers.get("lowPrice"),
        "cur": offers.get("priceCurrency"), "avail": str(offers.get("availability", ""))[-12:],
        "offerCount": offers.get("offerCount"),
    }.items() if v}

out_dir = sys.argv[1]
results = {}
for name, url in URLS.items():
    r = {"url": url}
    try:
        resp = requests.get(url, impersonate="chrome", timeout=30,
                            headers={"Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8"})
        html = resp.text
        open(f"{out_dir}/{name}.html", "w").write(html)
        r["status"] = resp.status_code
        r["bytes"] = len(html)
        r["challenge"] = [c for c in CHALLENGE if c.lower() in html.lower()][:4]
        tree = HTMLParser(html)
        r["title"] = (tree.css_first("title").text(strip=True)[:80] if tree.css_first("title") else None)
        prods = []
        for s in tree.css('script[type="application/ld+json"]'):
            try:
                find_products(json.loads(s.text()), prods)
            except Exception:
                pass
        r["jsonld"] = [summarize(p) for p in prods][:3]
        r["has_SN515X"] = "SN515X" in html
        r["has_meta_price"] = bool(re.search(r'itemprop="price"|product:price:amount', html))
        r["next_data"] = "__NEXT_DATA__" in html or "__NUXT__" in html or "window.__INITIAL_STATE__" in html
    except Exception as e:
        r["error"] = repr(e)[:150]
    results[name] = r
    print(name, json.dumps({k: v for k, v in r.items() if k != "url"}, ensure_ascii=False), flush=True)
    time.sleep(random.uniform(2, 4))

json.dump(results, open(f"{out_dir}/results.json", "w"), indent=1, ensure_ascii=False)
