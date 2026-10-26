"""Builds the JSON files behind the veg oil market dashboard from this repo's data/ folder.
Usage: python dashboard/build.py   -> writes dashboard/out/*.json
Everything here is public, delayed market data."""
import json, os
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "dashboard", "out")
os.makedirs(OUT, exist_ok=True)

def load(n):
    p = os.path.join(D, "daily", n)
    d = pd.read_csv(p); d["date"] = pd.to_datetime(d["time_utc"]).dt.normalize()
    return d.groupby("date")["close"].last().dropna()

def _clean(o):
    if isinstance(o, dict): return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list): return [_clean(v) for v in o]
    if isinstance(o, (float, np.floating)) and not np.isfinite(o): return None
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, np.floating): return float(o)
    return o

def dump(name, obj):
    with open(os.path.join(OUT, name), "w") as fh:
        json.dump(_clean(obj), fh, indent=0, allow_nan=False)

# ---------- spreads ----------
zl, zm, zs, ho, myr = [load(f) for f in ["ZL_F.csv", "ZM_F.csv", "ZS_F.csv", "HO_F.csv", "MYR_X.csv"]]
fcpo, y0, p0 = load("FCPO.csv"), load("DCE_Y0.csv"), load("DCE_P0.csv")
zlh, zlz = load("ZLH27_CBT.csv"), load("ZLZ26_CBT.csv")
idx = zl.index
al = lambda s: s.reindex(idx.union(s.index)).ffill().reindex(idx)
fc, my = al(fcpo), al(myr)
S = {"oilshare": zl * 11 / (zl * 11 + zm * 2.2) * 100, "crush": zl * 0.11 + zm * 0.022 - zs / 100,
     "boho": ho - zl / 100 * 7.37, "soy_palm": zl * 22.0462 - fc / my, "dce_y_p": al(y0) - al(p0), "zl_z_h": zlz - zlh}
META = {"oilshare": ("Oilshare", "%", 2), "crush": ("Board crush", "USD/bu", 3), "boho": ("BOHO (heating oil – soyoil)", "USD/gal", 3),
        "soy_palm": ("Soyoil – palm (CBOT vs Bursa)", "USD/t", 1), "dce_y_p": ("Dalian soyoil – palm olein", "CNY/t", 0),
        "zl_z_h": ("Soyoil Dec26 – Mar27", "c/lb", 2)}
df = pd.DataFrame(S); df = df[df.index >= df.index.max() - pd.Timedelta(days=730)]
o = df.reset_index().rename(columns={"index": "date"}); o["date"] = o["date"].dt.strftime("%Y-%m-%d")
dump("spreads_daily.json", [{k: (None if (k != "date" and pd.isna(v)) else (round(float(v), 4) if k != "date" else v)) for k, v in r.items()} for r in o.to_dict("records")])
stats = []
for k, (name, unit, dp) in META.items():
    s = df[k].dropna(); last, prev = float(s.iloc[-1]), float(s.iloc[-2]); s1 = s[s.index >= s.index.max() - pd.Timedelta(days=365)]
    rd = (lambda v: round(v, dp)) if dp else (lambda v: int(round(v)))
    stats.append({"metric": k, "name": name, "unit": unit, "decimals": dp, "date": f"{s.index[-1]:%Y-%m-%d}", "last": rd(last), "prev": rd(prev),
                  "change": rd(last - prev), "pct_1y": int(round((s1 < last).mean() * 100)), "pct_2y": int(round((s < last).mean() * 100)),
                  "median_2y": rd(float(s.median())), "min_2y": rd(float(s.min())), "max_2y": rd(float(s.max()))})
dump("spread_stats.json", stats)

# ---------- curve shape ----------
LAB = {"F": "Jan", "H": "Mar", "K": "May", "N": "Jul", "Q": "Aug", "U": "Sep", "V": "Oct", "Z": "Dec"}
files = sorted([f for f in os.listdir(os.path.join(D, "daily")) if f.startswith("ZL") and f.endswith("_CBT.csv")],
               key=lambda f: (int(f[3:5]), "FGHJKMNQUVXZ".index(f[2])))
cur = []
for f in files:
    s = load(f)
    if s.index.max() < idx.max() - pd.Timedelta(days=5): continue
    wk = s[s.index <= s.index.max() - pd.Timedelta(days=7)]
    cur.append({"contract": f[:5], "month": LAB.get(f[2], f[2]) + " " + f[3:5], "last": float(s.iloc[-1]), "week_ago": float(wk.iloc[-1]), "date": f"{s.index[-1]:%Y-%m-%d}"})
cur = cur[:6]
dump("zl_curve_shape.json", [{"contract": r["contract"], "month": r["month"], "vs_front": round(r["last"] - cur[0]["last"], 2),
                               "vs_front_week_ago": round(r["week_ago"] - cur[0]["week_ago"], 2), "date": r["date"]} for r in cur])

# ---------- FX ----------
FXN = {"MYR_X": ("USD/MYR", "Malaysia"), "IDR_X": ("USD/IDR", "Indonesia"), "INR_X": ("USD/INR", "India"), "CNY_X": ("USD/CNY", "China"),
       "BRL_X": ("USD/BRL", "Brazil"), "ARS_X": ("USD/ARS", "Argentina"), "EGP_X": ("USD/EGP", "Egypt"), "CAD_X": ("USD/CAD", "Canada"),
       "EURUSD_X": ("EUR/USD", "Eurozone"), "DX-Y_NYB": ("Dollar index", "DXY")}
fx = []
for f, (pair, mk) in FXN.items():
    try: s = load(f + ".csv")
    except FileNotFoundError: continue
    m = s[s.index <= s.index.max() - pd.Timedelta(days=30)]
    fx.append({"pair": pair, "market": mk, "last": float(s.iloc[-1]), "chg_1d_pct": round(float((s.iloc[-1] / s.iloc[-2] - 1) * 100), 2),
               "chg_1m_pct": round(float((s.iloc[-1] / m.iloc[-1] - 1) * 100), 2), "date": f"{s.index[-1]:%Y-%m-%d}"})
dump("fx.json", fx)

# ---------- freight and bunkers ----------
fr = []
b = pd.read_csv(os.path.join(D, "bunkers.csv")) if os.path.exists(os.path.join(D, "bunkers.csv")) else None
if b is not None and len(b):
    last = b.iloc[-1]; prev = b.iloc[-2] if len(b) > 1 else None
    for fuel in ["VLSFO", "MGO", "IFO380"]:
        for port in ["Singapore", "Rotterdam", "Houston", "Fujairah", "Santos", "Global20"]:
            c = f"{fuel}_{port}"
            if c in b and pd.notna(last[c]):
                fr.append({"id": c, "fuel": fuel, "port": "Global 20-port average" if port == "Global20" else port, "usd_t": float(last[c]),
                           "time_utc": last["time_utc"]})
dump("bunkers.json", fr)
frt = []
bd = load("BDRY.csv")
frt.append({"id": "BDRY", "name": "Breakwave dry bulk freight futures ETF (BDRY)", "value": float(bd.iloc[-1]), "unit": "USD/share",
            "chg_1w_pct": round(float((bd.iloc[-1] / bd[bd.index <= bd.index.max() - pd.Timedelta(days=7)].iloc[-1] - 1) * 100), 2),
            "date": f"{bd.index[-1]:%Y-%m-%d}"})
fp = os.path.join(D, "freight.csv")
if os.path.exists(fp):
    f2 = pd.read_csv(fp).dropna(subset=["bdi_headline"])
    if len(f2):
        frt.append({"id": "BDI", "name": "Baltic Dry Index (from public headlines)", "value": float(f2.iloc[-1]["bdi_headline"]), "unit": "index points",
                    "chg_1w_pct": None, "date": str(f2.iloc[-1]["time_utc"])[:10]})
dump("freight.json", frt)
dump("bdry_daily.json", [{"date": f"{d:%Y-%m-%d}", "close": float(v)} for d, v in bd[bd.index >= bd.index.max() - pd.Timedelta(days=730)].items()])

# ---------- fund positions: CBOT soy complex and corn, with estimate ----------
c = pd.read_csv(os.path.join(D, "cot_agri.csv")); c["date"] = pd.to_datetime(c["date"])
c["net"] = c["mm_long"] - c["mm_short"]
EST = {"7601": ("soybean_oil", "Soybean oil", "ZL_F.csv", "ZLZ26_CBT.csv"), "5602": ("soybeans", "Soybeans", "ZS_F.csv", "ZSX26_CBT.csv"),
       "26603": ("soybean_meal", "Soybean meal", "ZM_F.csv", "ZMZ26_CBT.csv"), "2602": ("corn", "Corn", "ZC_F.csv", "ZCZ26_CBT.csv")}
rows, fstats, est_delta = [], [], {}
for code, (k, lab, f, fe) in EST.items():
    px = load(f); pe = load(fe)
    x = c[c.code.astype(str) == code].sort_values("date").set_index("date")
    net = x["net"]; net = net[net.index >= net.index.max() - pd.Timedelta(days=730)]
    p = px.reindex(px.index.union(net.index)).ffill().reindex(net.index)
    dn, dp = net.diff(), np.log(p).diff(); ok = dn.notna() & dp.notna() & (dp.abs() < 0.15)
    beta = float(np.polyfit(dp[ok], dn[ok], 1)[0]); r2 = float(np.corrcoef(dp[ok], dn[ok])[0, 1] ** 2)
    ld, ln = net.index[-1], int(net.iloc[-1]); p0e = float(pe[pe.index <= ld].iloc[-1])
    for d, v in net.items(): rows.append({"id": f"{k}-{d:%Y%m%d}-o", "market": k, "date": f"{d:%Y-%m-%d}", "net": int(v), "kind": "official"})
    rows.append({"id": f"{k}-{ld:%Y%m%d}-e", "market": k, "date": f"{ld:%Y-%m-%d}", "net": ln, "kind": "estimate"})
    est = ln; series = {}
    for d, v in pe[pe.index > ld].items():
        est = int(round(ln + beta * np.log(v / p0e))); series[d] = est - ln
        rows.append({"id": f"{k}-{d:%Y%m%d}-e", "market": k, "date": f"{d:%Y-%m-%d}", "net": est, "kind": "estimate"})
    est_delta[code] = (series, pe)
    oi = float(x["open_interest"].iloc[-1])
    fstats.append({"market": k, "label": lab, "official_date": f"{ld:%Y-%m-%d}", "official_net": ln, "week_change": int(net.iloc[-1] - net.iloc[-2]),
                   "est_date": f"{(pe.index[-1] if len(series) else ld):%Y-%m-%d}", "est_net": est, "est_change": est - ln,
                   "pct_oi": round(ln / oi * 100, 1), "r2": round(r2, 2), "est_contract": fe.split("_")[0], "pct_2y": int(round((net < ln).mean() * 100))})
dump("funds.json", rows); dump("fund_stats.json", fstats)

# ---------- every agricultural market in dollars ----------
eur = load("EURUSD_X.csv")
ep = pd.read_csv(os.path.join(D, "euronext_prices.csv"))
ep["d"] = pd.to_datetime(ep["price_date"], format="%d %b %Y")
ep = ep[ep.d == ep.d.max()].sort_values("open_interest", ascending=False).drop_duplicates("product")
matif_px = {r["product"]: (float(r["settle"] or r["last"]), r["delivery"], f"{r['d']:%Y-%m-%d}") for _, r in ep.iterrows()}
palm_usd = (fcpo / myr.reindex(fcpo.index, method="ffill")).dropna()
# code: (label, group, price series, USD per contract per price unit, note)
AG = {
    "2602": ("Corn", "Grains", load("ZC_F.csv"), 50, ""), "1602": ("Wheat, Chicago SRW", "Grains", load("ZW_F.csv"), 50, ""),
    "1612": ("Wheat, KC HRW", "Grains", load("KE_F.csv"), 50, ""), "1626": ("Wheat, Minneapolis HRS", "Grains", load("KE_F.csv"), 50, "valued at KC wheat (no free HRS price)"),
    "4603": ("Oats", "Grains", load("ZO_F.csv"), 50, ""), "39601": ("Rough rice", "Grains", load("ZR_F.csv"), 2000, ""),
    "5602": ("Soybeans", "Oilseeds", load("ZS_F.csv"), 50, ""), "5603": ("Soybeans, mini", "Oilseeds", load("ZS_F.csv"), 10, ""),
    "26603": ("Soybean meal", "Oilseeds", load("ZM_F.csv"), 100, ""), "7601": ("Soybean oil", "Oilseeds", load("ZL_F.csv"), 600, ""),
    "37021": ("Palm oil, CME USD", "Oilseeds", palm_usd, 25, "valued at Bursa palm in USD"),
    "80732": ("Sugar No. 11", "Softs", load("SB_F.csv"), 1120, ""), "73732": ("Cocoa, ICE US", "Softs", load("CC_F.csv"), 10, ""),
    "83731": ("Coffee C", "Softs", load("KC_F.csv"), 375, ""), "33661": ("Cotton", "Softs", load("CT_F.csv"), 500, ""),
    "40701": ("Orange juice", "Softs", load("OJ_F.csv"), 150, ""),
    "57642": ("Live cattle", "Livestock", load("LE_F.csv"), 400, ""), "61641": ("Feeder cattle", "Livestock", load("GF_F.csv"), 500, ""),
    "54642": ("Lean hogs", "Livestock", load("HE_F.csv"), 400, ""),
}
dates = sorted(c.date.unique()); dates = [d for d in dates if d >= max(dates) - pd.Timedelta(days=730)]
pxat = lambda s, d: float(s[s.index <= d].iloc[-1]) if len(s[s.index <= d]) else np.nan
recs = []
for code, (lab, grp, s, mult, note) in AG.items():
    x = c[c.code.astype(str) == code].set_index("date")["net"]
    for d in dates:
        if d in x.index:
            recs.append({"m": code, "label": lab, "group": grp, "date": d, "net": float(x.loc[d]), "usd": float(x.loc[d]) * mult * pxat(s, d), "note": note})
# canola: ICE canola positions valued at MATIF rapeseed (no free canola price), constant at today's price
ca = c[c.code.astype(str) == "135731"].set_index("date")["net"]
rs_px, rs_del, rs_day = matif_px.get("ECO", (np.nan, "", ""))
for d in dates:
    if d in ca.index:
        recs.append({"m": "135731", "label": "Canola, ICE", "group": "Oilseeds", "date": d, "net": float(ca.loc[d]),
                     "usd": float(ca.loc[d]) * 20 * rs_px * pxat(eur, d), "note": f"valued at MATIF rapeseed {rs_del} (no free canola price)"})
# MATIF: Euronext investment funds net, 50 t lots, valued at today's settlement (no free price history)
ec = pd.read_csv(os.path.join(D, "euronext_cot.csv")); ec["date"] = pd.to_datetime(ec["date"])
for prod, lab in {"EBM": "Wheat, MATIF milling", "ECO": "Rapeseed, MATIF", "EMA": "Corn, MATIF"}.items():
    e = ec[ec["product"] == prod].sort_values("date").set_index("date")
    net = (e["funds_long"] - e["funds_short"])
    px, dl, day = matif_px.get(prod, (np.nan, "", ""))
    for d in dates:
        w = net[net.index <= d + pd.Timedelta(days=4)]   # Friday report nearest the CFTC Tuesday
        w = w[w.index >= d - pd.Timedelta(days=4)]
        if len(w):
            recs.append({"m": prod, "label": lab, "group": "MATIF", "date": d, "net": float(w.iloc[-1]),
                         "usd": float(w.iloc[-1]) * 50 * px * pxat(eur, d), "note": f"Euronext investment funds; valued at {dl} settlement of {day}"})
R = pd.DataFrame(recs)
tot = R.groupby("date")["usd"].sum(min_count=1)
last_d = max(dates)
cnt = R[R.date == last_d].groupby("date").size().iloc[0]
tot = tot[R.groupby("date").size().reindex(tot.index) >= cnt - 2]
tot = tot.dropna()
avg = float(tot.mean())
# estimate for the four CBOT markets with daily prices
est_days = sorted(set().union(*[set(v[0].keys()) for v in est_delta.values()]))
est_rows = []
for d in est_days:
    add = 0.0
    for code, (series, pe) in est_delta.items():
        lab, grp, s, mult, note = AG[code]
        base = float(R[(R.m == code) & (R.date == last_d)]["net"].iloc[0])
        add += (base + series.get(d, 0)) * mult * pxat(pe, d) - base * mult * pxat(s, last_d)
    est_rows.append((d, float(tot.loc[last_d]) + add))
series = [{"id": f"{d:%Y%m%d}-o", "date": f"{d:%Y-%m-%d}", "kind": "official", "usd_bn": round(v / 1e9, 3)} for d, v in tot.items()]
series += [{"id": f"{last_d:%Y%m%d}-e", "date": f"{last_d:%Y-%m-%d}", "kind": "estimate", "usd_bn": round(float(tot.loc[last_d]) / 1e9, 3)}]
series += [{"id": f"{d:%Y%m%d}-e", "date": f"{d:%Y-%m-%d}", "kind": "estimate", "usd_bn": round(v / 1e9, 3)} for d, v in est_rows]
dump("agri_notional.json", series)
L = R[R.date == last_d]; P = R[R.date == sorted(dates)[-2]]
mk = []
for _, r in L.sort_values("usd", key=abs, ascending=False).iterrows():
    hist = R[R.m == r.m].set_index("date")["usd"]
    prev = P[P.m == r.m]
    mk.append({"market": r.m, "label": r.label, "group": r.group, "net": int(round(r.net)),
               "week_change": int(round(r.net - prev.net.iloc[0])) if len(prev) else None,
               "usd_bn": round(r.usd / 1e9, 2), "avg_2y_usd_bn": round(float(hist.mean()) / 1e9, 2),
               "vs_avg_usd_bn": round((r.usd - float(hist.mean())) / 1e9, 2), "pct_2y": int(round((hist < r.usd).mean() * 100)), "note": r.note})
est_now = est_rows[-1][1] if est_rows else float(tot.loc[last_d])
mk.append({"market": "total", "label": f"All {len(L)} agricultural markets", "group": "Total", "net": None, "week_change": None,
           "usd_bn": round(float(tot.loc[last_d]) / 1e9, 2), "avg_2y_usd_bn": round(avg / 1e9, 2), "vs_avg_usd_bn": round((float(tot.loc[last_d]) - avg) / 1e9, 2),
           "pct_2y": int(round((tot < float(tot.loc[last_d])).mean() * 100)), "note": ""})
summary = {"market": "total", "official_date": f"{last_d:%Y-%m-%d}", "est_date": f"{(est_rows[-1][0] if est_rows else last_d):%Y-%m-%d}",
           "official_usd_bn": round(float(tot.loc[last_d]) / 1e9, 2), "est_usd_bn": round(est_now / 1e9, 2), "avg_2y_usd_bn": round(avg / 1e9, 2),
           "vs_avg_usd_bn": round((est_now - avg) / 1e9, 2), "pct_2y": int(round((tot < est_now).mean() * 100)), "markets": len(L)}
dump("agri_funds.json", mk); dump("agri_summary.json", [summary])
print(json.dumps(summary)); print(pd.DataFrame(mk)[["label", "group", "net", "usd_bn", "avg_2y_usd_bn", "pct_2y"]].to_string())

# ---------- export line-ups and shipments (Argentina: INDEC customs + NABSA; Brazil: Comex Stat customs) ----------
import collections, re as _re
LU = os.path.join(D, "lineups")
names = json.load(open(os.path.join(LU, "indec_countries.json"))) if os.path.exists(os.path.join(LU, "indec_countries.json")) else {}
names["999"] = "Undisclosed (customs confidentiality)"
PRODUCTS = {  # product: (INDEC NCM prefixes, NABSA cargo names)
    "Soybean oil": (("15071000",), ("SOYBEAN OIL",)),
    "Soybean meal": (("2304",), ("SOYBEANMEAL", "SOYBEAN MEAL")),
    "Sunflower oil": (("151211",), ("SUN FLOWER OIL", "SUNFLOWER OIL")),
    "Soybeans": (("1201",), ("SOYA BEAN", "SOYBEANS", "SOYBEAN")),
    "Corn": (("1005",), ("CORN",)),
}
def title(s): return " ".join(w.capitalize() if len(w) > 3 or w in ("USA",) else w.lower() if w in ("AND", "OF", "THE") else w.capitalize() for w in str(s).split())
ALIAS = {"Korea (republic Of South Korea)": "South Korea", "Korea": "South Korea", "Russian Federation": "Russia", "Holland": "Netherlands",
         "Not Available": "Not stated", "To Orders": "Not stated", "Optional": "Not stated", "United Arab Emirates": "UAE",
         "United States": "USA", "United Kingdom": "UK", "Dominican Republic": "Dominican Rep."}
ALIAS.update({"Venezuela": "Venezuela", "Iran": "Iran", "Syrian Arab Republic": "Syria", "Viet Nam": "Vietnam", "Korea": "South Korea",
              "United States Of America": "USA", "China - Hong Kong": "Hong Kong", "Türkiye": "Turkey", "Russian Federation": "Russia",
              "Tanzania, United Republic Of": "Tanzania", "Netherlands (kingdom Of The)": "Netherlands"})
def norm(n):
    t = title(_re.sub(r"\s*\((the|Bolivarian Republic of|Islamic Republic of|Republic of|Special Administrative Region|Plurinational State of|Kingdom of the)\)", "", str(n), flags=_re.I))
    t = _re.sub(r"\s*\(.*\)$", "", t).strip()
    return ALIAS.get(t, t)
monthly = []
# INDEC customs, Argentina
indec = collections.defaultdict(float)
for y in (2025, 2026):
    p = os.path.join(LU, f"indec_exports_{y}.json")
    if not os.path.exists(p): continue
    for r in json.load(open(p))["rows"]:
        if not r["_file"].startswith("exponm") or r["Pnet(kg)"] in ("s", ""): continue
        for prod, (ncms, _) in PRODUCTS.items():
            if r["NCM"].startswith(ncms):
                indec[(prod, f"{r['Año']}-{r['Mes']}", norm(names.get(r["Pdes"], "INDEC code " + r["Pdes"])) if r["Pdes"] != "999" else names["999"])] += float(r["Pnet(kg)"].replace(",", ".")) / 1000
for (prod, m, dest), t in indec.items():
    monthly.append({"country": "Argentina", "product": prod, "month": m, "destination": dest, "tons": round(t), "basis": "Customs (INDEC)"})
indec_months = sorted({m for (_, m, _) in indec})
# NABSA sailed: Argentina for months not yet in customs data; Paraguay (cargo of Paraguayan origin loaded at Argentine and Uruguayan river ports) for every month, as no free monthly Paraguayan customs data by destination exists
sail_p = os.path.join(LU, "nabsa_sailed.csv")
sailed_all = pd.read_csv(sail_p) if os.path.exists(sail_p) else pd.DataFrame()
sailed = pd.DataFrame()
if len(sailed_all):
    sailed_all = sailed_all[sailed_all["date"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$")].copy()   # drop rows whose date didn't parse
    sailed_all["month"] = sailed_all["date"].str.slice(0, 7)
    # the sailed report is cumulative for the month: use only the latest issue that covers each month
    latest = sailed_all.dropna(subset=["issue"]).groupby("month")["issue"].max()
    sailed_all = sailed_all[sailed_all.apply(lambda r: r["issue"] == latest.get(r["month"]), axis=1)]
    sailed = sailed_all[sailed_all["origin"] == "ARGENTINA"].copy()   # Paraguayan and Bolivian cargo loaded in Argentina is not an Argentine export
    for origin, country in (("ARGENTINA", "Argentina"), ("PARAGUAY", "Paraguay")):
        so = sailed_all[sailed_all["origin"] == origin]
        if not len(so): continue
        last_d = pd.to_datetime(so["date"]).max()
        for prod, (_, cargos) in PRODUCTS.items():
            s = so[so["cargo"].isin(cargos)]
            for (m, dest), t in s.groupby(["month", "destination"])["tons"].sum().items():
                if country == "Argentina" and m in indec_months: continue
                done = m < f"{last_d:%Y-%m}"
                monthly.append({"country": country, "product": prod, "month": m, "destination": norm(dest), "tons": round(float(t)),
                                "basis": ("Sailed, whole month (NABSA)" if done else f"Sailed to {last_d:%-d %b} (NABSA)")})
# Comex Stat customs, Brazil (soybean oil, crude and refined)
cs_p = os.path.join(LU, "comexstat_soyoil.json")
if os.path.exists(cs_p):
    agg = collections.defaultdict(float)
    for r in json.load(open(cs_p))["data"]["list"]:
        agg[(f"{r['year']}-{r['monthNumber']}", norm(r["country"]))] += float(r["metricKG"]) / 1000
    for (m, dest), t in agg.items():
        monthly.append({"country": "Brazil", "product": "Soybean oil", "month": m, "destination": dest, "tons": round(t), "basis": "Customs (Comex Stat)"})
# keep the last 7 months per country/product
mdf = pd.DataFrame(monthly)
keep = []
for (c, p), g in mdf.groupby(["country", "product"]):
    ms = sorted(g["month"].unique())[-7:]
    keep.append(g[g["month"].isin(ms)])
mdf = pd.concat(keep) if keep else mdf
mdf = mdf[mdf["tons"] > 0].sort_values(["country", "product", "month", "tons"], ascending=[True, True, True, False])
mdf["id"] = [f"m{i:04d}" for i in range(len(mdf))]
dump("lineup_monthly.json", mdf.to_dict("records"))

# NABSA line-up (latest issue): scheduled loadings, Argentina
lu_p = os.path.join(LU, "nabsa_lineup.csv")
sched = []
if os.path.exists(lu_p):
    lu = pd.read_csv(lu_p)
    lu = lu[lu["issue"] == lu["issue"].max()]
    for prod, (_, cargos) in PRODUCTS.items():
        for origin, country in (("ARGENTINA", "Argentina"), ("PARAGUAY", "Paraguay")):
            g = lu[lu["cargo"].isin(cargos) & (lu["origin"] == origin)]
            for dest, gg in g.groupby("destination"):
                sched.append({"country": country, "product": prod, "destination": norm(dest), "tons": round(float(gg["tons"].sum())),
                              "vessels": int(gg["head"].nunique()), "issue": str(lu["issue"].max())})
sched = sorted(sched, key=lambda r: (r["country"], r["product"], -r["tons"]))
for i, r in enumerate(sched): r["id"] = f"s{i:03d}"
dump("lineup_scheduled.json", sched)

# Cross-checks
checks = []
refs = json.load(open(os.path.join(ROOT, "dashboard", "lineup_refs.json")))
for ref in refs:
    a, b = ref["period"].split("..")
    ms = [f"{x:%Y-%m}" for x in pd.period_range(a, b, freq="M").to_timestamp()]
    if ref["country"] == "Argentina":
        ours = sum(t for (p, m, _), t in indec.items() if p == ref["product"] and m in ms); src = "INDEC customs"
    else:
        ours = sum(r["tons"] for r in monthly if r["country"] == "Brazil" and r["month"] in ms); src = "Comex Stat customs"
    diff = (ours / 1000 - ref["value_kt"]) / ref["value_kt"] * 100
    checks.append({"id": ref["id"], "check": f"{ref['country']} {ref['product'].lower()}, {ms[0]} to {ms[-1]}", "ours": f"{ours/1000:,.0f} kt ({src})",
                   "other": f"{ref['approx']} {ref['value_kt']:,} kt ({ref['source']})", "diff_pct": round(diff, 1),
                   "status": "Agrees" if abs(diff) <= 3 else ("Close" if abs(diff) <= 7 else "Check"), "url": ref["url"]})
# NABSA vs INDEC once both cover a month
if len(sailed):
    for m in sorted(set(sailed["month"]) & set(indec_months)):
        a = float(sailed[(sailed["month"] == m) & sailed["cargo"].isin(PRODUCTS["Soybean oil"][1])]["tons"].sum())
        b = sum(t for (p, mm, _), t in indec.items() if p == "Soybean oil" and mm == m)
        if a and b:
            diff = (a - b) / b * 100
            checks.append({"id": f"nabsa-indec-{m}", "check": f"Argentina soybean oil, {m}", "ours": f"{a/1000:,.0f} kt (NABSA sailed)",
                           "other": f"{b/1000:,.0f} kt (INDEC customs)", "diff_pct": round(diff, 1),
                           "status": "Agrees" if abs(diff) <= 5 else ("Close" if abs(diff) <= 10 else "Check"), "url": "https://comex.indec.gob.ar/"})
# NABSA internal: soybean oil vessels that left the line-up should appear in the sailed list
if os.path.exists(lu_p) and len(sailed):
    lu_all = pd.read_csv(lu_p)
    issues = sorted(lu_all["issue"].dropna().unique())
    if len(issues) >= 2:
        first, last = issues[0], issues[-1]
        clean = lambda h: _re.sub(r"( (ETA|ETB|ETF|ETS|AT|REC|CZONE|BERTHED|SHIFTING|ANCHORED|\d{2}/\d{2}))+$", "", str(h))
        GENERIC = {"NORTH", "SOUTH", "BERTH", "TERMINAL", "LORENZO", "ROSARIO", "UNIT", "WHARF", "PIER", "DOCK", "I", "II", "III"}
        def keys(h):
            w = clean(h).split()
            k = {" ".join(w[-2:])}
            if w and w[-1] not in GENERIC and len(w[-1]) > 3: k.add(w[-1])
            return k
        def heads(df): return [h for h in df[df["cargo"].isin(PRODUCTS["Soybean oil"][1])]["head"].dropna()]
        later = set().union(*[keys(h) for h in heads(lu_all[lu_all["issue"] == last])]) if heads(lu_all[lu_all["issue"] == last]) else set()
        sailed_keys = set().union(*[keys(h) for h in pd.read_csv(sail_p)["head"].dropna()])
        gone = {}
        for h in heads(lu_all[lu_all["issue"] == first]):
            k = keys(h)
            if not (k & later):
                gone[sorted(k, key=lambda s: (")" not in s and "(" not in s, len(s)))[-1]] = k
        found = [n for n, k in gone.items() if k & sailed_keys]
        missing = [n for n in gone if n not in found]
        if gone:
            pct = len(found) / len(gone) * 100
            checks.append({"id": "nabsa-internal", "check": f"Soybean oil vessels that left NABSA's line-up between {first} and {last}",
                           "ours": f"{len(gone)} vessels left the line-up", "other": f"{len(found)} appear in NABSA's sailed list" + (f" (not found: {', '.join(missing)})" if missing else ""),
                           "diff_pct": round(pct - 100, 1), "status": "Agrees" if pct >= 90 else ("Close" if pct >= 75 else "Check"), "url": "https://www.nabsa.com.ar/info.html"})
dump("lineup_checks.json", checks)
print("lineups", len(mdf), len(sched), [ (c["check"], c["diff_pct"], c["status"]) for c in checks])

# ---------- this month's vegetable-oil shipments by shipper, charterer and destination (NABSA) ----------
OIL_CARGO = {"SOYBEAN OIL": "Soybean oil", "NEUTRALIZED SOYBEAN OIL": "Soybean oil", "NEUTRAL OIL": "Soybean oil", "SOYA BEAN OIL (BLEND)": "Soybean oil",
             "SOYBEANOIL REFINED": "Soybean oil", "SOYBEAN OIL REFINED": "Soybean oil", "REFINED SOYBEAN OIL": "Soybean oil",
             "SUN FLOWER OIL": "Sunflower oil", "SUNFLOWER OIL": "Sunflower oil", "HIGH OLEIC SUNFLOWER OIL": "Sunflower oil"}
MARKERS = [r"\)", r"NAVIOS SOUTH", r"NAVIOS NORTH", r"SAN MARTIN", r"SAN LORENZO", r"VICENTIN", r"MINERA ALUMBRERA", r"DEMPA", r"SAN BENITO", r"ARAUCO ARGENTINA", r"RENOVA NORTH",
           r"RENOVA SOUTH", r"TIMBUES", r"LAGOS", r"GALVEZ", r"GALVÁN", r"VGG", r"WHITE", r"BERTH \d+", r"BERTH", r"PIER \d+/\d+", r"PIER \d+",
           r"EXTERNAL PIER", r"QUEBRACHO", r"T\.B\.C\.", r"TERMINAL \d+"]
SHIPPERS = ["UNION AGRICOLA AVELLANEDA COOP.LTDA.", "MOLINOS AGRO S.A.", "GROBOCOPATEL S.A.", "COMMODITIES S.A.", "NOT AVAILABLE", "LDC PARAGUAY", "BUNGE PARAGUAY",
            "ADM PARAGUAY", "CARGILL PARAGUAY", "BUNGE", "CARGILL", "LDC", "AGD", "ACA", "COFCO", "ADM", "ARCOR", "INAGRO", "SYNGENTA", "YPF", "COPAGRA", "VITERRA",
            "MOLINOS AGRO", "OLEAGINOSA MORENO", "CHS", "AMAGGI", "NUTRIOIL", "ACABIO", "BUYATTI", "VICENTIN", "TANONI", "GLENCORE", "OLAM", "WILMAR"]
NICE = {"UNION AGRICOLA AVELLANEDA COOP.LTDA.": "Unión Agrícola Avellaneda", "MOLINOS AGRO S.A.": "Molinos Agro", "MOLINOS AGRO": "Molinos Agro",
        "GROBOCOPATEL S.A.": "Grobocopatel", "COMMODITIES S.A.": "Commodities S.A.", "NOT AVAILABLE": "Not stated", "LDC PARAGUAY": "LDC Paraguay",
        "BUNGE PARAGUAY": "Bunge Paraguay", "ADM PARAGUAY": "ADM Paraguay", "CARGILL PARAGUAY": "Cargill Paraguay", "EXXON MOBIL": "ExxonMobil",
        "BRAYA RENEWABLE FUELS": "Braya Renewable Fuels", "G2O": "G2O"}
def nice(s):
    s = str(s).strip()
    if not s or s == "nan": return "Not stated"
    if s in NICE: return NICE[s]
    if s in ("COFCO", "VITERRA_", "AMAGGI_"): return s
    return s if len(s) <= 4 and s.isupper() else title(s)
def split_vessel(head):
    h = _re.sub(r"\s+(ETA|ETB|ETS)\s+.*$", "", str(head)).strip()
    end = 0
    for mk in MARKERS:
        for m in _re.finditer(mk, h):
            if m.end() < len(h) - 1: end = max(end, m.end())
    if end:
        return h[:end].strip(), h[end:].strip(" -")
    w = h.split()
    return " ".join(w[:-2]), " ".join(w[-2:])
def split_rest(rest):
    r = str(rest).strip()
    for s in sorted(SHIPPERS, key=len, reverse=True):
        if r == s or r.startswith(s + " "):
            return nice(s), nice(r[len(s):].strip())
    w = r.split()
    return (nice(w[0]) if w else "Not stated"), nice(" ".join(w[1:]))
oil_rows = []
if len(sailed_all):
    cur = max(sailed_all["month"])
    so = sailed_all[(sailed_all["month"] == cur) & sailed_all["cargo"].isin(OIL_CARGO)]
    for r in so.itertuples():
        berth, vessel = split_vessel(r.head)
        shp, chart = split_rest(r.rest)
        oil_rows.append({"month": cur, "status": "Sailed", "date": r.date, "vessel": title(vessel), "berth": title(berth), "product": OIL_CARGO[r.cargo],
                         "cargo": title(r.cargo), "origin": title(r.origin), "destination": norm(r.destination), "shipper": shp, "charterer": chart,
                         "tons": round(float(r.tons)), "source": f"NABSA sailed vessels, issue of {r.issue}"})
    if os.path.exists(lu_p):
        lu_all = pd.read_csv(lu_p)
        lu_last = lu_all[(lu_all["issue"] == lu_all["issue"].max()) & lu_all["cargo"].isin(OIL_CARGO)].copy()
        y, mo = map(int, cur.split("-"))
        def eta_date(e):
            try:
                d_, m_ = map(int, str(e).split("/")[:2]); return dt.date(y if m_ >= mo or mo < 11 else y + 1, m_, d_)
            except Exception:
                return None
        import datetime as dt
        seen = set()
        for r in lu_last.itertuples():
            berth, vessel = split_vessel(r.head)
            ed = eta_date(r.eta)
            if ed is not None and f"{ed:%Y-%m}" > cur: continue   # arriving after this month
            k = (vessel, r.cargo, r.tons, r.destination)
            if k in seen: continue
            seen.add(k)
            oil_rows.append({"month": cur, "status": "Line-up", "date": f"{ed:%Y-%m-%d}" if ed else None, "vessel": title(vessel), "berth": title(berth),
                             "product": OIL_CARGO[r.cargo], "cargo": title(r.cargo), "origin": title(r.origin), "destination": norm(r.destination),
                             "shipper": "Not in line-up data", "charterer": nice(r.charterer), "tons": round(float(r.tons)),
                             "source": f"NABSA line-up of {r.issue}"})
oil_rows = sorted(oil_rows, key=lambda r: (r["status"] != "Sailed", str(r["date"]), r["vessel"]))
for i, r in enumerate(oil_rows): r["id"] = f"o{i:03d}"
dump("oil_month.json", oil_rows)
print("oil_month", len(oil_rows), sum(r["tons"] for r in oil_rows if r["status"] == "Sailed"), sum(r["tons"] for r in oil_rows if r["status"] == "Line-up"))

# ---------- China UCO to the EU: EU imports from China of CN 1518 00 (Eurostat Comext mirror data) ----------
EU_NAMES = {"EU27_2020": "EU-27", "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "CY": "Cyprus", "CZ": "Czechia", "DE": "Germany", "DK": "Denmark",
            "EE": "Estonia", "ES": "Spain", "FI": "Finland", "FR": "France", "GR": "Greece", "HR": "Croatia", "HU": "Hungary", "IE": "Ireland", "IT": "Italy",
            "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia", "MT": "Malta", "NL": "Netherlands", "PL": "Poland", "PT": "Portugal", "RO": "Romania",
            "SE": "Sweden", "SI": "Slovenia", "SK": "Slovakia"}
uco_p = os.path.join(D, "uco", "eurostat_eu_imports_from_china_1518.json")
uco_rows = []
if os.path.exists(uco_p):
    body = json.load(open(uco_p)).get("151800", {}).get("body", {})
    if isinstance(body, dict) and "value" in body:
        ids, size = body["id"], body["size"]
        idx = {dn: {i: c for c, i in body["dimension"][dn]["category"]["index"].items()} for dn in ids}
        for flat, val in body["value"].items():
            f, coords = int(flat), []
            for s_ in reversed(size):
                coords.append(f % s_); f //= s_
            rec = {dn: idx[dn][c] for dn, c in zip(ids, reversed(coords))}
            if rec["reporter"] in EU_NAMES and val:
                uco_rows.append({"month": rec["time"], "country_code": rec["reporter"], "country": EU_NAMES[rec["reporter"]], "tons": round(val / 10)})
uco_rows = sorted(uco_rows, key=lambda r: (r["month"], r["country_code"]))
for i, r in enumerate(uco_rows): r["id"] = f"u{i:04d}"
dump("uco_eu.json", uco_rows)
print("uco_eu", len(uco_rows), max((r["month"] for r in uco_rows), default=None))

# ---------- UCO into the US: US imports of HS 1518 00 by origin (UN Comtrade, reported by the US) ----------
try:
    import pycountry
except Exception:
    pycountry = None
CT_OVERRIDE = {0: "World", 156: "China", 124: "Canada", 458: "Malaysia", 36: "Australia", 410: "South Korea", 360: "Indonesia", 826: "UK", 554: "New Zealand",
               704: "Vietnam", 170: "Colombia", 56: "Belgium", 276: "Germany", 251: "France", 699: "India", 490: "Taiwan", 757: "Switzerland", 484: "Mexico",
               764: "Thailand", 608: "Philippines", 702: "Singapore", 392: "Japan", 528: "Netherlands", 724: "Spain", 76: "Brazil", 32: "Argentina", 152: "Chile",
               604: "Peru", 344: "Hong Kong", 842: "USA", 380: "Italy", 784: "UAE", 682: "Saudi Arabia", 818: "Egypt", 792: "Turkey", 50: "Bangladesh", 586: "Pakistan"}
def ct_name(code):
    if code in CT_OVERRIDE: return CT_OVERRIDE[code]
    if pycountry:
        c = pycountry.countries.get(numeric=f"{int(code):03d}")
        if c: return getattr(c, "common_name", None) or c.name
    return f"Code {code}"
us_p = os.path.join(D, "uco", "comtrade_us_imports_151800.json")
us_rows = []
if os.path.exists(us_p):
    agg = collections.defaultdict(float)
    for r in json.load(open(us_p)).get("rows", []):
        if r["partner_code"] in (0, None) or not r.get("net_kg"): continue
        agg[(f"{r['period'][:4]}-{r['period'][4:6]}", ct_name(r["partner_code"]))] += float(r["net_kg"]) / 1000
    tot = collections.defaultdict(float)
    for (m, c), t in agg.items():
        us_rows.append({"month": m, "country": c, "tons": round(t)}); tot[m] += t
    us_rows += [{"month": m, "country": "Total", "tons": round(t)} for m, t in tot.items()]
us_rows = sorted(us_rows, key=lambda r: (r["month"], r["country"]))
for i, r in enumerate(us_rows): r["id"] = f"us{i:04d}"
dump("uco_us.json", us_rows)
print("uco_us", len(us_rows), max((r["month"] for r in us_rows), default=None))
