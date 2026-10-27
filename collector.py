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
# Other agricultural futures (continuous), used to value fund positions across all agri markets
AGRI = ["ZW=F", "KE=F", "MWE=F", "ZO=F", "ZR=F", "RS=F", "CT=F", "SB=F", "KC=F", "CC=F", "OJ=F", "LE=F", "GF=F", "HE=F"]
# Freight proxy: Breakwave Dry Bulk Shipping ETF (holds Capesize/Panamax/Supramax freight futures)
FREIGHT = ["BDRY"]
FX = ["CAD=X", "MYR=X", "BRL=X", "ARS=X", "INR=X", "CNY=X", "IDR=X", "EGP=X", "EURUSD=X", "DX-Y.NYB"]
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

COT_CODES = {"005602": "soybeans", "007601": "soybean_oil", "026603": "soybean_meal", "002602": "corn"}
COT_FIELDS = ["report_date_as_yyyy_mm_dd", "cftc_contract_market_code", "open_interest_all",
              "prod_merc_positions_long", "prod_merc_positions_short",
              "swap_positions_long_all", "swap__positions_short_all", "swap__positions_spread_all",
              "m_money_positions_long_all", "m_money_positions_short_all", "m_money_positions_spread",
              "other_rept_positions_long", "other_rept_positions_short", "other_rept_positions_spread",
              "nonrept_positions_long_all", "nonrept_positions_short_all"]

def cot():
    """CFTC disaggregated futures-only (public Socrata API), weekly, from 2023."""
    codes = ",".join(f"'{c}'" for c in COT_CODES)
    params = {"$where": f"cftc_contract_market_code in({codes}) AND report_date_as_yyyy_mm_dd > '2023-01-01T00:00:00'",
              "$limit": "5000", "$order": "report_date_as_yyyy_mm_dd"}
    r = requests.get("https://publicreporting.cftc.gov/resource/72hh-3qpy.json", params=params, headers=UA, timeout=60)
    r.raise_for_status()
    rows = []
    for a in r.json():
        row = {"key": a.get("report_date_as_yyyy_mm_dd", "")[:10] + "_" + COT_CODES.get(a.get("cftc_contract_market_code"), a.get("cftc_contract_market_code")),
               "date": a.get("report_date_as_yyyy_mm_dd", "")[:10], "market": COT_CODES.get(a.get("cftc_contract_market_code"))}
        for f in COT_FIELDS[2:]:
            row[f] = a.get(f)
        rows.append(row)
    return rows

def cot_agri():
    """CFTC disaggregated futures-only for every agricultural market (commodity group AGRICULTURE), weekly, from mid-2024."""
    params = {"$where": "commodity_group_name='AGRICULTURE' AND report_date_as_yyyy_mm_dd > '2024-06-01T00:00:00'",
              "$select": "report_date_as_yyyy_mm_dd,cftc_contract_market_code,market_and_exchange_names,commodity_subgroup_name,commodity_name,"
                         "open_interest_all,m_money_positions_long_all,m_money_positions_short_all",
              "$limit": "50000", "$order": "report_date_as_yyyy_mm_dd"}
    r = requests.get("https://publicreporting.cftc.gov/resource/72hh-3qpy.json", params=params, headers=UA, timeout=90)
    r.raise_for_status()
    rows = []
    for a in r.json():
        d, c = a.get("report_date_as_yyyy_mm_dd", "")[:10], a.get("cftc_contract_market_code")
        rows.append({"key": f"{d}_{c}", "date": d, "code": c, "name": a.get("market_and_exchange_names"),
                     "subgroup": a.get("commodity_subgroup_name"), "commodity": a.get("commodity_name"),
                     "open_interest": a.get("open_interest_all"), "mm_long": a.get("m_money_positions_long_all"),
                     "mm_short": a.get("m_money_positions_short_all")})
    return rows

EURONEXT_COT = {"EBM": "Milling wheat", "ECO": "Rapeseed", "EMA": "Corn"}

def euronext_probe():
    """Find the latest Euronext weekly position report (PDF) per MATIF product and save its text,
    so the parser can be written against the real layout. Also records which quote pages respond."""
    out_dir = os.path.join(DATA, "euronext")
    os.makedirs(out_dir, exist_ok=True)
    found = {}
    today = dt.date.today()
    for prod in EURONEXT_COT:
        for back in range(0, 22):
            d = today - dt.timedelta(days=back)
            for lang in ("en",):
                url = f"https://live.euronext.com/sites/default/files/commodities_reporting/{d:%Y/%m/%d}/{lang}/cdwpr_{prod}_{d:%Y%m%d}.pdf"
                try:
                    r = requests.get(url, headers=UA, timeout=30)
                except Exception as e:
                    continue
                if r.status_code == 200 and r.content[:4] == b"%PDF":
                    import io, pdfplumber
                    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                        text = "\n\n=== PAGE ===\n".join((p.extract_text() or "") for p in pdf.pages)
                    with open(os.path.join(out_dir, f"raw_{prod}.txt"), "w") as fh:
                        fh.write(url + "\n" + text)
                    found[prod] = url
                    break
            if prod in found:
                break
    probes = {}
    for u in ["https://live.euronext.com/en/ajax/getDetailedQuote/EBM-DPAR",
              "https://live.euronext.com/en/product/commodities-futures/EBM-DPAR",
              "https://live.euronext.com/en/ajax/getPricesFutures/commodities-futures/EBM/DPAR"]:
        try:
            r = requests.get(u, headers=UA, timeout=30)
            probes[u] = {"status": r.status_code, "type": r.headers.get("content-type"), "head": r.text[:4000]}
        except Exception as e:
            probes[u] = {"error": str(e)[:200]}
    for u in ["https://shipandbunker.com/prices",
              "https://shipandbunker.com/prices/apac/sea/sg-sin-singapore",
              "https://shipandbunker.com/prices/emea/nwe/nl-rtm-rotterdam",
              "https://www.balticexchange.com/en/index.html",
              "https://www.hellenicshippingnews.com/category/shipping-news/dry-bulk-market/"]:
        try:
            r = requests.get(u, headers=UA, timeout=30)
            t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text, flags=re.S)
            t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))
            probes[u] = {"status": r.status_code, "type": r.headers.get("content-type"), "text": t[:6000]}
        except Exception as e:
            probes[u] = {"error": str(e)[:200]}
    try:
        pg = requests.get("https://live.euronext.com/en/product/commodities-futures/EBM-DPAR", headers=UA, timeout=30).text
        probes["ajax_urls"] = sorted(set(re.findall(r"/(?:en/)?ajax/[A-Za-z0-9_/\-{}.]+", pg)))[:60]
    except Exception as e:
        probes["ajax_urls"] = str(e)[:200]
    tries = {}
    for sym in ["RSX26.NYB", "RSF27.NYB", "RS=F", "MWEZ26.MGE", "MWE=F"]:
        try:
            yahoo_chart(sym, "1d", "5d"); tries[sym] = "ok"
        except Exception as e:
            tries[sym] = str(e)[:80]
    probes["yahoo_tries"] = tries
    with open(os.path.join(out_dir, "probe.json"), "w") as fh:
        json.dump({"found": found, "quotes": probes}, fh, indent=1)
    return found

def _segs(tokens, n):
    """All ways to group space-separated tokens into n numbers (thousands groups of 3 digits)."""
    out = []
    def rec(i, cur):
        if len(cur) > n: return
        if i == len(tokens):
            if len(cur) == n: out.append(list(cur))
            return
        if not re.fullmatch(r"-?\d{1,3}(\.\d+)?", tokens[i]) and not re.fullmatch(r"-?\d+(\.\d+)?", tokens[i]): return
        num = tokens[i]; j = i + 1
        cur.append(float(num)); rec(j, cur); cur.pop()
        while j < len(tokens) and re.fullmatch(r"\d{3}(\.\d+)?", tokens[j]) and "." not in num:
            num = num + tokens[j]; j += 1
            cur.append(float(num)); rec(j, cur); cur.pop()
    rec(0, [])
    return out

def parse_euronext(text):
    rep = re.search(r"Report date (\d{2})/(\d{2})/(\d{4})", text)
    date = f"{rep.group(3)}-{rep.group(2)}-{rep.group(1)}" if rep else None
    tot = re.search(r"\nOther [^\n]*\nTotal ([\d .\-]+)\n", text)
    pct = re.search(r"\nTotal ((?:[\d.]+% ?){10})", text)
    if not (tot and pct): raise ValueError("layout not recognised")
    p = [float(x) / 100 for x in re.findall(r"([\d.]+)%", pct.group(1))]
    best, err = None, 1e18
    for s in _segs(tot.group(1).split(), 10):
        ois = [v / q for v, q in zip(s, p) if q >= 0.05 and v > 0]
        if not ois: continue
        m = sum(ois) / len(ois); e = sum((o - m) ** 2 for o in ois) / m ** 2
        if e < err: best, err, oi = s, e, m
    if not best: raise ValueError("could not segment totals")
    return {"date": date, "funds_long": best[2], "funds_short": best[3], "inv_firms_long": best[0], "inv_firms_short": best[1],
            "commercial_long": best[6], "commercial_short": best[7], "open_interest": round(oi)}

def euronext_pdf_text(url):
    r = requests.get(url, headers=UA, timeout=30)
    if r.status_code != 200 or r.content[:4] != b"%PDF":
        return None
    import io, pdfplumber
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        return "\n\n=== PAGE ===\n".join((p.extract_text() or "") for p in pdf.pages)

def euronext_cot(mode):
    """Euronext weekly position reports (MiFID II) for MATIF wheat, rapeseed and corn. Published Wednesdays."""
    weeks = 110 if mode == "backfill" else 3
    today = dt.date.today()
    last_wed = today - dt.timedelta(days=(today.weekday() - 2) % 7)
    rows, misses = [], []
    for w in range(weeks):
        wed = last_wed - dt.timedelta(weeks=w)
        for prod, name in EURONEXT_COT.items():
            got = None
            for shift in (0, 1, -1, 2):
                d = wed + dt.timedelta(days=shift)
                url = f"https://live.euronext.com/sites/default/files/commodities_reporting/{d:%Y/%m/%d}/en/cdwpr_{prod}_{d:%Y%m%d}.pdf"
                try:
                    t = euronext_pdf_text(url)
                except Exception:
                    t = None
                if t:
                    try:
                        got = parse_euronext(t)
                    except Exception as e:
                        misses.append(f"{prod} {d}: {e}")
                    break
            if got:
                rows.append({"key": f"{got['date']}_{prod}", "product": prod, "name": name, "publication": f"{d:%Y-%m-%d}", **got})
            else:
                misses.append(f"{prod} week of {wed}")
    return rows, misses[:20]

def euronext_prices():
    """Front-month and curve settlements for MATIF wheat, rapeseed and corn from Euronext's public price table."""
    out = []
    for prod in EURONEXT_COT:
        r = requests.get(f"https://live.euronext.com/en/ajax/getPricesFutures/commodities-futures/{prod}/DPAR", headers=UA, timeout=30)
        r.raise_for_status()
        day = re.search(r"Prices\s*-\s*(\d{1,2} \w{3} \d{4})", r.text)
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, flags=re.S):
            cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S)]
            i = next((k for k, c in enumerate(cells) if re.fullmatch(r"[A-Z][a-z]{2} \d{4}", c)), None)
            if i is not None and len(cells) >= i + 12:
                f = lambda x: float(x.replace(",", "")) if re.fullmatch(r"-?[\d,]+(\.\d+)?", x or "") else None
                out.append({"product": prod, "delivery": cells[i], "price_date": day.group(1) if day else None,
                            "last": f(cells[i + 3]), "settle": f(cells[i + 10]), "open_interest": f(cells[i + 11])})
    return out

def bunkers():
    """Ship & Bunker public port prices ($/mt) for VLSFO, MGO and IFO380."""
    r = requests.get("https://shipandbunker.com/prices", headers=UA, timeout=30)
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text, flags=re.S)
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))
    blocks = t.split("Port Price $/mt Change High Low Spread")[1:4]
    out = {}
    for fuel, b in zip(["VLSFO", "MGO", "IFO380"], blocks):
        for port in ["Global 20 Ports Average", "Singapore", "Rotterdam", "Houston", "Fujairah", "Santos"]:
            m = re.search(re.escape(port) + r" ([\d.]+) ([+-]?[\d.]+)", b)
            if m:
                out[f"{fuel}_{port.split(' Ports')[0].replace(' ', '')}"] = float(m.group(1))
    if not out:
        raise ValueError("no prices parsed")
    return out

def baltic_headline():
    """Baltic Dry Index level from public news headlines (the exchange's own indices are licensed)."""
    r = requests.get("https://www.hellenicshippingnews.com/category/shipping-news/dry-bulk-market/", headers=UA, timeout=30)
    m = re.search(r"Baltic Dry Index[^<]{0,40}? to ([\d,]+)", r.text)
    if not m:
        raise ValueError("no BDI headline")
    return float(m.group(1).replace(",", ""))

NABSA = "https://www.nabsa.com.ar/assets/"

def _num_es(x):
    x = (x or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(x)
    except ValueError:
        return None

COUNTRIES = ["UNITED ARAB EMIRATES", "KOREA (REPUBLIC OF SOUTH KOREA)", "SOUTH KOREA", "KOREA", "DOMINICAN REPUBLIC", "SAUDI ARABIA", "SOUTH AFRICA",
    "UNITED KINGDOM", "UNITED STATES", "U.S.A.", "USA", "NEW ZEALAND", "SRI LANKA", "COSTA RICA", "EL SALVADOR", "PUERTO RICO", "IVORY COAST",
    "CAPE VERDE", "TRINIDAD AND TOBAGO", "PAPUA NEW GUINEA", "NETHERLANDS ANTILLES", "CZECH REPUBLIC", "HONG KONG", "SIERRA LEONE",
    "NOT AVAILABLE", "TO ORDERS", "OPTIONAL", "PERSIAN GULF", "RUSSIAN FEDERATION", "RED SEA", "WEST AFRICA", "EAST AFRICA", "CARIBBEAN", "MEDITERRANEAN", "CONTINENT", "FAR EAST", "INDIA", "CHINA", "PERU", "MOROCCO", "ALGERIA", "EGYPT", "BANGLADESH", "PAKISTAN", "MOZAMBIQUE",
    "MEXICO", "MADAGASCAR", "GUATEMALA", "TOGO", "SPAIN", "VENEZUELA", "COLOMBIA", "ECUADOR", "CHILE", "BOLIVIA", "PARAGUAY", "URUGUAY", "BRAZIL",
    "HONDURAS", "NICARAGUA", "PANAMA", "CUBA", "JAMAICA", "HAITI", "NETHERLANDS", "HOLLAND", "BELGIUM", "GERMANY", "FRANCE", "ITALY", "PORTUGAL",
    "POLAND", "DENMARK", "NORWAY", "SWEDEN", "FINLAND", "IRELAND", "GREECE", "TURKEY", "ISRAEL", "LEBANON", "SYRIA", "JORDAN", "IRAQ", "IRAN",
    "KUWAIT", "QATAR", "OMAN", "YEMEN", "BAHRAIN", "LIBYA", "TUNISIA", "SUDAN", "KENYA", "TANZANIA", "ANGOLA", "NIGERIA", "GHANA", "SENEGAL",
    "CAMEROON", "BENIN", "GUINEA", "LIBERIA", "MAURITANIA", "MAURITIUS", "DJIBOUTI", "ETHIOPIA", "SOMALIA", "VIETNAM", "THAILAND", "MALAYSIA",
    "INDONESIA", "PHILIPPINES", "JAPAN", "TAIWAN", "SINGAPORE", "MYANMAR", "CAMBODIA", "NEPAL", "AUSTRALIA", "CANADA", "RUSSIA", "UKRAINE",
    "GEORGIA", "ROMANIA", "BULGARIA", "CROATIA", "SLOVENIA", "ALBANIA", "MALTA", "CYPRUS", "ARMENIA", "AZERBAIJAN", "KAZAKHSTAN", "UZBEKISTAN"]
ORIGINS = r"(ARGENTINA|PARAGUAY|BOLIVIA|URUGUAY|BRAZIL)"
CARGOES = ["NEUTRALIZED SOYBEAN OIL", "REFINED SOYBEAN OIL", "SOYBEAN OIL", "SOY ACID OIL", "SOYBEANMEAL", "SOYBEAN MEAL", "SOYBEANS", "SOYBEAN",
           "SUN FLOWER OIL", "SUNFLOWER OIL", "SUN FLOWER MEAL", "SUNFLOWER MEAL", "CORN", "WHEAT", "BARLEY", "SORGHUM", "BIODIESEL", "GLYCERINE",
           "CORN OIL", "VEGETABLE OIL", "SOYA HULL PELLETS", "SUNFLOWER SEED PELLETS", "MALT", "RICE",
           "SOYA BEAN OIL (BLEND)", "SOYBEANOIL REFINED", "SOYA BEAN", "NEUTRAL OIL", "OLEIN", "LECITHIN", "SUN FLOWER PELLETS",
           "SUN FLOWER MEAL PELLETS", "SUNFLOWER PELLETS", "WOOD LOGS", "WOOD PULP", "WOOD CHIPS", "IRON ORE", "CRUDE OIL", "BALANCED FEED",
           "SULPHURIC ACID", "PEANUTS", "PEANUT OIL", "CHICKPEAS", "BEANS"]

def _country(rest):
    """Split 'DESTINATION COORDINATOR CHARTERER' by the longest known country prefix."""
    for c in sorted(COUNTRIES, key=len, reverse=True):
        if rest == c or rest.startswith(c + " "):
            return c, rest[len(c):].strip()
    return None, rest

def _cargo(text):
    for c in sorted(CARGOES, key=len, reverse=True):
        if text == c or text.startswith(c + " "):
            return c, text[len(c):].strip()
    return None, text

def _tons_es(t):
    return _num_es(t.replace(" ", ""))

def parse_nabsa_sailed(text):
    rows, bad = [], []
    for line in text.splitlines():
        m = re.search(r"^(.*?) (SAILED|SAILING) (\d{2}/\d{2}/\d{4}) ([\d .]*\d,\d{2}) (.+?) " + ORIGINS + r" (.+)$", line)
        if not m:
            if " SAILED " in line: bad.append(line[:160])
            continue
        head, _, date, tons, cargo, origin, rest = m.groups()
        dest, tail = _country(rest)
        if not dest: bad.append(line[:160])
        d, mth, y = date.split("/")
        rows.append({"head": head, "date": f"{y}-{mth}-{d}", "tons": _tons_es(tons), "cargo": cargo.strip(), "origin": origin,
                     "destination": dest or "UNPARSED", "rest": tail})
    return rows, bad

def _interleave(a, b, s):
    """True if s is an interleaving of a and b (order kept within each)."""
    if len(a) + len(b) != len(s): return False
    prev = [True] * (len(b) + 1)
    for j in range(1, len(b) + 1): prev[j] = prev[j - 1] and b[j - 1] == s[j - 1]
    for i in range(1, len(a) + 1):
        cur = [prev[0] and a[i - 1] == s[i - 1]] + [False] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = (prev[j] and a[i - 1] == s[i + j - 1]) or (cur[j - 1] and b[j - 1] == s[i + j - 1])
        prev = cur
    return prev[-1]

ORIGIN_LIST = ["ARGENTINA", "PARAGUAY", "BOLIVIA", "URUGUAY", "BRAZIL"]

def split_dest_origin(rest):
    """rest = 'DEST ORIGIN CHARTERER', where DEST and ORIGIN may be interleaved letter by letter by the PDF text layer."""
    for c in sorted(COUNTRIES, key=len, reverse=True):
        for o in ORIGIN_LIST:
            clean = c + " " + o
            if rest == clean or rest.startswith(clean + " "):
                return c, o, rest[len(clean):].strip()
    toks = rest.split(" ")
    for c in sorted(COUNTRIES, key=len, reverse=True):
        cw = c.split(" ")
        for o in ORIGIN_LIST:
            # the first len(cw)-1 words match exactly, the last word of the country is interleaved with the origin
            if len(toks) < len(cw): continue
            if cw[:-1] != toks[:len(cw) - 1]: continue
            merged = toks[len(cw) - 1]
            if _interleave(cw[-1], o, merged):
                return c, o, " ".join(toks[len(cw):])
    return None, None, rest

def parse_nabsa_lineup(text, issue):
    rows, bad = [], []
    for line in text.splitlines():
        m = re.search(r"^(.*?) (load|disch|discharge) ([\d][\d .,]*?) ([A-Z(].*)$", line)
        if not m:
            continue
        head, op, tons, rest = m.groups()
        if op != "load":
            continue
        cargo, rest2 = _cargo(rest)
        dest, origin, charterer = split_dest_origin(rest2) if cargo else (None, None, rest)
        if not cargo or not dest:
            bad.append(line[:170])
        eta = re.search(r"(ETA(?: REC| CZONE)?|ETB|ETF) (\d{2})/(\d{2})", head)
        rows.append({"head": re.sub(r"( (ETA|ETB|ETF|ETS|AT|REC|CZONE|BERTHED|SHIFTING|ANCHORED|\d{2}/\d{2}))+$", "", head), "tons": _tons_es(tons), "cargo": cargo or "UNPARSED",
                     "destination": dest or "UNPARSED", "origin": origin, "charterer": charterer, "eta": f"{eta.group(2)}/{eta.group(3)}" if eta else None,
                     "eta_kind": eta.group(1) if eta else None, "raw": line[:200] if not (cargo and dest) else ""})
    return rows, bad

def nabsa_reports():
    """Argentine vessel reports from Agencia Maritima Nabsa: sailed vessels (month to date) and line-ups (current + 4 prior issues).
    Rows are archived so monthly totals build up over time. Raw text is kept for checking the parser."""
    import io, pdfplumber
    raw_dir = os.path.join(DATA, "lineups", "raw")
    os.makedirs(raw_dir, exist_ok=True)
    out = {"sailed": [], "lineup": [], "bad": []}
    for kind, base in (("sailed", "vessels_sailed_"), ("lineup", "vessel_")):
        for suffix in ["prior4", "prior3", "prior2", "prior1", "update"]:   # oldest first, so the newest issue wins in the archive
            url = NABSA + base + suffix + ".pdf"
            try:
                r = requests.get(url, headers=UA, timeout=60)
                if r.status_code != 200 or r.content[:4] != b"%PDF":
                    continue
                with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                    text = "\n".join((p.extract_text() or "") for p in pdf.pages)
                with open(os.path.join(raw_dir, f"{kind}_{suffix}.txt"), "w") as fh:
                    fh.write(url + "\n" + text[:300000])
                if suffix == "update":
                    with open(os.path.join(raw_dir, f"{kind}_{suffix}.pdf"), "wb") as fh:
                        fh.write(r.content)
                if kind == "sailed":
                    m = re.search(r"BUENOS AIRES, (\d{1,2})-([A-Za-z]{3})-(\d{2})", text)
                    issue = dt.datetime.strptime(" ".join(m.groups()), "%d %b %y").strftime("%Y-%m-%d") if m else None
                    rows, bad = parse_nabsa_sailed(text)
                else:
                    m = re.search(r"Line Up: ([A-Za-z]+ \d{1,2}, \d{4})", text)
                    issue = dt.datetime.strptime(m.group(1), "%B %d, %Y").strftime("%Y-%m-%d") if m else None
                    rows, bad = parse_nabsa_lineup(text, issue)
                for i, r_ in enumerate(rows):
                    r_["issue"] = issue
                    r_["key"] = "|".join(str(r_.get(k)) for k in ("head", "date", "eta", "cargo", "destination", "tons", "issue" if kind == "lineup" else "x"))
                out[kind] += rows
                out["bad"] += [f"{kind}_{suffix}: {b}" for b in bad[:10]]
            except Exception as e:
                out["bad"].append(f"{kind}_{suffix} error: {str(e)[:120]}")
    return out

def indec_exports():
    """Official Argentine exports by NCM and destination (INDEC monthly files): keeps soy oil, meal, beans, sunflower oil and corn."""
    import io, zipfile
    keep = ("1507", "2304", "1201", "1512", "1005", "1517", "3826")
    for year in (2025, 2026):
        r = requests.get(f"https://comex.indec.gob.ar/files/zips/exports_{year}_M.zip", headers=UA, timeout=120, verify=False)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
        info = {"members": z.namelist()}
        rows = []
        for name in z.namelist():
            raw = z.read(name)
            txt = raw.decode("latin-1")
            info.setdefault("heads", {})[name] = txt[:600]
            lines = txt.splitlines()
            if not lines: continue
            sep = ";" if lines[0].count(";") >= lines[0].count(",") else ","
            hdr = [h.strip().strip('"') for h in lines[0].split(sep)]
            for ln in lines[1:]:
                cells = [c.strip().strip('"') for c in ln.split(sep)]
                if any(c.replace(".", "").startswith(keep) for c in cells[:6]):
                    rows.append(dict(zip(hdr, cells), _file=name))
        with open(os.path.join(DATA, "lineups", f"indec_exports_{year}.json"), "w") as fh:
            json.dump({"info": info, "rows": rows}, fh)

def indec_country_probe():
    """INDEC's destination codes (Pdes) come from the map layer in its comex web app: properties._id -> name.common."""
    base = "https://comex.indec.gob.ar/"
    r = requests.get(base, headers=UA, timeout=60, verify=False)
    js = re.findall(r'src="([^"]+\.js[^"]*)"', r.text)
    codes = {}
    for j in js:
        u = j if j.startswith("http") else base + j.lstrip("/")
        try:
            t = requests.get(u, headers=UA, timeout=60, verify=False).text
        except Exception:
            continue
        for m in re.finditer(r'"_id":(\d+),"name":\{"common":"([^"]+)"', t):
            codes[m.group(1)] = m.group(2)
    if len(codes) < 50:
        raise ValueError(f"only {len(codes)} country codes found")
    with open(os.path.join(DATA, "lineups", "indec_countries.json"), "w") as fh:
        json.dump(dict(sorted(codes.items())), fh, indent=0, ensure_ascii=False)

def comexstat_exports():
    """Official Brazilian exports by NCM and destination (Comex Stat API), soybean oil crude and refined, monthly."""
    body = {"flow": "export", "monthDetail": True, "period": {"from": "2025-01", "to": "2026-12"},
            "filters": [{"filter": "ncm", "values": ["15071000", "15079011", "15079019"]}],
            "details": ["country", "ncm"], "metrics": ["metricKG", "metricFOB"]}
    last = None
    for attempt in range(4):
        r = requests.post("https://api-comexstat.mdic.gov.br/general?language=en", json=body,
                          headers={**UA, "Content-Type": "application/json"}, timeout=90, verify=False)
        last = r
        if r.status_code == 200:
            with open(os.path.join(DATA, "lineups", "comexstat_soyoil.json"), "w") as fh:
                fh.write(r.text)
            return True
        time.sleep(15)
    raise ValueError(f"comexstat {last.status_code}: {last.text[:150]}")

def lineup_probes():
    """One-off checks of other sources for cross-checking Argentine and Brazilian shipments."""
    res = {}
    try:
        r = requests.get("https://nabsa.info/", headers=UA, timeout=30)
        links = sorted(set(re.findall(r'href="([^"]+)"', r.text)))[:120]
        res["nabsa_info"] = {"status": r.status_code, "links": links, "text": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))[:3000]}
    except Exception as e:
        res["nabsa_info"] = str(e)[:200]
    body = {"flow": "export", "monthDetail": True, "period": {"from": "2026-01", "to": "2026-12"},
            "filters": [{"filter": "ncm", "values": ["15071000", "15079011"]}],
            "details": ["country", "ncm"], "metrics": ["metricKG", "metricFOB"]}
    for u in ["https://api-comexstat.mdic.gov.br/general?language=en", "https://api-comexstat.mdic.gov.br/general"]:
        try:
            r = requests.post(u, json=body, headers={**UA, "Content-Type": "application/json"}, timeout=60, verify=False)
            res["comexstat " + u] = {"status": r.status_code, "head": r.text[:3000]}
            if r.status_code == 200:
                with open(os.path.join(DATA, "lineups", "comexstat_raw.json"), "w") as fh:
                    fh.write(r.text)
                break
        except Exception as e:
            res["comexstat " + u] = str(e)[:200]
    for u in ["https://comex.indec.gob.ar/", "https://comex.indec.gob.ar/files/zips/exports_2026_M.zip",
              "https://comex.indec.gob.ar/files/zips/exports_2025_M.zip", "https://www.indec.gob.ar/indec/web/Nivel4-Tema-3-2-40"]:
        try:
            r = requests.get(u, headers=UA, timeout=60, verify=False)
            res["indec " + u] = {"status": r.status_code, "type": r.headers.get("content-type"), "len": len(r.content),
                                 "head": (re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))[:1500] if "text" in (r.headers.get("content-type") or "") else ""),
                                 "links": sorted(set(re.findall(r'href="([^"]*(?:zip|csv|xls)[^"]*)"', r.text)))[:80] if "text" in (r.headers.get("content-type") or "") else []}
        except Exception as e:
            res["indec " + u] = str(e)[:200]
    with open(os.path.join(DATA, "lineups", "probes.json"), "w") as fh:
        json.dump(res, fh, indent=1)

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

def comtrade_uco():
    """China exports of HS 151800 (used cooking oil is reported under this code) by partner and month, from the UN Comtrade public preview API (no key)."""
    d = os.path.join(DATA, "uco"); os.makedirs(d, exist_ok=True)
    now = dt.date.today()
    periods = []
    for y in range(now.year - 2, now.year + 1):
        for m in range(1, 13):
            if dt.date(y, m, 1) <= now: periods.append(f"{y}{m:02d}")
    rows, log = [], {}
    for per in periods:
        url = ("https://comtradeapi.un.org/public/v1/preview/C/M/HS?reporterCode=156&flowCode=X&cmdCode=151800"
               f"&period={per}")
        for attempt in range(3):
            try:
                r = requests.get(url, headers=UA, timeout=90)
                if r.status_code == 429:
                    time.sleep(20 * (attempt + 1)); continue
                js = r.json() if r.status_code == 200 else {}
                data = js.get("data") or []
                log[per] = [r.status_code, len(data), (js.get("error") or "") if r.status_code == 200 else r.text[:200]]
                for x in data:
                    rows.append({"period": str(x.get("period")), "partner_code": x.get("partnerCode"), "net_kg": x.get("netWgt"),
                                 "qty": x.get("qty"), "qty_unit_code": x.get("qtyUnitCode"), "fob_usd": x.get("fobvalue") or x.get("primaryValue")})
                break
            except Exception as e:
                log[per] = ["error", str(e)[:200]]
                break
        time.sleep(4)
    with open(os.path.join(d, "comtrade_china_151800.json"), "w") as fh:
        json.dump({"fetched": now.isoformat(), "log": log, "rows": rows}, fh)

def eurostat_uco():
    """EU imports from China of CN 1518 00 (used cooking oil and other modified fats), by EU member state and month, from Eurostat Comext (mirror of China's exports to the EU)."""
    d = os.path.join(DATA, "uco"); os.makedirs(d, exist_ok=True)
    base = "https://ec.europa.eu/eurostat/api/comext/dissemination/statistics/1.0/data/DS-045409"
    out = {}
    for prod in ("151800", "15180095", "15180099", "15180091"):
        for since in ("2024-01", "202401", "2024M1"):
            url = f"{base}?format=JSON&lang=en&freq=M&partner=CN&flow=1&indicators=QUANTITY_IN_100KG&product={prod}&sinceTimePeriod={since}"
            try:
                r = requests.get(url, headers=UA, timeout=120)
                body = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:500]
            except Exception as e:
                r, body = None, str(e)[:300]
            out[prod] = {"status": getattr(r, "status_code", "error"), "since": since, "body": body}
            time.sleep(2)
            if getattr(r, "status_code", 0) == 200: break
    with open(os.path.join(d, "eurostat_eu_imports_from_china_1518.json"), "w") as fh:
        json.dump(out, fh)

def census_uco():
    """US imports of HTS 1518.00.40 (where UCO is entered) and of all HTS 1518.00, by country of origin and month, from the US Census Bureau trade API (no key)."""
    d = os.path.join(DATA, "uco"); os.makedirs(d, exist_ok=True)
    out = {}
    key = os.environ.get("CENSUS_KEY", "").strip()
    if not key:
        with open(os.path.join(d, "census_us_imports_1518.json"), "w") as fh:
            json.dump({"skipped": "no CENSUS_KEY secret set"}, fh)
        return
    variants = [("1518004000", "https://api.census.gov/data/timeseries/intltrade/imports/hs?get=CTY_CODE,CTY_NAME,GEN_VAL_MO,GEN_QY1_MO,UNIT_QY1&I_COMMODITY=1518004000&time=from+2024-01&key=" + key),
                ("1518004000_y", "https://api.census.gov/data/timeseries/intltrade/imports/hs?get=CTY_CODE,CTY_NAME,GEN_VAL_MO,GEN_QY1_MO,UNIT_QY1&I_COMMODITY=1518004000&YEAR=2025&key=" + key),
                ("151800", "https://api.census.gov/data/timeseries/intltrade/imports/hs?get=CTY_CODE,CTY_NAME,GEN_VAL_MO,CON_QY1_MO,UNIT_QY1&I_COMMODITY=151800&time=from+2024-01&key=" + key)]
    for code, url in variants:
        try:
            r = requests.get(url, headers=UA, timeout=120)
            try:
                body = r.json()
            except Exception:
                body = r.text[:800]
            out[code] = {"status": r.status_code, "body": body}
        except Exception as e:
            out[code] = {"status": "error", "body": str(e)[:300]}
        time.sleep(2)
    with open(os.path.join(d, "census_us_imports_1518.json"), "w") as fh:
        json.dump(out, fh)

def comtrade_us_uco():
    """US imports of HS 151800 (UCO is entered under 1518.00.40) by origin and month, from the UN Comtrade public preview API (no key)."""
    d = os.path.join(DATA, "uco"); os.makedirs(d, exist_ok=True)
    now = dt.date.today()
    periods = [f"{y}{m:02d}" for y in range(now.year - 2, now.year + 1) for m in range(1, 13) if dt.date(y, m, 1) <= now]
    rows, log = [], {}
    for per in periods:
        url = f"https://comtradeapi.un.org/public/v1/preview/C/M/HS?reporterCode=842&flowCode=M&cmdCode=151800&period={per}"
        for attempt in range(3):
            try:
                r = requests.get(url, headers=UA, timeout=90)
                if r.status_code == 429:
                    time.sleep(20 * (attempt + 1)); continue
                js = r.json() if r.status_code == 200 else {}
                data = js.get("data") or []
                log[per] = [r.status_code, len(data)]
                for x in data:
                    rows.append({"period": str(x.get("period")), "partner_code": x.get("partnerCode"), "net_kg": x.get("netWgt"),
                                 "qty": x.get("qty"), "qty_unit_code": x.get("qtyUnitCode"), "value_usd": x.get("primaryValue")})
                break
            except Exception as e:
                log[per] = ["error", str(e)[:200]]; break
        time.sleep(4)
    with open(os.path.join(d, "comtrade_us_imports_151800.json"), "w") as fh:
        json.dump({"fetched": now.isoformat(), "log": log, "rows": rows}, fh)

def magyp_lineups():
    """Argentine Agriculture Ministry (SSMA) port reports, independent of NABSA: vessels loaded and announced, next-15-day line-up,
    and the weekly internal port movements PDF; plus its ocean-freight files. Saved raw each run; parsed by the dashboard build."""
    d = os.path.join(DATA, "lineups", "magyp"); os.makedirs(d, exist_ok=True)
    base = "https://www.magyp.gob.ar/sitio/areas/ss_mercados_agropecuarios/logistica/_archivos/"
    lu = "000022_Posici%C3%B3n%20de%20Buques%20en%20Puertos%20y%20Anunciados%20(Line%20up)/"
    fl = "000010_Fletes%20Internacionales/"
    urls = {
        "cargados.html": base + lu + "000050_Buques%20Anunciados%20y%20Cargados.php",
        "proximos15.html": base + lu + "000052_Buques%20Anunciados,%20Pr%C3%B3ximos%2015%20D%C3%ADas.php",
        "movimientos_actual.pdf": base + lu + "000053_Movimientos%20Portuarios%20Internos%20-%20Actual.pdf",
        "flete_maritimo.xlsx": base + fl + "flete-maritimo.xlsx",
        "flete_semanal.html": base + fl + "000010_Informe%20Semanal%20Actual.php",
        "flete_diario.html": base + fl + "000010_Informe%20Diario%20Maritimo.php",
        "emb_destino.html": "https://www.magyp.gob.ar/sitio/areas/ss_mercados_agropecuarios/exportaciones/_archivos/000030_Embarques%20-%20Exportaciones%20de%20Granos,%20Aceites%20y%20Subproductos/000030_Por%20Destino.php?accion=imp",
        "emb_puerto.html": "https://www.magyp.gob.ar/sitio/areas/ss_mercados_agropecuarios/exportaciones/_archivos/000030_Embarques%20-%20Exportaciones%20de%20Granos,%20Aceites%20y%20Subproductos/000030_Por%20Puerto.php?accion=imp",
        "emb_ranking.html": "https://www.magyp.gob.ar/sitio/areas/ss_mercados_agropecuarios/exportaciones/_archivos/000020_Ranking%20Exportaciones%20por%20Exportador%20de%20Granos%20y%20Subproductos/000001_Ranking_Exportaciones_Actual.php",
        "emb_base.html": "https://www.magyp.gob.ar/sitio/areas/ss_mercados_agropecuarios/exportaciones/_archivos/000033_Base%20de%20Datos%20de%20Transporte%20y%20Embarque%20de%20Granos/",
        "djve.html": "https://www.magyp.gob.ar/sitio/areas/ss_mercados_agropecuarios/areas/granos/_archivos/000058_Estad%C3%ADsticas/000020_Compras%20y%20DJVE%20de%20Granos.php?accion=imp",
    }
    log = {}
    for name, url in urls.items():
        try:
            r = requests.get(url, headers=UA, timeout=60)
            log[name] = [r.status_code, len(r.content), r.headers.get("content-type", "")]
            if r.status_code == 200 and len(r.content) > 500:
                with open(os.path.join(d, name), "wb") as fh: fh.write(r.content)
        except Exception as ex:
            log[name] = ["error", str(ex)[:200]]
    log["_fetched"] = dt.datetime.utcnow().isoformat()
    with open(os.path.join(d, "log.json"), "w") as fh: json.dump(log, fh)

def price_probe():
    """Look up Investing.com instrument ids for ICE gasoil and MATIF rapeseed (search results saved for inspection)."""
    d = os.path.join(DATA, "probe_px"); os.makedirs(d, exist_ok=True)
    from curl_cffi import requests as cr
    out = {}
    for q in ["london gas oil", "gasoil", "rapeseed", "rapeseed futures", "colza"]:
        u = "https://api.investing.com/api/search/v2/search?q=" + requests.utils.quote(q)
        try:
            r = cr.get(u, impersonate="chrome", headers={"domain-id": "www"}, timeout=30)
            js = r.json() if r.status_code == 200 else {}
            out[q] = [{k: x.get(k) for k in ("id", "name", "symbol", "exchange", "flag", "type", "url")} for x in (js.get("quotes") or [])[:12]] or [r.status_code, r.text[:300]]
        except Exception as e:
            out[q] = ["error", str(e)[:150]]
    with open(os.path.join(d, "search.json"), "w") as fh: json.dump(out, fh, indent=1)

def main(mode):
    if mode == "probe_px":
        price_probe(); return
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    status, latest = {"run_utc": now, "mode": mode, "errors": {}}, {}
    rng = "2y" if mode == "backfill" else "10d"
    symbols = CONTINUOUS + FX + AGRI + FREIGHT + contract_symbols()
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
        rows = cot()
        append_csv(os.path.join(DATA, "cot_disaggregated.csv"), rows, key="key")
    except Exception as e:
        status["errors"]["cot"] = str(e)[:200]
    try:
        rows = cot_agri()
        append_csv(os.path.join(DATA, "cot_agri.csv"), rows, key="key")
    except Exception as e:
        status["errors"]["cot_agri"] = str(e)[:200]
    try:
        rows, misses = euronext_cot(mode)
        append_csv(os.path.join(DATA, "euronext_cot.csv"), rows, key="key")
        if misses:
            status["euronext_cot_misses"] = misses
    except Exception as e:
        status["errors"]["euronext_cot"] = str(e)[:200]
    try:
        ep = euronext_prices()
        append_csv(os.path.join(DATA, "euronext_prices.csv"), [{"key": f"{r['price_date']}_{r['product']}_{r['delivery']}", **r} for r in ep], key="key")
    except Exception as e:
        status["errors"]["euronext_prices"] = str(e)[:200]
    try:
        nb = nabsa_reports()
        append_csv(os.path.join(DATA, "lineups", "nabsa_sailed.csv"), nb["sailed"], key="key")
        lu = [dict(r, key=r["key"] + "|" + str(r["issue"])) for r in nb["lineup"]]
        append_csv(os.path.join(DATA, "lineups", "nabsa_lineup.csv"), lu, key="key")
        status["nabsa_rows"] = {"sailed": len(nb["sailed"]), "lineup": len(nb["lineup"]), "unparsed_examples": nb["bad"][:15]}
    except Exception as e:
        status["errors"]["nabsa"] = str(e)[:200]
    if mode in ("backfill", "probe") or dt.datetime.utcnow().minute < 15 and dt.datetime.utcnow().hour == 6:
        for name, fn in (("indec", indec_exports), ("comexstat", comexstat_exports), ("indec_countries", indec_country_probe), ("eurostat_uco", eurostat_uco), ("census_uco", census_uco), ("comtrade_us_uco", comtrade_us_uco)):
            try:
                fn()
            except Exception as e:
                status["errors"][name] = str(e)[:200]
    try:
        b = bunkers()
        latest["_bunkers"] = b
        append_csv(os.path.join(DATA, "bunkers.csv"), [{"time_utc": now, **b}])
    except Exception as e:
        status["errors"]["bunkers"] = str(e)[:200]
    try:
        bdi = baltic_headline()
        append_csv(os.path.join(DATA, "freight.csv"), [{"time_utc": now, "bdi_headline": bdi}])
    except Exception as e:
        status["errors"]["bdi"] = str(e)[:200]
    if mode == "backfill":
        try:
            status["euronext_found"] = euronext_probe()
        except Exception as e:
            status["errors"]["euronext"] = str(e)[:200]
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
