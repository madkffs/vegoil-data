"""One-off pull of public data for the largest S&P 500 companies (research branch only)."""
import io, json, os, time, re, traceback
import requests, pandas as pd, numpy as np, yfinance as yf

OUT = "out"; os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
SEC_UA = {"User-Agent": "vegoil-research research@example.com"}
status = {}

def save(name, obj):
    with open(os.path.join(OUT, name), "w") as f: json.dump(obj, f, default=str)

def step(name):
    def deco(fn):
        def run(*a, **k):
            t = time.time()
            try:
                r = fn(*a, **k); status[name] = f"ok {time.time()-t:.0f}s"; return r
            except Exception as e:
                status[name] = "failed: " + repr(e)[:300]; traceback.print_exc(); return None
        return run
    return deco

@step("constituents")
def constituents():
    h = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", headers=UA, timeout=60).text
    t = pd.read_html(io.StringIO(h))[0]
    t.to_csv(f"{OUT}/constituents.csv", index=False); return t

@step("slickcharts")
def slick():
    h = requests.get("https://www.slickcharts.com/sp500", headers=UA, timeout=60)
    h.raise_for_status()
    t = [x for x in pd.read_html(io.StringIO(h.text)) if "Weight" in " ".join(map(str, x.columns))][0]
    t.to_csv(f"{OUT}/slickcharts.csv", index=False); return t

@step("market_caps_yf")
def caps(symbols):
    rows = []
    for s in symbols:
        y = s.replace(".", "-")
        for k in range(3):
            try:
                fi = yf.Ticker(y).fast_info
                rows.append({"symbol": s, "market_cap": fi["marketCap"], "last": fi["lastPrice"]}); break
            except Exception as e:
                time.sleep(2 + 3 * k)
        time.sleep(0.15)
    d = pd.DataFrame(rows); d.to_csv(f"{OUT}/market_caps.csv", index=False); return d

@step("yf_details")
def details(symbols):
    info, est = {}, {}
    for s in symbols:
        y = s.replace(".", "-"); t = yf.Ticker(y)
        for k in range(3):
            try:
                info[s] = t.info; break
            except Exception: time.sleep(3 + 5 * k)
        e = {}
        for attr in ["eps_trend", "earnings_estimate", "growth_estimates", "eps_revisions", "revenue_estimate"]:
            try:
                v = getattr(t, attr)
                if v is not None and len(v): e[attr] = v.reset_index().to_dict(orient="records")
            except Exception as ex: e[attr + "_error"] = repr(ex)[:200]
        for attr in ["income_stmt", "cashflow", "quarterly_income_stmt"]:
            try:
                v = getattr(t, attr)
                if v is not None and len(v): e[attr] = {str(c.date()): v[c].dropna().to_dict() for c in v.columns}
            except Exception as ex: e[attr + "_error"] = repr(ex)[:200]
        est[s] = e; time.sleep(0.3)
    save("yf_info.json", info); save("yf_estimates.json", est)

@step("prices")
def prices(symbols):
    ys = [s.replace(".", "-") for s in symbols] + ["^GSPC", "SPY", "RSP"]
    d = yf.download(ys, start="2019-06-01", interval="1d", auto_adjust=False, progress=False, threads=True)
    d["Close"].to_csv(f"{OUT}/close_daily.csv"); d["Adj Close"].to_csv(f"{OUT}/adjclose_daily.csv")

@step("sec_companyfacts")
def sec(cik_map):
    keep = ["EarningsPerShareDiluted", "EarningsPerShareBasic", "NetIncomeLoss", "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
            "WeightedAverageNumberOfDilutedSharesOutstanding", "NetCashProvidedByUsedInOperatingActivities",
            "PaymentsToAcquirePropertyPlantAndEquipment", "StockholdersEquity", "OperatingIncomeLoss", "InterestExpense"]
    res = {}
    for s, cik in cik_map.items():
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json"
        for k in range(3):
            try:
                r = requests.get(url, headers=SEC_UA, timeout=60); r.raise_for_status(); j = r.json(); break
            except Exception: time.sleep(2 + 3 * k); j = None
        if not j: res[s] = {"error": "fetch"}; continue
        facts = {}
        for ns in ("us-gaap", "ifrs-full"):
            for tag, v in j.get("facts", {}).get(ns, {}).items():
                if tag in keep:
                    units = v.get("units", {})
                    facts[tag] = {u: [x for x in arr if x.get("form") in ("10-K", "10-K/A", "10-Q", "20-F", "40-F")] for u, arr in units.items()}
        res[s] = {"name": j.get("entityName"), "facts": facts}
        time.sleep(0.15)
    save("sec_facts.json", res)

@step("multpl")
def multpl():
    out = {}
    for k, u in {"pe": "https://www.multpl.com/s-p-500-pe-ratio/table/by-month",
                 "earnings": "https://www.multpl.com/s-p-500-earnings/table/by-month",
                 "shiller_pe": "https://www.multpl.com/shiller-pe/table/by-month",
                 "div_yield": "https://www.multpl.com/s-p-500-dividend-yield/table/by-month",
                 "earnings_yield": "https://www.multpl.com/s-p-500-earnings-yield/table/by-month"}.items():
        try:
            h = requests.get(u, headers=UA, timeout=60); h.raise_for_status()
            t = pd.read_html(io.StringIO(h.text))[0]; t.to_csv(f"{OUT}/multpl_{k}.csv", index=False); out[k] = len(t)
        except Exception as e: out[k] = repr(e)[:200]
    return out

@step("spdji_eps")
def spdji():
    u = "https://www.spglobal.com/spdji/en/documents/additional-material/sp-500-eps-est.xlsx"
    r = requests.get(u, headers=UA, timeout=60); r.raise_for_status()
    open(f"{OUT}/sp-500-eps-est.xlsx", "wb").write(r.content)

if __name__ == "__main__":
    c = constituents()
    sl = slick()
    syms = list(c["Symbol"]) if c is not None else []
    if sl is not None:
        scol = [x for x in sl.columns if "Symbol" in str(x)][0]
        order = [str(x) for x in sl[scol]]
    else:
        mc = caps(syms)
        order = list(mc.sort_values("market_cap", ascending=False)["symbol"]) if mc is not None else syms
    top = order[:62]
    if sl is None: pass
    else: caps(top)
    details(top)
    prices(top)
    cik = {}
    if c is not None:
        cc = c.set_index("Symbol")["CIK"].to_dict()
        for s in top:
            k = cc.get(s) or cc.get(s.replace("-", ".")) or cc.get(s.replace(".", "-"))
            if k is not None and not pd.isna(k): cik[s] = int(k)
    sec(cik)
    multpl()
    spdji()
    save("status.json", {"status": status, "top": top, "utc": pd.Timestamp.utcnow().isoformat()})
    print(json.dumps(status, indent=1))
