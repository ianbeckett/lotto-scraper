"""
Scraper for Oregon Lottery's scratch-it ("Scratch-its") prize data.

Unlike WA Lottery, Oregon's site (oregonlottery.org, WordPress) renders its
scratch-it list and individual game pages with client-side JavaScript - a
plain HTTP GET returns an HTML shell with empty placeholders where the
numbers should be (verified directly: a raw fetch() of a game page is
missing "Prizes Left", the "$X.XX" ticket cost, etc., even though the
rendered page shows them). The real numbers come from Oregon Lottery's own
backend (api.oregonlottery.org/gameinfo/v1/instant/games), but that
endpoint requires a client_id/client_secret pair that ships inside the
site's own JS bundle - built for Oregon Lottery's own frontend, not for a
third party to lift out and reuse against their production API on a
recurring schedule. Rather than extract and reuse that credential, this
module drives a real (headless) browser with Playwright and reads the same
numbers any visitor's browser renders on-screen - same spirit as the WA
scraper (reading what the public site displays), just via rendering
instead of a plain HTTP GET, because Oregon's site needs JS to populate
the page. Oregon's own list page says prize data is "updated once daily",
so this is meant to run daily, not hourly like WA's.

Two page types, both DOM structures confirmed by directly inspecting the
live, rendered site (class names below are real, not guessed):

1. The scratch-its list page (oregonlottery.org/scratch-its/list/) is a
   DataTables-powered <table class="ol-table"> listing every game
   currently for sale: game number, name (+ link to its detail page),
   price, top prize, top-prize-unclaimed count, and percent sold.
   DataTables paginates this client-side by default (40 rows/page, no URL
   param - it's all in-page JS state), but its own jQuery API can be told
   to show every row on one page (`.DataTable().page.len(-1).draw()`),
   which avoids clicking through pages.

2. Each individual game detail page (oregonlottery.org/scratch-its/<slug>/)
   has a `.ol-gamedata-scratchit__financials` block (ticket cost / top
   prize / overall odds), a `.ol-gamedata-scratchit__quick-facts-section`
   block (percent tickets sold, on-sale date, last day to buy, last day to
   claim a prize), and a flat list of `.ol-odds-payouts-scratchits__result`
   elements under `.ol-odds-payouts-scratchits__results` - 5 per prize
   tier, always in the order Prize / Odds / Total Prizes / Prizes Claimed /
   Prizes Left, repeated once per tier. There's a "Load More" button
   (`.ol-odds-payouts-scratchits__load-more`), but it turned out to be a
   pure CSS reveal, not a data-loading action: every tier's
   `.ol-odds-payouts-scratchits__result` element is already present in the
   DOM on first load (confirmed directly - querying the selector returned
   all tiers before ever clicking the button), so no click is needed here.

IMPORTANT: this has NOT been executed against the live site from inside
the sandbox this was written in - oregonlottery.org isn't reachable from
there (outbound network is allowlisted and doesn't include it). Every
selector and text pattern above was verified by directly inspecting the
live, rendered page instead, but that's not a substitute for actually
running this. Treat the first real run (locally, or a manual
`workflow_dispatch` run in Actions) as the real test, and check its
`warnings` output - if Oregon changes their markup, the most likely
symptom is "0 games found" or a spike in per-game warnings below.
"""

import re
import time

from playwright.sync_api import sync_playwright

import multistate

STATE = "OR"
LIST_URL = "https://www.oregonlottery.org/scratch-its/list/"
BASE_URL = "https://www.oregonlottery.org"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Third-party ad/analytics domains observed firing continuously on this
# site (doubleclick, GA, Meta pixel, Taboola, Vimeo embeds). Blocking them
# - plus images/fonts/media, which we never need since we only read text
# and the og:image URL attribute - cuts ~50 page loads down significantly
# and avoids flakiness from waiting on third parties that have nothing to
# do with the data we want. If scraping breaks in a way that looks
# network-related, try disabling this block first.
BLOCKED_DOMAINS = (
    "doubleclick.net",
    "google-analytics.com",
    "analytics.google.com",
    "googletagmanager.com",
    "facebook.net",
    "facebook.com",
    "taboola.com",
    "vimeocdn.com",
    "player.vimeo.com",
    "googlesyndication.com",
)
BLOCKED_RESOURCE_TYPES = ("image", "font", "media")


def _block_trackers(route):
    request = route.request
    url = request.url
    if request.resource_type in BLOCKED_RESOURCE_TYPES or any(d in url for d in BLOCKED_DOMAINS):
        route.abort()
    else:
        route.continue_()


def _to_number(text):
    """Parse '$2,000,000' / '36,802' / '1' / '76%' -> int/float, or None."""
    if text is None:
        return None
    cleaned = text.replace("$", "").replace(",", "").replace("%", "").strip()
    if not cleaned:
        return None
    try:
        if "." in cleaned:
            return float(cleaned)
        return int(cleaned)
    except ValueError:
        return None


def fetch_roster(page, timeout=20000):
    """Load the scratch-its list page and return every currently-for-sale
    game's roster row (game_number, name, slug, price, plus the list
    page's own top-prize/unclaimed/pct-sold columns, kept only as a
    cross-check - the authoritative numbers for each game come from that
    game's own detail page, scraped separately)."""
    page.goto(LIST_URL, wait_until="domcontentloaded", timeout=timeout)
    page.wait_for_selector("table.ol-table tbody tr", timeout=timeout)

    # DataTables paginates client-side (no URL param); ask its own jQuery
    # API to show every row on one page instead of clicking "Next".
    page.evaluate("jQuery('table.ol-table').DataTable().page.len(-1).draw()")
    page.wait_for_timeout(300)

    rows = page.query_selector_all("table.ol-table tbody tr")
    roster = []
    for tr in rows:
        tds = tr.query_selector_all("td")
        if len(tds) < 6:
            continue
        link = tr.query_selector('a[href*="/scratch-its/"]')
        href = link.get_attribute("href") if link else None
        slug = None
        if href:
            m = re.search(r"/scratch-its/([^/]+)/?", href)
            slug = m.group(1) if m else None
        roster.append({
            "game_number": tds[0].inner_text().strip(),
            "name": tds[1].inner_text().strip(),
            "slug": slug,
            "price": tds[2].inner_text().strip(),
            "list_top_prize": _to_number(tds[3].inner_text()),
            "list_unclaimed": _to_number(tds[4].inner_text()),
            "list_pct_sold": _to_number(tds[5].inner_text()),
        })
    return roster


def scrape_game_detail(page, slug, timeout=20000):
    """Load one game's detail page. Returns (tiers, extra_fields)."""
    url = f"{BASE_URL}/scratch-its/{slug}/"
    page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    page.wait_for_selector(".ol-odds-payouts-scratchits__result", timeout=timeout)

    financials_el = page.query_selector(".ol-gamedata-scratchit__financials")
    financials_text = financials_el.inner_text() if financials_el else ""

    facts_el = page.query_selector(".ol-gamedata-scratchit__quick-facts-section")
    facts_text = facts_el.inner_text() if facts_el else ""

    overall_odds_m = re.search(r"Overall Odds\s*(1 in [\d,.]+)", financials_text)
    overall_odds = overall_odds_m.group(1) if overall_odds_m else None

    pct_sold_m = re.search(r"([\d.]+)%\s*of Tickets Sold", facts_text)
    pct_tickets_sold = float(pct_sold_m.group(1)) if pct_sold_m else None

    on_sale_m = re.search(r"On Sale:\s*([\d/]+)", facts_text)
    on_sale_date = on_sale_m.group(1) if on_sale_m else None

    last_buy_m = re.search(r"Last Day to Buy:\s*([\d/]+)", facts_text)
    last_day_to_buy = last_buy_m.group(1) if last_buy_m else None

    # DOM text is "Last Day to" then (visually, via a line-break) "Claim a
    # Prize:" with no guaranteed whitespace between "to" and "Claim" once
    # flattened to inner_text - \s* handles it either way.
    last_claim_m = re.search(r"Last Day to\s*Claim a Prize:\s*([\d/]+)", facts_text)
    last_day_to_claim = last_claim_m.group(1) if last_claim_m else None

    # Flat list of 5-per-tier fields, always Prize/Odds/Total/Claimed/Left,
    # in that order (confirmed on a live 9-tier game) - see module docstring.
    result_els = page.query_selector_all(".ol-odds-payouts-scratchits__result")
    values = [el.inner_text().split(":", 1)[-1].strip() for el in result_els]

    tiers = []
    for i in range(0, len(values) - 4, 5):
        chunk = values[i:i + 5]
        amount = _to_number(chunk[0])
        total = _to_number(chunk[2])
        paid = _to_number(chunk[3])
        remaining = _to_number(chunk[4])
        if amount is None or total is None or remaining is None:
            continue
        tiers.append({"amount": amount, "total": total, "paid": paid, "remaining": remaining})

    og_image = page.query_selector('meta[property="og:image"]')
    image_url = og_image.get_attribute("content") if og_image else None

    extra = {
        "overall_odds": overall_odds,
        "pct_tickets_sold": pct_tickets_sold,
        "on_sale_date": on_sale_date,
        "last_day_to_buy": last_day_to_buy,
        "last_day_to_claim": last_day_to_claim,
        "image_url": image_url,
        "url": url,
    }
    return tiers, extra


def _build_game_record(roster_entry, tiers, extra):
    if not tiers:
        return None

    tiers_sorted = sorted(tiers, key=lambda t: t["amount"], reverse=True)
    top = tiers_sorted[0]

    total_prizes_total = sum(t["total"] for t in tiers_sorted)
    total_prizes_remaining = sum(t["remaining"] for t in tiers_sorted)
    remaining_cash_value = sum(t["amount"] * t["remaining"] for t in tiers_sorted)
    original_cash_value = sum(t["amount"] * t["total"] for t in tiers_sorted)

    def pct(numer, denom):
        return round((numer / denom) * 100, 2) if denom else None

    game_id = roster_entry["game_number"]

    return {
        "id": game_id,
        "state": STATE,
        "name": roster_entry["name"],
        "price": roster_entry["price"],
        "game_number": game_id,
        "last_day_to_redeem": extra["last_day_to_claim"],
        "explorer_url": extra["url"],
        "image_url": extra["image_url"],
        "top_prize_amount": top["amount"],
        "top_prize_total": top["total"],
        "top_prize_paid": top["paid"],
        "top_prize_remaining": top["remaining"],
        "top_prize_pct_remaining": pct(top["remaining"], top["total"]),
        "total_prizes_total": total_prizes_total,
        "total_prizes_remaining": total_prizes_remaining,
        "total_prizes_pct_remaining": pct(total_prizes_remaining, total_prizes_total),
        "remaining_cash_value": remaining_cash_value,
        "original_cash_value": original_cash_value,
        "cash_value_pct_remaining": pct(remaining_cash_value, original_cash_value),
        # Oregon's site doesn't expose anything like WA's "tickets printed".
        "tickets_printed": None,
        "overall_odds": extra["overall_odds"],
        "prize_tiers": tiers_sorted,
        # Oregon-specific extras with no WA equivalent. index.html only
        # reads fields it knows about for its default columns, so these
        # just ride along for anyone who wants them (e.g. a future
        # Oregon-specific column, or the per-game expanded detail view).
        "on_sale_date": extra["on_sale_date"],
        "last_day_to_buy": extra["last_day_to_buy"],
        "pct_tickets_sold": extra["pct_tickets_sold"],
    }


def scrape_all(progress_cb=None, polite_delay_seconds=0.3):
    """Scrape every currently-for-sale Oregon scratch-it game. Returns
    (games, warnings). Visits ~1 list page + 1 page per active game
    (roughly 50-60 total as of this writing), so this is meaningfully
    slower than WA's plain-HTTP scrape - expect low single-digit minutes,
    not seconds."""
    games = []
    warnings = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=USER_AGENT)
        page.route("**/*", _block_trackers)

        try:
            roster = fetch_roster(page)
        except Exception as e:
            browser.close()
            return [], [f"Failed to load Oregon scratch-its list page: {e}"]

        if not roster:
            warnings.append(
                "No games found on Oregon scratch-its list page - page layout may have changed."
            )

        for entry in roster:
            if not entry.get("slug"):
                warnings.append(
                    f"Skipped '{entry.get('name')}' (#{entry.get('game_number')}) - "
                    "no detail page link found."
                )
                continue
            try:
                tiers, extra = scrape_game_detail(page, entry["slug"])
                record = _build_game_record(entry, tiers, extra)
                if record is None:
                    warnings.append(
                        f"No prize tiers parsed for '{entry['name']}' "
                        f"(#{entry['game_number']}) - page layout may have changed."
                    )
                else:
                    games.append(record)
            except Exception as e:
                warnings.append(
                    f"Failed to scrape '{entry.get('name')}' (#{entry.get('game_number')}): {e}"
                )
            if progress_cb:
                progress_cb(entry.get("name"), len(games))
            time.sleep(polite_delay_seconds)

        browser.close()

    return games, warnings


def scrape_and_save(out_path="games.json"):
    games, warnings = scrape_all()
    return multistate.save_state_games(STATE, games, warnings, out_path=out_path)


if __name__ == "__main__":
    result = scrape_and_save()
    or_source = result["sources"]["OR"]
    print(f"Scraped {or_source['count']} Oregon games ({result['count']} total across all states).")
    if or_source["warnings"]:
        print("Warnings:")
        for w in or_source["warnings"]:
            print(" -", w)
