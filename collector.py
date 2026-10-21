"""Public market data collector for a private research repo.
Runs on GitHub's servers (GitHub Actions). It only downloads public, delayed market data
and writes CSV/JSON files into this repo. It has no access to anything else.
Every source is optional: if one fails, the others still run and the failure is logged in data/status.json.
"""
import csv, json, os, re, sys, time, datetime as dt
import requests

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
MONTHS = "FGHJKMNQUVXZ"

# CBOT listed months per product
CYCLES = {"ZL": "FHKNQUVZ", "ZM": "FHKNQUVZ", "ZS": "FHKNQUX", "ZC": "HKNUZ"}
CONTINUOUS = ["ZL=F", "ZM=F", "ZS=F", "ZC=F", "HO=F", "BZ=F", "CL=F", "RB=F"]
FX = ["MYR=X", "BRL=X", "ARS=X", "INR=X", "CNY=X", "IDR=X", "EGP=X", "EURUSD=X", "DX-Y.NYB"]
SINA = {"Y0": "DCE soyoil (main)", "P0": "DCE palm olein (main)", "M0": "DCE soymeal (main)", "A0": "DCE soybean No.1 (main)"}

def contract_symbols(today=None, n=6):
    today = today or dt.date.today()
    out = []
    for root, cyc in CYCLES.items():
        y, m = today.year, today.month
        got = 0
        start = 0 if today.day <= 14 else 1   # CBOT soy complex months expire around mid-month
        for k in range(start, 36):
            mm = (m - 1 + k) % 12 + 1
            yy = y + (m - 1 + k) // 12
            code = MONTHS[mm - 1]
            if code in cyc:
                out.append(f"{root}{code}{str(yy)[-2:]}.CBT")
                got += 1
            if got == n:
                break
    return out

def yahoo_chart(symbol, interval="1d", rng="1mo"):
    last_err = None
    for host in ("query1", "query2"):
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}"
        try:
            r = requests.get(url, params={"interval": interval, "range": rng}, headers=UA, timeout=20)
            r.raise_for_status()
            return parse_yahoo(r.json())
        except Exception as e:
            last_err = e
    raise RuntimeError(f"{symbol}: {last_err}")

def parse_yahoo(js):
    res = (js.get("chart") or {}).get("result") or []
    if not res:
        raise ValueError(f"no result: {(js.get('chart') or {}).get('error')}")
    res = res[0]
    meta = res.get("meta", {})
    ts = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    rows = []
    for i, t in enumerate(ts):
        c = (q.get("close") or [None] * len(ts))[i]
        if c is None:
            continue
        g = lambda k: (q.get(k) or [None] * len(ts))[i]
        rows.append({"time_utc": dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
                     "open": g("open"), "high": g("high"), "low": g("low"), "close": c, "volume": g("volume")})
    snap = {"symbol": meta.get("symbol"), "last": meta.get("regularMarketPrice"),
            "prev_close": meta.get("chartPreviousClose") or meta.get("previousClose"),
            "time_utc": dt.datetime.fromtimestamp(meta["regularMarketTime"], dt.timezone.utc).strftime("%Y-%m-%d %H:%M") if meta.get("regularMarketTime") else None,
            "currency": meta.get("currency"), "exchange": meta.get("exchangeName")}
    return snap, rows

def sina(codes):
    url = "https://hq.sinajs.cn/list=" + ",".join("nf_" + c for c in codes)
    r = requests.get(url, headers={**UA, "Referer": "https://finance.sina.com.cn"}, timeout=20)
    r.encoding = "gbk"
    return parse_sina(r.text)

def parse_sina(text):
    out = {}
    for code, body in re.findall(r'hq_str_nf_(\w+)="([^"]*)"', text):
        f = body.split(",")
        if len(f) < 15:
            continue
        num = lambda i: float(f[i]) if i < len(f) and re.fullmatch(r"-?\d+(\.\d+)?", f[i] or "") else None
        # Field layout for Chinese commodity futures (verify on first live run):
        # 0 name, 1 time hhmmss, 2 open, 3 high, 4 low, 5 prev close, 6 bid, 7 ask, 8 last,
        # 9 settle, 10 prev settle, 11 bid vol, 12 ask vol, 13 open interest, 14 volume, ... 17 date
        out[code] = {"last": num(8), "open": num(2), "high": num(3), "low": num(4), "prev_settle": num(10),
                     "open_interest": num(13), "volume": num(14), "date": f[17] if len(f) > 17 else None,
                     "time": f[1], "raw": body[:300]}
    return out

def palm_fob():
    r = requests.get("https://www.zyotwdhon.com/en/palm-oil-daily-prices", headers=UA, timeout=20)
    return parse_palm(r.text)

def parse_palm(html):
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    out = {}
    for label in ["Indonesian Crude Palm Oil (CPO)", "Malaysian Crude Palm Oil (CPO)", "RBD Palm Olein", "RBD Palm Stearin", "Palm Fatty Acid Distillate (PFAD)"]:
        m = re.search(re.escape(label) + r"\s*\$?\s*([\d,]+(?:\.\d+)?)", text)
        if m:
            out[label] = float(m.group(1).replace(",", ""))
    return out

def append_csv(path, rows, key="time_utc"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing = {}
    if os.path.exists(path):
        with open(path, newline="") as fh:
            for r in csv.DictReader(fh):
                existing[r[key]] = r
    for r in rows:
        existing[r[key]] = {k: ("" if v is None else v) for k, v in r.items()}
    if not existing:
        return
    fields = list(next(iter(existing.values())).keys())
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for k in sorted(existing):
            w.writerow(existing[k])

def spreads(latest):
    g = lambda s: (latest.get(s) or {}).get("last")
    zl, zm, zs, ho = g("ZL=F"), g("ZM=F"), g("ZS=F"), g("HO=F")
    usdmyr = g("MYR=X")
    palm = (latest.get("_palm_fob") or {}).get("Malaysian Crude Palm Oil (CPO)")
    out = {}
    if zl and zm:
        oil, meal = zl * 11 / 100, zm * 0.022
        out["oilshare_pct"] = round(oil / (oil + meal) * 100, 2)
        if zs:
            out["board_crush_usd_bu"] = round(oil + meal - zs / 100, 3)
    if zl and ho:
        out["boho_usd_gal"] = round(ho - zl / 100 * 7.37, 3)
    if zl and palm:
        out["soy_minus_palm_fob_usd_t"] = round(zl * 22.0462 - palm, 1)
    if usdmyr:
        out["usdmyr"] = usdmyr
    return out

def main(mode):
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    status, latest = {"run_utc": now, "mode": mode, "errors": {}}, {}
    rng = "2y" if mode == "backfill" else "10d"
    symbols = CONTINUOUS + FX + contract_symbols()
    for s in symbols:
        try:
            snap, daily = yahoo_chart(s, "1d", rng)
            latest[s] = snap
            append_csv(os.path.join(DATA, "daily", s.replace("=", "_").replace(".", "_") + ".csv"), daily)
            if mode != "backfill" and s in CONTINUOUS + contract_symbols()[:1]:
                _, intraday = yahoo_chart(s, "30m", "5d")
                append_csv(os.path.join(DATA, "intraday", s.replace("=", "_").replace(".", "_") + ".csv"), intraday)
        except Exception as e:
            status["errors"][s] = str(e)[:200]
        time.sleep(0.5)
    try:
        dce = sina(list(SINA))
        latest["_dalian"] = dce
        append_csv(os.path.join(DATA, "dalian.csv"),
                   [{"time_utc": now, **{f"{c}_last": v.get("last") for c, v in dce.items()}, **{f"{c}_prev_settle": v.get("prev_settle") for c, v in dce.items()}}])
    except Exception as e:
        status["errors"]["dalian"] = str(e)[:200]
    try:
        p = palm_fob()
        latest["_palm_fob"] = p
        append_csv(os.path.join(DATA, "palm_fob.csv"), [{"time_utc": now, **p}])
    except Exception as e:
        status["errors"]["palm_fob"] = str(e)[:200]
    sp = spreads(latest)
    latest["_spreads"] = sp
    append_csv(os.path.join(DATA, "spreads.csv"), [{"time_utc": now, **sp}])
    with open(os.path.join(DATA, "latest.json"), "w") as fh:
        json.dump(latest, fh, indent=1, ensure_ascii=False)
    status["ok"] = len([k for k in latest if not k.startswith("_")])
    with open(os.path.join(DATA, "status.json"), "w") as fh:
        json.dump(status, fh, indent=1)
    print(json.dumps(status, indent=1))

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "update")
