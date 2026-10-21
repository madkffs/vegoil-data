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
SINA_HF = {"hf_BO": "CBOT soyoil (front)", "hf_SM": "CBOT soymeal (front)", "hf_S": "CBOT soybeans (front)", "hf_C": "CBOT corn (front)",
           "hf_HO": "NYMEX heating oil (front)", "hf_OIL": "ICE Brent (front)", "hf_CL": "NYMEX WTI (front)", "hf_FCPO": "Bursa crude palm oil (3rd month benchmark)"}
SINA_FX = ["fx_susdmyr", "fx_susdbrl", "fx_susdinr", "fx_susdcny", "fx_seurusd", "fx_susdidr"]
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
    """Delayed Yahoo Finance data via the yfinance library (handles the session cookies that plain requests lack)."""
    import yfinance as yf
    h = yf.Ticker(symbol).history(period=rng, interval=interval, auto_adjust=False)
    if h is None or h.empty:
        raise ValueError("no data")
    rows = []
    for idx, r in h.iterrows():
        t = idx.tz_convert("UTC") if idx.tzinfo else idx
        rows.append({"time_utc": t.strftime("%Y-%m-%d %H:%M"), "open": round(float(r["Open"]), 4), "high": round(float(r["High"]), 4),
                     "low": round(float(r["Low"]), 4), "close": round(float(r["Close"]), 4), "volume": int(r["Volume"]) if r["Volume"] == r["Volume"] else None})
    last = rows[-1]
    prev = rows[-2]["close"] if len(rows) > 1 else None
    snap = {"symbol": symbol, "last": last["close"], "prev_close": prev, "time_utc": last["time_utc"], "source": "yahoo (delayed)"}
    return snap, rows

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

def sina_raw(codes):
    r = requests.get("https://hq.sinajs.cn/list=" + ",".join(codes), headers={**UA, "Referer": "https://finance.sina.com.cn"}, timeout=20)
    r.encoding = "gbk"
    return r.text

def parse_sina_hf(text):
    """Global futures: 0 last, 2 bid, 3 ask, 4 high, 5 low, 6 time (Beijing), 7 prev settle, 8 open, 12 date."""
    out = {}
    for code, body in re.findall(r'hq_str_(hf_\w+)="([^"]*)"', text):
        f = body.split(",")
        if len(f) < 13 or not f[0]:
            continue
        fl = lambda i: float(f[i]) if re.fullmatch(r"-?\d+(\.\d+)?", f[i] or "") else None
        out[code] = {"last": fl(0), "high": fl(4), "low": fl(5), "prev_settle": fl(7), "open": fl(8), "time_beijing": f[6], "date": f[12]}
    return out

def parse_sina_fx(text):
    out = {}
    for code, body in re.findall(r'hq_str_(fx_s\w+)="([^"]*)"', text):
        f = body.split(",")
        if len(f) > 8:
            try:
                out[code] = {"last": float(f[8]), "time": f[0], "date": f[-1]}
            except ValueError:
                pass
    return out

SINA_KLINE = {  # daily history (OHLC) from Sina's public chart endpoints
    "FCPO": ("global", "FCPO"),          # Bursa Malaysia crude palm oil, MYR/t
    "DCE_Y0": ("inner", "Y0"),            # Dalian soyoil main
    "DCE_P0": ("inner", "P0"),            # Dalian palm olein main
    "DCE_M0": ("inner", "M0"),            # Dalian soymeal main
}

def sina_kline(kind, sym):
    if kind == "global":
        url = f"https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_{sym}=/GlobalFuturesService.getGlobalFuturesDailyKLine?symbol={sym}"
    else:
        url = f"https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_{sym}=/InnerFuturesNewService.getDailyKLine?symbol={sym}"
    r = requests.get(url, headers={**UA, "Referer": "https://finance.sina.com.cn"}, timeout=30)
    return parse_kline(r.text)

def parse_kline(text):
    m = re.search(r"\((\[.*\])\)", text, re.S)
    if not m:
        raise ValueError("no kline data: " + text[:120])
    arr = json.loads(m.group(1))
    rows = []
    for a in arr:
        g = lambda *ks: next((a[k] for k in ks if k in a and a[k] not in (None, "")), None)
        d, c = g("date", "d"), g("close", "c")
        if d is None or c is None:
            continue
        rows.append({"time_utc": str(d)[:10] + " 00:00", "open": float(g("open", "o") or c), "high": float(g("high", "h") or c),
                     "low": float(g("low", "l") or c), "close": float(c), "volume": g("volume", "v")})
    return rows

def percentiles():
    """2-year percentiles of key spreads from daily files."""
    import pandas as pd
    def load(name):
        p = os.path.join(DATA, "daily", name)
        if not os.path.exists(p):
            return None
        d = pd.read_csv(p)
        d["date"] = pd.to_datetime(d["time_utc"]).dt.normalize()
        return d.groupby("date")["close"].last()
    zl, zm, zs, ho, myr = load("ZL_F.csv"), load("ZM_F.csv"), load("ZS_F.csv"), load("HO_F.csv"), load("MYR_X.csv")
    fcpo, y0, p0 = load("FCPO.csv"), load("DCE_Y0.csv"), load("DCE_P0.csv")
    zlh, zlz = load("ZLH27_CBT.csv"), load("ZLZ26_CBT.csv")
    series = {}
    if zl is not None and ho is not None:
        series["boho_usd_gal"] = (ho - zl / 100 * 7.37)
    if zl is not None and zm is not None:
        series["oilshare_pct"] = zl * 11 / (zl * 11 + zm * 2.2) * 100
        if zs is not None:
            series["board_crush_usd_bu"] = zl * 0.11 + zm * 0.022 - zs / 100
    if zl is not None and fcpo is not None and myr is not None:
        series["soy_minus_palm_usd_t"] = zl * 22.0462 - fcpo / myr.reindex(fcpo.index, method="ffill")
    if fcpo is not None:
        series["fcpo_myr_t"] = fcpo
    if zl is not None:
        series["zl_cents_lb"] = zl
    if y0 is not None and p0 is not None:
        series["dalian_soyoil_minus_palmolein_cny_t"] = y0 - p0
    if zlz is not None and zlh is not None:
        series["zl_dec_minus_mar"] = zlz - zlh
    out = {}
    for k, s in series.items():
        s = s.dropna()
        s = s[s.index >= s.index.max() - pd.Timedelta(days=730)]
        if len(s) < 30:
            continue
        last = float(s.iloc[-1])
        out[k] = {"last": round(last, 3), "date": s.index[-1].strftime("%Y-%m-%d"), "pct_2y": round(float((s < last).mean() * 100), 1),
                  "pct_1y": round(float((s[s.index >= s.index.max() - pd.Timedelta(days=365)] < last).mean() * 100), 1),
                  "median_2y": round(float(s.median()), 3), "min_2y": round(float(s.min()), 3), "max_2y": round(float(s.max()), 3), "n": int(len(s))}
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
    fields = []
    for r in existing.values():
        for k in r:
            if k not in fields:
                fields.append(k)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, restval="", extrasaction="ignore")
        w.writeheader()
        for k in sorted(existing):
            w.writerow(existing[k])

def spreads(latest):
    g = lambda s: (latest.get(s) or {}).get("last")
    hf = latest.get("_sina_futures") or {}
    h = lambda k: (hf.get(k) or {}).get("last")
    zl, zm, zs, ho = h("hf_BO") or g("ZL=F"), h("hf_SM") or g("ZM=F"), h("hf_S") or g("ZS=F"), h("hf_HO") or g("HO=F")
    usdmyr = ((latest.get("_sina_fx") or {}).get("fx_susdmyr") or {}).get("last") or g("MYR=X")
    fcpo = h("hf_FCPO")
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
    if zl and fcpo and usdmyr:
        out["soy_minus_fcpo_usd_t"] = round(zl * 22.0462 - fcpo / usdmyr, 1)
    out["inputs"] = {"zl": zl, "zm": zm, "zs": zs, "ho": ho, "fcpo": fcpo}
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
        time.sleep(1.0)
    try:
        hf = parse_sina_hf(sina_raw(list(SINA_HF)))
        latest["_sina_futures"] = hf
        append_csv(os.path.join(DATA, "sina_futures.csv"), [{"time_utc": now, **{f"{k}_last": v["last"] for k, v in hf.items()}, **{f"{k}_prev": v["prev_settle"] for k, v in hf.items()}}])
    except Exception as e:
        status["errors"]["sina_futures"] = str(e)[:200]
    try:
        fx = parse_sina_fx(sina_raw(SINA_FX))
        latest["_sina_fx"] = fx
    except Exception as e:
        status["errors"]["sina_fx"] = str(e)[:200]
    try:
        dce = sina(list(SINA))
        latest["_dalian"] = dce
        append_csv(os.path.join(DATA, "dalian.csv"),
                   [{"time_utc": now, **{f"{c}_last": v.get("last") for c, v in dce.items()}, **{f"{c}_prev_settle": v.get("prev_settle") for c, v in dce.items()}}])
    except Exception as e:
        status["errors"]["dalian"] = str(e)[:200]
    for name, (kind, sym) in SINA_KLINE.items():
        try:
            rows = sina_kline(kind, sym)
            if mode != "backfill":
                rows = rows[-15:]
            append_csv(os.path.join(DATA, "daily", name + ".csv"), rows)
        except Exception as e:
            status["errors"]["kline_" + name] = str(e)[:200]
    try:
        p = palm_fob()
        latest["_palm_fob"] = p
        append_csv(os.path.join(DATA, "palm_fob.csv"), [{"time_utc": now, **p}])
    except Exception as e:
        status["errors"]["palm_fob"] = str(e)[:200]
    sp = spreads(latest)
    latest["_spreads"] = sp
    flat = {k: v for k, v in sp.items() if k != "inputs"}
    flat.update({f"in_{k}": v for k, v in (sp.get("inputs") or {}).items()})
    append_csv(os.path.join(DATA, "spreads.csv"), [{"time_utc": now, **flat}])
    try:
        latest["_percentiles"] = percentiles()
        with open(os.path.join(DATA, "percentiles.json"), "w") as fh:
            json.dump(latest["_percentiles"], fh, indent=1)
    except Exception as e:
        status["errors"]["percentiles"] = str(e)[:200]
    with open(os.path.join(DATA, "latest.json"), "w") as fh:
        json.dump(latest, fh, indent=1, ensure_ascii=False)
    status["ok"] = len([k for k in latest if not k.startswith("_")])
    with open(os.path.join(DATA, "status.json"), "w") as fh:
        json.dump(status, fh, indent=1)
    print(json.dumps(status, indent=1))

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "update")
