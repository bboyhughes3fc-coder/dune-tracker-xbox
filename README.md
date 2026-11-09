# Dune EU Xbox server tracker

Scrapes https://dunestatus.com every 15 minutes (GitHub Actions) for the 11 official
EU Xbox worlds in Dune: Awakening, stores each snapshot as CSV in `data/raw/`, and
publishes a dashboard (GitHub Pages, from `docs/`).

- `scraper/scrape.py` – fetch + record a snapshot, then rebuild `docs/data/summary.json`
- `scraper/build_summary.py` – hourly / weekday averages in UK time
- `.github/workflows/scrape.yml` – the 15-minute schedule
- `docs/index.html` – the dashboard

Setup: Settings → Pages → Source "Deploy from a branch", branch `main`, folder `/docs`.
Then Actions → "Scrape EU Xbox server counts" → Run workflow once to start it.
