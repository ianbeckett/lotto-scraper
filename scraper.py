"""
Scraper for Washington's Lottery scratch ticket prize data.

Source: https://walottery.com/Scratch/TopPrizesRemaining.aspx?price=$X
This page is server-rendered HTML (unlike /Scratch/Explorer.aspx, which needs
JS to populate). Each price bracket page lists every active scratch game at
that price, with a full prize-tier breakdown table
(Prize Amount / Total Prizes / Prizes Paid / Prizes Remaining).

The parser below is written defensively: instead of depending on specific
CSS class names (which could change, and which we could not directly inspect
in raw HTML form), it walks the page in document order and pairs each game's
title link with the plain-text "$PRICE | GAME_NUMBER" line, an optional
"Last Day To Redeem: MM/DD/YY" line, and the <table> that follows it.
"""

import re
import time
import json

import requests
from bs4 import BeautifulSoup, Tag, NavigableString

import multistate

STATE = "WA"
BASE_URL = "https://walottery.com/Scratch/TopPrizesRemaining.aspx"
PRICE_BRACKETS = ["$1", "$2", "$3", "$5", "$10", "$20", "$30"]

# The Scratch Explorer page is JS-driven (the visible ticket popup shows
# "N/A" until JavaScript runs), but the data it renders from is embedded
# directly in the page's initial HTML as a plain JSON blob assigned to
# WaLottery.Scratch.data.all - a JS string literal, not fetched separately
# over the network. That means a plain server-side GET (no browser/JS
# execution needed) can read it. It covers every active game in one request,
# keyed by game Id, and includes "TicketsPrinted" and "OverallOdds", which
# aren't present anywhere in TopPrizesRemaining.aspx.
EXPLORER_URL = "https://walottery.com/Scratch/Explorer.aspx"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

PRICE_NUMBER_RE = re.compile(r"\$([\d,]+)\s*\|\s*(\d+)")
REDEEM_RE = re.compile(r"Last Day To Redeem:\s*([\d/]+)")

# Non-greedy: the JSON blob itself never contains the literal 2-char
# sequence "')" (it's all double-quoted JSON with no embedded apostrophes -
# names like "S'MORE SLINGO" are HTML-entity-encoded as S&#39;MORE SLINGO in
# the source, specifically to avoid breaking out of this single-quoted JS
# string), so the first "')" reliably marks the true end of the "all" value.
EXPLORER_DATA_RE = re.compile(r"all\s*:\s*JSON\.parse\('(.*?)'\)\s*,\s*featured\s*:", re.S)


def _to_number(text):
    """Parse '$2,000,000' / '36,802' / '1' -> int (or float if it has cents)."""
    if text is None:
        return None
    cleaned = text.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        if "." in cleaned:
            return float(cleaned)
        return int(cleaned)
    except ValueError:
        return None


def fetch_price_page(price, session=None, timeout=20):
    sess = session or requests
    resp = sess.get(BASE_URL, params={"price": price}, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def fetch_explorer_extras(session=None, timeout=20):
    """Fetch Tickets Printed / Overall Odds for every active game.

    Reads the WaLottery.Scratch.data.all JSON blob embedded in the Scratch
    Explorer page's HTML (see EXPLORER_DATA_RE above). Returns a dict keyed
    by game id (string) -> {"tickets_printed": int|None, "overall_odds": str|None}.
    Returns {} if the page structure has changed and the blob can't be found
    or parsed - callers should treat that as "extras unavailable this run"
    rather than a hard failure, since the core prize-remaining data doesn't
    depend on this.
    """
    sess = session or requests
    resp = sess.get(EXPLORER_URL, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()

    m = EXPLORER_DATA_RE.search(resp.text)
    if not m:
        return {}

    try:
        payload = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}

    extras = {}
    for g in payload.get("Games", []):
        gid = g.get("Id")
        if gid is None:
            continue
        extras[str(gid)] = {
            "tickets_printed": _to_number(g.get("TicketsPrinted")),
            "overall_odds": g.get("OverallOdds") or None,
        }
    return extras


def parse_price_page(html, price_bracket):
    """Parse one price-bracket page into a list of game dicts."""
    soup = BeautifulSoup(html, "html.parser")

    games = []
    pending_name = None
    pending_id = None
    pending_price = None
    pending_number = None
    pending_redeem = None
    seen_link_hrefs = set()

    for el in soup.descendants:
        if isinstance(el, Tag) and el.name == "a" and el.get("href") and "Explorer.aspx" in el.get("href", ""):
            href = el["href"]
            text = el.get_text(strip=True)
            if text and href not in seen_link_hrefs:
                seen_link_hrefs.add(href)
                pending_name = text
                m = re.search(r"id=(\d+)", href)
                pending_id = m.group(1) if m else None
                pending_price = None
                pending_number = None
                pending_redeem = None

        elif isinstance(el, NavigableString):
            s = str(el).strip()
            if not s:
                continue
            m = PRICE_NUMBER_RE.search(s)
            if m:
                pending_price = "$" + m.group(1)
                pending_number = m.group(2)
                continue
            m2 = REDEEM_RE.search(s)
            if m2:
                pending_redeem = m2.group(1)

        elif isinstance(el, Tag) and el.name == "table":
            header_text = el.get_text(" ", strip=True)
            if "Prize Amount" not in header_text or "Prizes Remaining" not in header_text:
                continue

            rows = []
            trs = el.find_all("tr")
            for tr in trs[1:]:  # skip header row
                cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
                if len(cells) >= 4:
                    rows.append(cells[:4])

            if pending_name and rows:
                tiers = []
                for amount_s, total_s, paid_s, remaining_s in rows:
                    amount = _to_number(amount_s)
                    total = _to_number(total_s)
                    paid = _to_number(paid_s)
                    remaining = _to_number(remaining_s)
                    if amount is None or total is None or remaining is None:
                        continue
                    tiers.append({
                        "amount": amount,
                        "total": total,
                        "paid": paid,
                        "remaining": remaining,
                    })

                if tiers:
                    games.append(_build_game_record(
                        name=pending_name,
                        game_id=pending_id,
                        price=pending_price or price_bracket,
                        game_number=pending_number or pending_id,
                        last_day_to_redeem=pending_redeem,
                        tiers=tiers,
                    ))

            # reset per-game fields so a stray/duplicate table can't reuse stale data
            pending_price = None
            pending_number = None
            pending_redeem = None

    return games


def _build_game_record(name, game_id, price, game_number, last_day_to_redeem, tiers):
    tiers_sorted = sorted(tiers, key=lambda t: t["amount"], reverse=True)
    top = tiers_sorted[0]

    total_prizes_total = sum(t["total"] for t in tiers_sorted)
    total_prizes_remaining = sum(t["remaining"] for t in tiers_sorted)
    remaining_cash_value = sum(t["amount"] * t["remaining"] for t in tiers_sorted)
    original_cash_value = sum(t["amount"] * t["total"] for t in tiers_sorted)

    def pct(numer, denom):
        return round((numer / denom) * 100, 2) if denom else None

    return {
        "id": game_id,
        "state": STATE,
        "name": name,
        "price": price,
        "game_number": game_number,
        "last_day_to_redeem": last_day_to_redeem,
        "explorer_url": f"https://walottery.com/Scratch/Explorer.aspx?id={game_id}" if game_id else None,
        "image_url": f"https://walottery.com/scratch/assets/imgs/tickets/grid/{game_id}.jpg" if game_id else None,
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
        # Filled in later from fetch_explorer_extras(); default to None so
        # the field is always present even if that fetch fails.
        "tickets_printed": None,
        "overall_odds": None,
        "prize_tiers": tiers_sorted,
    }


def scrape_all(progress_cb=None):
    """Scrape every price bracket. Returns (games, warnings)."""
    games = []
    warnings = []
    with requests.Session() as sess:
        for price in PRICE_BRACKETS:
            try:
                html = fetch_price_page(price, session=sess)
                bracket_games = parse_price_page(html, price)
                if not bracket_games:
                    warnings.append(f"No games parsed for {price} bracket - page layout may have changed.")
                games.extend(bracket_games)
            except requests.RequestException as e:
                warnings.append(f"Failed to fetch {price} bracket: {e}")
            if progress_cb:
                progress_cb(price, len(games))
            time.sleep(0.5)  # be polite

        try:
            extras = fetch_explorer_extras(session=sess)
            if not extras:
                warnings.append("Tickets Printed / Overall Odds unavailable this run - Explorer page structure may have changed.")
        except requests.RequestException as e:
            extras = {}
            warnings.append(f"Failed to fetch Tickets Printed / Overall Odds: {e}")

    # de-dupe by game id (in case a game appears under multiple filters)
    deduped = {}
    for g in games:
        key = g["id"] or g["name"]
        deduped[key] = g

    for g in deduped.values():
        extra = extras.get(g["id"])
        if extra:
            g["tickets_printed"] = extra["tickets_printed"]
            g["overall_odds"] = extra["overall_odds"]

    return list(deduped.values()), warnings


def scrape_and_save(out_path="games.json"):
    games, warnings = scrape_all()
    return multistate.save_state_games(STATE, games, warnings, out_path=out_path)


if __name__ == "__main__":
    result = scrape_and_save()
    print(f"Scraped {result['count']} games.")
    if result["warnings"]:
        print("Warnings:")
        for w in result["warnings"]:
            print(" -", w)
