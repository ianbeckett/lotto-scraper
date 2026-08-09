"""
Shared helpers for merging one state's scrape results into the combined
games.json that index.html reads.

games.json holds every state's games in a single flat "games" array (each
tagged with a "state" field: "WA" / "OR" / ...), plus a "sources" object
carrying per-state scrape metadata (scraped_at / count / warnings). This
split exists because each state scrapes on its own schedule - WA hourly
(scraper.py, plain HTML requests), OR daily (scraper_oregon.py, headless
browser render, much heavier per-run) - so one state's scheduled run must
never clobber another state's already-current data. save_state_games()
below is the only thing that writes games.json; it replaces just the
calling state's games and source metadata, leaving everything else as-is.

Each game's "id" (as returned by the individual scrapers) is only unique
*within* that state - WA and OR both hand out small integer game numbers
independently, so collisions across states are possible. To keep ids
globally unique in the combined file (index.html uses "id" as the
expand/collapse row key), save_state_games() rewrites every incoming
game's "id" to "{state}-{original_id}" before merging. Do this here,
centrally, rather than in each scraper, so scraper.py / scraper_oregon.py
can keep using their own natural per-state ids internally (e.g. for
de-duping against that state's own explorer/extras data) without knowing
anything about how the combined file namespaces things.
"""

import json
from datetime import datetime, timezone


def load_existing(out_path):
    """Load the current games.json, tolerating "doesn't exist yet" and
    "corrupt/unreadable" by falling back to an empty combined-file shape
    rather than raising - a state's scrape run shouldn't fail just because
    games.json hasn't been created yet (e.g. very first run)."""
    try:
        with open(out_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"sources": {}, "games": []}


def save_state_games(state, games, warnings, out_path="games.json"):
    """Merge one state's freshly-scraped games into games.json.

    Replaces only this state's games (matched by the "state" field) and
    this state's entry in "sources"; every other state's games and source
    metadata are left untouched. Returns the full combined payload that
    was written.
    """
    payload = load_existing(out_path)
    sources = payload.get("sources", {})
    existing_games = payload.get("games", [])

    now = datetime.now(timezone.utc).isoformat()

    namespaced_games = []
    for g in games:
        g = dict(g)
        raw_id = g.get("id")
        g["id"] = f"{state}-{raw_id}" if raw_id is not None else None
        namespaced_games.append(g)

    sources[state] = {
        "scraped_at": now,
        "count": len(namespaced_games),
        "warnings": warnings,
    }

    other_states_games = [g for g in existing_games if g.get("state") != state]
    all_games = other_states_games + namespaced_games

    combined = {
        # Top-level scraped_at/warnings are kept (in addition to the
        # per-state "sources" entries below) so anything that only reads
        # the old single-state shape still shows a sensible "last
        # updated" - it reflects whichever state's run wrote most
        # recently, i.e. this run.
        "scraped_at": now,
        "count": len(all_games),
        "warnings": warnings,
        "sources": sources,
        "games": all_games,
    }

    with open(out_path, "w") as f:
        json.dump(combined, f, indent=2)

    return combined
