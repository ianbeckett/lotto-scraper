# WA Lotto Scraper

A static site for browsing Washington's Lottery scratch ticket data in one
sortable, filterable table, instead of clicking through the site's Explorer
one game at a time. Hosted on GitHub Pages; data refreshes automatically
once a day via a scheduled GitHub Action - no server required.

Live version: add your GitHub Pages URL here once deployed, e.g.
`https://<your-username>.github.io/wa-lotto-scraper/`

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

(Note: "Tickets Printed" and "Overall Odds," shown on the Explorer's
per-game popup, aren't available from this page and require the JS-driven
Explorer - they're static numbers set at print time anyway, so they're less
useful than the "remaining" metrics above for deciding which ticket to buy.)

## Architecture

- `index.html` - the static frontend. Fetches `games.json` on load, renders
  a sortable/filterable table. No backend calls, nothing dynamic server-side.
- `games.json` - the data, committed to the repo. Updated automatically.
- `scraper.py` - fetches and parses walottery.com, writes `games.json`.
- `.github/workflows/scrape.yml` - runs `scraper.py` once a day (13:00 UTC)
  and commits the updated `games.json` if it changed. Can also be triggered
  manually from the repo's **Actions** tab ("Run workflow").

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

1. Create a new **public** GitHub repo (e.g. `wa-lotto-scraper`).
2. From this folder:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<your-username>/wa-lotto-scraper.git
   git push -u origin main
   ```
3. In the repo, go to **Settings > Pages**. Under "Build and deployment",
   set Source to "Deploy from a branch", branch `main`, folder `/ (root)`.
   Save. GitHub gives you a URL like
   `https://<your-username>.github.io/wa-lotto-scraper/` within a minute or two.
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
- `games.json` - scrape results, updated by the scheduled Action
- `scraper.py` - fetching + parsing logic, runnable standalone (`python scraper.py`)
- `.github/workflows/scrape.yml` - the daily scrape + commit job
- `test_scraper.py` - offline sanity test for the parser
- `app.py` + `requirements.txt` - optional local Flask dev version
