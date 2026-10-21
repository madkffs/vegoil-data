# vegoil-data (private)
Public, delayed market data collected automatically by GitHub Actions for personal research.
- `collector.py` downloads: CBOT soy complex and corn by contract month and continuous, heating oil, Brent, WTI, gasoline, FX (delayed, from Yahoo Finance's public chart endpoint); Dalian soyoil/palm olein/meal/beans (Sina Finance public quotes); Malaysian/Indonesian palm FOB (zyotwdhon.com).
- Output in `data/`: `latest.json` (snapshot), `daily/*.csv`, `intraday/*.csv` (30-min), `dalian.csv`, `palm_fob.csv`, `spreads.csv` (oilshare, board crush, BOHO, soy-palm), `status.json` (what worked).
- Runs every 30 minutes on weekdays. Run "backfill" once from the Actions tab to load 2 years of daily history.
- It only reads public websites. It has no access to any personal or company systems. Data is delayed, unofficial and for personal use only; endpoints can change without notice.
