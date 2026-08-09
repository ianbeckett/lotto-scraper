# Lotto Scraper

A static site for browsing scratch ticket data - currently Washington and
Oregon - in one sortable, filterable table, instead of clicking through
each state lottery's own site one game at a time. Hosted on GitHub Pages;
data refreshes automatically via scheduled GitHub Actions - no server
required.

Live version: `https://ianbeckett.github.io/lotto-scraper/`

The frontend has a WA / OR / Combined selector. WA and OR scrape on
different schedules (WA hourly, OR daily - see below), so `games.json`
holds both states' games in one array (each tagged `"state": "WA"` or
`"OR"`), plus a `sources` object with per-state scrape metadata
(`scraped_at` / `count` / `warnings`), since one state's scheduled run
must never clobber the other's already-current data. `multistate.py` is
the shared merge logic both scrapers call into - see its docstring for
details.

## How it works

Washington's Lottery's own "Scratch Explorer" page
(`walottery.com/Scratch/Explorer.aspx`) loads its data with JavaScript after
the page loads, which makes it hard to scrape directly. But their
**Top Prizes Remaining** page (`walottery.com/Scratch/TopPrizesRemaining.aspx`)
renders the same underlying data - full prize-tier tables for every active
game - as plain server-side HTML. `scraper.py` fetches that page for each
price bracket ($1 through $30) and parses it.

For each game it computes some sortable, at-a-glance metrics beyond what's
on the site:

- **Top Prize % Left** - how much of the top prize tier is still unclaimed
- **All Prizes % Left** - how much of every prize tier combined is still unclaimed
- **Remaining Cash Value** - total dollar value of all unclaimed prizes still in circulation for that game

It also pulls **Tickets Printed** and **Overall Odds** for every game from
the Scratch Explorer page (`walottery.com/Scratch/Explorer.aspx`). That page
renders its ticket-flip UI with JavaScript, but the data behind it -
`TicketsPrinted`, `OverallOdds`, and per-game prize tiers for every active
game - is embedded directly in the page's initial HTML as a JSON blob
(`WaLottery.Scratch.data.all`), so a plain server-side request can read it
without needing to run any JavaScript. `scraper.fetch_explorer_extras()`
extracts that blob with a regex and merges `tickets_printed` /
`overall_odds` into each game record by id. These are static numbers set at
print time, so they're less useful than the "remaining" metrics above for
deciding which ticket to buy, but they're shown for reference.

### Oregon

Oregon Lottery's site (`oregonlottery.org`, WordPress) renders its
scratch-it pages with client-side JavaScript - a plain HTTP GET returns an
HTML shell with empty placeholders where the prize numbers should be. The
real numbers come from Oregon Lottery's own backend
(`api.oregonlottery.org`), but that endpoint requires a
`client_id`/`client_secret` pair that ships inside the site's own JS
bundle - built for their frontend, not for a third party to lift out and
reuse against their production API on a schedule. Rather than extract and
reuse that credential, `scraper_oregon.py` drives a real headless browser
(Playwright) and reads the same numbers any visitor's browser renders on
screen - same spirit as the WA scraper (reading what the public site
displays), just via rendering instead of a plain GET, because Oregon's
site needs JS to populate the page.

It scrapes the scratch-its list page (a DataTables table - its own jQuery
API is used to show every row on one page instead of clicking through
pagination) for the roster of currently-for-sale games, then visits each
game's own detail page for its full prize-tier breakdown. That's roughly
50-60 page loads per run, so it's meaningfully heavier than WA's ~7 plain
HTTP requests - hence its own daily (not hourly) schedule, matching Oregon
Lottery's own "updated once daily" disclaimer on that page.

This was developed and its selectors verified by directly inspecting the
live, rendered site, but - unlike the WA scraper - it has **not been
executed end-to-end against oregonlottery.org** (the dev environment this
was built in can't reach that domain; only pure parsing logic was tested
offline against real captured page text). Treat the first real run
(locally, or a manual `workflow_dispatch` run in Actions) as the actual
test, and check its `warnings` output.

## Architecture

- `index.html` - the static frontend. Fetches `games.json` on load, renders
  a sortable/filterable table with a WA / OR / Combined selector. No
  backend calls, nothing dynamic server-side.
- `games.json` - the data, committed to the repo. Updated automatically.
- `multistate.py` - shared merge logic: writes one state's games into
  `games.json` without disturbing the other state's games or metadata.
- `scraper.py` - fetches and parses walottery.com, calls
  `multistate.save_state_games("WA", ...)`.
- `scraper_oregon.py` - renders and parses oregonlottery.org with
  Playwright, calls `multistate.save_state_games("OR", ...)`.
- `.github/workflows/scrape.yml` - runs `scraper.py` hourly and commits the
  updated `games.json` if it changed. Can also be triggered manually from
  the repo's **Actions** tab ("Run workflow").
- `.github/workflows/scrape-oregon.yml` - same, but runs `scraper_oregon.py`
  daily (it's much heavier - see "Oregon" above) and installs Playwright +
  headless Chromium first.
- Both scrape workflows share a `concurrency` group (`games-json-scrape`)
  so they can never run at the same time - both commit and push
  `games.json` on `main`, and without this, an overlapping run could push
  a stale merge over a fresher one, or just fail the push outright.

This intentionally has **no live backend and no exposed endpoint** - the
scraping happens inside GitHub's own runners on a schedule, not in response
to site visitors, and the published site is just static files.

### Local dev version

`app.py` is a Flask version of the same thing with an on-demand "Refresh
Data" button, useful for testing changes locally:

```bash
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5000. This is not what's deployed to GitHub
Pages (Pages can't run Flask) - it's just handy for local iteration.

## Deploying to GitHub Pages

1. Create a new **public** GitHub repo named `lotto-scraper`.
2. From this folder:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/ianbeckett/lotto-scraper.git
   git push -u origin main
   ```
3. In the repo, go to **Settings > Pages**. Under "Build and deployment",
   set Source to "Deploy from a branch", branch `main`, folder `/ (root)`.
   Save. GitHub gives you a URL like
   `https://ianbeckett.github.io/lotto-scraper/` within a minute or two.
4. Go to the **Actions** tab and manually run the "Scrape WA Lottery Data"
   workflow once (Run workflow button) so `games.json` has real data right
   away, instead of waiting for the next scheduled run.
5. (Optional) Point a subdomain like `scratch.ibeckett.com` at this instead
   of the default github.io URL: add a `CNAME` file to the repo containing
   just the subdomain, and add a CNAME DNS record for it pointing to
   `<your-username>.github.io`, then set the custom domain in
   Settings > Pages.

## A note on reliability

This was built without a way to inspect walottery.com's raw HTML directly
(the dev environment's network access to that domain was restricted), so
the parser (`scraper.py`) works structurally: it walks the page in order,
pairs each game's title link + "$PRICE | GAME NUMBER" line + optional
"Last Day To Redeem" line with the `<table>` that follows it, and reads the
prize-tier rows out of that table. It doesn't depend on specific CSS class
names, which should make it fairly resilient to minor markup changes -
but it hasn't been tested against the live site.

`test_scraper.py` unit-tests the parsing and math against a hand-built
HTML snippet that mirrors real page content, and that all passes. If a
scheduled run ever produces a `games.json` with a `warnings` entry saying
"No games parsed for $X bracket," WA Lottery likely changed their page
structure and `scraper.py` needs a look - check the failed run's log in
the Actions tab.

## Files

- `index.html` - static frontend, deployed as-is to GitHub Pages
- `games.json` - scrape results (both states), updated by the scheduled Actions
- `multistate.py` - shared per-state merge logic for `games.json`
- `scraper.py` - WA fetching + parsing logic, runnable standalone (`python scraper.py`)
- `scraper_oregon.py` - OR rendering + parsing logic (Playwright), runnable
  standalone (`python scraper_oregon.py`) after `pip install -r requirements-oregon.txt && playwright install chromium`
- `.github/workflows/scrape.yml` - the hourly WA scrape + commit job
- `.github/workflows/scrape-oregon.yml` - the daily OR scrape + commit job
- `test_scraper.py` - offline sanity test for the WA parser
- `app.py` + `requirements.txt` - optional local Flask dev version (WA only)
- `requirements-oregon.txt` - extra dependency (Playwright) for `scraper_oregon.py`
