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
# Headline = CFTC disaggregated managed money, FUTURES AND OPTIONS COMBINED (the figure most market commentary quotes);
# futures-only kept alongside. Daily estimate since the report: fitted contracts per 1% move of the 2nd-month contract
# (2 years of weekly changes), applied to the 2nd-month price change since the report Tuesday; +/- one weekly residual s.d.
c_fo = pd.read_csv(os.path.join(D, "cot_agri_fo.csv"), dtype={"code": str}); c_fo["date"] = pd.to_datetime(c_fo["date"])
c_fu = pd.read_csv(os.path.join(D, "cot_agri.csv"), dtype={"code": str}); c_fu["date"] = pd.to_datetime(c_fu["date"])
c = c_fo.copy(); c["code"] = c["code"].str.lstrip("0"); c["net"] = c["mm_long"] - c["mm_short"]   # all-ag section uses the same combined report
EST = {"007601": ("soybean_oil", "Soybean oil", "ZL_2.csv", "ZL_F.csv"), "005602": ("soybeans", "Soybeans", None, "ZS_F.csv"),
       "026603": ("soybean_meal", "Soybean meal", "ZM_2.csv", "ZM_F.csv"), "002602": ("corn", "Corn", None, "ZC_F.csv")}
rows, fstats, est_delta = [], [], {}
for code, (k, lab, f2, f1) in EST.items():
    px = None
    for f in (f2, f1):
        if f and os.path.exists(os.path.join(D, "daily", f)):
            px = load(f); px = px[px.index.dayofweek < 5]; break
    x = c_fo[c_fo.code.str.lstrip("0") == code.lstrip("0")].sort_values("date").set_index("date")
    xf = c_fu[c_fu.code.str.lstrip("0") == code.lstrip("0")].sort_values("date").set_index("date")
    net = (x["mm_long"] - x["mm_short"]); net = net[net.index >= net.index.max() - pd.Timedelta(days=730)]
    p = px.reindex(px.index.union(net.index)).ffill().reindex(net.index)
    dn, dp = net.diff(), np.log(p).diff() * 100; ok = dn.notna() & dp.notna() & (dp.abs() < 15)
    beta = float(np.linalg.lstsq(np.c_[dp[ok]], dn[ok], rcond=None)[0][0])
    resid = dn[ok] - beta * dp[ok]; sd = float(resid.std()); r2 = float(1 - resid.var() / dn[ok].var())
    ld, ln = net.index[-1], int(net.iloc[-1]); p0 = float(p.iloc[-1])
    for d, v in net.items(): rows.append({"id": f"{k}-{d:%Y%m%d}-o", "market": k, "date": f"{d:%Y-%m-%d}", "net": int(v), "kind": "official"})
    rows.append({"id": f"{k}-{ld:%Y%m%d}-e", "market": k, "date": f"{ld:%Y-%m-%d}", "net": ln, "kind": "estimate"})
    est = ln; series = {}
    for d, v in px[px.index > ld].items():
        est = int(round(ln + beta * np.log(v / p0) * 100)); series[d] = est - ln
        rows.append({"id": f"{k}-{d:%Y%m%d}-e", "market": k, "date": f"{d:%Y-%m-%d}", "net": est, "kind": "estimate"})
    est_delta[code.lstrip("0")] = (series, px)
    oi = float(x["open_interest"].iloc[-1]); fut_net = int((xf["mm_long"] - xf["mm_short"]).iloc[-1]) if len(xf) else None
    fstats.append({"market": k, "label": lab, "official_date": f"{ld:%Y-%m-%d}", "official_net": ln, "week_change": int(net.iloc[-1] - net.iloc[-2]),
                   "futures_only_net": fut_net, "report": "Futures and options combined",
                   "est_date": f"{(px.index[-1] if len(series) else ld):%Y-%m-%d}", "est_net": est, "est_change": est - ln,
                   "est_low": int(round(est - sd)), "est_high": int(round(est + sd)), "per_1pct": int(round(beta)),
                   "pct_oi": round(ln / oi * 100, 1), "r2": round(r2, 2), "est_contract": (f2 or f1).split(".")[0].replace("_2", " 2nd month").replace("_F", " front"),
                   "pct_2y": int(round((net < ln).mean() * 100))})
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
# daily estimate since the report for every CFTC market with a daily price: soy complex and corn from the fund model above,
# the rest from their own fitted contracts-per-1% move (2 years of weekly changes). MATIF and canola stay at the official figure.
for code, (lab, grp, s_, mult, note) in AG.items():
    if code in est_delta or s_ is None or not len(s_): continue
    sp = s_[s_.index.dayofweek < 5]
    x = c[c.code == code].set_index("date")["net"].sort_index(); x = x[x.index >= x.index.max() - pd.Timedelta(days=730)]
    if len(x) < 30: continue
    p_ = sp.reindex(sp.index.union(x.index)).ffill().reindex(x.index)
    dn_, dp_ = x.diff(), np.log(p_).diff() * 100; ok_ = dn_.notna() & dp_.notna() & (dp_.abs() < 15)
    if ok_.sum() < 20: continue
    b_ = float(np.linalg.lstsq(np.c_[dp_[ok_]], dn_[ok_], rcond=None)[0][0])
    p0_ = float(p_.iloc[-1]); ser_ = {}
    for d, v in sp[sp.index > x.index[-1]].items(): ser_[d] = b_ * np.log(v / p0_) * 100
    est_delta[code] = (ser_, sp)
est_days = sorted(set().union(*[set(v[0].keys()) for v in est_delta.values()]))
est_rows = []
for d in est_days:
    add = 0.0
    for code, (ser_, pe) in est_delta.items():
        if code not in AG: continue
        lab, grp, s_, mult, note = AG[code]
        hit = R[(R.m == code) & (R.date == last_d)]
        if not len(hit): continue
        base = float(hit["net"].iloc[0]); prior = [v for k_, v in ser_.items() if k_ <= d]
        delta = prior[-1] if prior else 0.0
        add += (base + delta) * mult * pxat(s_, d) - base * mult * pxat(s_, last_d)
    est_rows.append((d, float(tot.loc[last_d]) + add))
est_net_now = {code: (v[0][max(v[0])] if v[0] else 0.0) for code, v in est_delta.items()}
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
               "vs_avg_usd_bn": round((r.usd - float(hist.mean())) / 1e9, 2), "pct_2y": int(round((hist < r.usd).mean() * 100)), "note": r.note,
               "est_net": int(round(r.net + est_net_now[r.m])) if r.m in est_net_now else None})
est_now = est_rows[-1][1] if est_rows else float(tot.loc[last_d])
mk.append({"market": "total", "label": f"All {len(L)} agricultural markets", "group": "Total", "net": None, "week_change": None, "est_net": None,
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
# Brazil: Paranaguá and Santos port line-ups (vessel, agent, terminal, tonnes; no shipper or destination in port data)
BR_OIL = {"OLEO DE SOJA": "Soybean oil", "OLEO VEGETAL": "Soybean oil", "OLEO DE GIRASSOL": "Sunflower oil"}
def br_date(x):
    m_ = _re.match(r"(\d{2})/(\d{2})/(\d{4})", str(x or ""))
    return f"{m_.group(3)}-{m_.group(2)}-{m_.group(1)}" if m_ else None
br_sched = collections.defaultdict(lambda: [0.0, set()])
br_cur = max(sailed_all["month"]) if len(sailed_all) else f"{pd.Timestamp.utcnow():%Y-%m}"
br_ports = []
for port in ("paranagua", "santos"):
    pdir = os.path.join(LU, port)
    if not os.path.exists(os.path.join(pdir, "vessels.json")): continue
    hist = json.load(open(os.path.join(pdir, "vessels.json")))
    latest_fetch = json.load(open(os.path.join(pdir, "latest.json")))["fetched_utc"]
    pname = {"paranagua": "Paranaguá", "santos": "Santos"}[port]
    br_ports.append(f"{pname} port line-up, {latest_fetch[:16]} UTC")
    for k, v in hist.items():
        prod = next((p for c, p in BR_OIL.items() if c in str(v.get("product", "")).upper()), None)
        if not prod or str(v.get("direction", "Exp")).upper() not in ("EXP", "EMB", "IMP/EXP"): continue
        agent = title(v.get("agency") or "Not stated")
        base = {"month": br_cur, "vessel": title(v.get("vessel")), "berth": pname + " – " + title(v.get("terminal") or ""), "product": prod,
                "cargo": title(v.get("product")), "origin": "Brazil", "destination": "Not in port data", "shipper": "Not in port data",
                "charterer": "Agent: " + agent, "tons": round(float(v.get("tons") or 0))}
        sailed_d = br_date(v.get("sailed")) if v.get("section", "").startswith("DESPACHADO") else None
        if sailed_d:
            if sailed_d[:7] == br_cur:
                oil_rows.append({**base, "status": "Sailed", "date": sailed_d, "source": f"{pname} port line-up (departures)"})
        elif v.get("last_seen") == latest_fetch:
            eta = None if v.get("section") in ("ATRACADOS", "AO LARGO", "AO LARGO PARA REATRACAÇÃO") else (br_date(v.get("etb")) or br_date(v.get("eta")) or br_date(v.get("arrival")))
            br_sched[prod][0] += base["tons"]; br_sched[prod][1].add(base["vessel"])
            if eta is None or eta[:7] <= br_cur:
                oil_rows.append({**base, "status": "Line-up", "date": eta, "source": f"{pname} port line-up"})
for prod, (t, vs) in br_sched.items():
    sched.append({"country": "Brazil", "product": prod, "destination": "Not in port data", "tons": round(t), "vessels": len(vs),
                  "issue": max(br_ports)[-20:-4] if br_ports else ""})
for i, r in enumerate(sched): r["id"] = f"s{i:03d}"
dump("lineup_scheduled.json", sched)
# Brazil soybean oil exports by port, official customs (Comex Stat), monthly
bp = os.path.join(LU, "comexstat_soyoil_ports.json")
if os.path.exists(bp):
    bl = json.load(open(bp))["data"]["list"]
    bdf = pd.DataFrame([{"month": f"{r['year']}-{r['monthNumber']}", "port": str(r.get("urf") or r.get("noUrf") or "").split(" - ", 1)[-1].title()
                         .replace("Porto De ", "").replace("Sao ", "São ").replace("Paranagua", "Paranaguá"), "tons": float(r["metricKG"]) / 1000} for r in bl])
    piv = bdf.groupby(["port", "month"])["tons"].sum().unstack(fill_value=0)
    months = sorted(piv.columns); last_m = months[-1]; prev_m = months[-2]
    y, mth = int(last_m[:4]), int(last_m[5:])
    ytd = [m for m in months if m.startswith(str(y)) and int(m[5:]) <= mth]; ytd_p = [f"{y-1}-{m[5:]}" for m in ytd if f"{y-1}-{m[5:]}" in months]
    six = months[-6:]
    tot_last = float(piv[last_m].sum())
    rows_bp = []
    for port in piv.index:
        a, b = float(piv.loc[port, ytd].sum()), float(piv.loc[port, ytd_p].sum()) if ytd_p else 0.0
        if a + b < 1000: continue
        rows_bp.append({"id": "p-" + _re.sub(r"[^a-z]", "", port.lower())[:20], "port": port, "last_month": round(float(piv.loc[port, last_m])),
                        "prev_month": round(float(piv.loc[port, prev_m])), "avg_6m": round(float(piv.loc[port, six].mean())),
                        "share_last": round(float(piv.loc[port, last_m]) / tot_last * 100, 1) if tot_last else None,
                        "ytd": round(a), "ytd_prev": round(b), "ytd_change_pct": round((a / b - 1) * 100, 1) if b > 1000 else None,
                        "month": last_m, "prev": prev_m, "ytd_label": f"Jan-{pd.Timestamp(last_m + '-01'):%b} {y}"})
    rows_bp.sort(key=lambda r: -r["ytd"])
    big = [r for r in rows_bp if r["ytd"] >= 10000]; small = [r for r in rows_bp if r["ytd"] < 10000]
    T = lambda k, rs=rows_bp: round(sum(r[k] for r in rs))
    if small:
        a0, b0 = T("ytd", small), T("ytd_prev", small)
        big.append({"id": "other", "port": "Other ports and land borders", "last_month": T("last_month", small), "prev_month": T("prev_month", small),
                    "avg_6m": T("avg_6m", small), "share_last": round(T("last_month", small) / tot_last * 100, 1) if tot_last else None,
                    "ytd": a0, "ytd_prev": b0, "ytd_change_pct": round((a0 / b0 - 1) * 100, 1) if b0 > 1000 else None,
                    "month": last_m, "prev": prev_m, "ytd_label": big[0]["ytd_label"] if big else ""})
    a, b = T("ytd"), T("ytd_prev")
    rows_bp_total = ({"id": "total", "port": "Brazil, all ports", "last_month": T("last_month"), "prev_month": T("prev_month"), "avg_6m": T("avg_6m"),
                    "share_last": 100.0, "ytd": a, "ytd_prev": b, "ytd_change_pct": round((a / b - 1) * 100, 1) if b else None,
                    "month": last_m, "prev": prev_m, "ytd_label": f"Jan-{pd.Timestamp(last_m + '-01'):%b} {y}"})
    rows_bp = big + [rows_bp_total]
    dump("br_ports.json", rows_bp)
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

# ---------- correlations: six cross-market pairs, last 6 months of daily closes ----------
def daily_close(name):
    p = os.path.join(D, "daily", name + ".csv")
    if not os.path.exists(p): return None
    d = pd.read_csv(p)
    s = pd.Series(pd.to_numeric(d["close"], errors="coerce").values, index=pd.to_datetime(d["time_utc"].str.slice(0, 10))).dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s[s > 0]
def usd(series, fx, divide=True):
    if series is None or fx is None: return None
    f = fx.reindex(series.index, method="ffill")
    return (series / f if divide else series * f).dropna()
def first(*names):
    for n in names:
        s_ = daily_close(n)
        if s_ is not None and len(s_) > 30: return s_[s_.index.dayofweek < 5]
    return None
def matif_mask(idx):
    """MATIF rapeseed expires on the last business day of Jan, Apr, Jul and Oct. Flag the last 10 sessions before
    each expiry and the 2 after it, so delivery squeezes and the roll don't enter the numbers."""
    out = pd.Series(False, index=idx)
    for y in sorted(set(idx.year) | {idx.year.max() + 1}):
        for m in (1, 4, 7, 10):
            exp = pd.offsets.BMonthEnd().rollforward(pd.Timestamp(y, m, 1))
            before, after = idx[idx <= exp][-10:], idx[idx > exp][:2]
            out[before] = True; out[after] = True
    return out
RS_FRONT = first("MATIF_RS")
RS_MASK = matif_mask(RS_FRONT.index) if RS_FRONT is not None else None
def rs_chain():
    """Front-month rapeseed outside the expiry weeks; inside them, carry the series forward with the daily % change of the
    second listed contract from Euronext's settlement table (collected daily since 22 Oct 2026)."""
    if RS_FRONT is None: return None
    s_ = RS_FRONT[~RS_MASK]
    p = os.path.join(D, "euronext_prices.csv")
    if not os.path.exists(p) or not len(s_): return s_
    e = pd.read_csv(p); e = e[e["product"] == "ECO"].copy()
    e["d"] = pd.to_datetime(e["price_date"], format="%d %b %Y", errors="coerce"); e["m"] = pd.to_datetime(e["delivery"], format="%b %Y", errors="coerce")
    e = e.dropna(subset=["d", "m", "settle"])
    e = e[e["m"] >= e["d"].dt.to_period("M").dt.to_timestamp()]
    f2 = e.sort_values("m").groupby("d").nth(1).set_index("d")
    f2 = f2[["settle", "delivery"]].sort_index()
    ext = {}
    last_d, last_v = s_.index[-1], float(s_.iloc[-1])
    prev = None
    for d_, row in f2[f2.index > last_d].iterrows():
        if d_ in RS_MASK.index and not RS_MASK[d_] and d_ in RS_FRONT.index: break
        if prev is not None and prev[1] == row["delivery"]:
            last_v = last_v * row["settle"] / prev[0]; ext[d_] = last_v
        prev = (row["settle"], row["delivery"])
    return pd.concat([s_, pd.Series(ext, dtype=float)]).sort_index() if ext else s_
RS_SER = rs_chain()
SER = {
    "gasoil": ("ICE gasoil (2nd month)", "USD/t", first("ICE_GO_2", "ICE_GO")),
    "palm": ("Bursa palm, 3rd month", "MYR/t", first("FCPO")),
    "brent": ("Brent (2nd month)", "USD/bbl", first("BZ_2", "BZ_F")),
    "meal": ("CBOT soymeal (2nd month)", "USD/st", first("ZM_2", "ZM_F")),
    "soyoil": ("CBOT soyoil (2nd month)", "c/lb", first("ZL_2", "ZL_F")),
    "rapeseed": ("MATIF rapeseed (nearest, expiry weeks left out)", "EUR/t", RS_SER),
    "heatoil": ("NYMEX heating oil (2nd month)", "USD/gal", first("HO_2", "HO_F")),
}
PAIRS = [("gasoil", "palm"), ("gasoil", "brent"), ("meal", "soyoil"), ("rapeseed", "gasoil"), ("soyoil", "heatoil"), ("heatoil", "brent")]
corr_rows, corr_stats = [], []
end = max((v[2].index.max() for v in SER.values() if v[2] is not None and len(v[2])), default=None)
for a, b in PAIRS:
    sa, sb = SER[a][2], SER[b][2]
    pid = f"{a}-{b}"
    if sa is None or sb is None or not len(sa) or not len(sb):
        corr_stats.append({"pair": pid, "a": SER[a][0], "b": SER[b][0], "note": "data missing"}); continue
    df = pd.concat([sa.rename("a"), sb.rename("b")], axis=1).dropna()
    df = df[df.index >= end - pd.Timedelta(days=183)]
    if len(df) < 30:
        corr_stats.append({"pair": pid, "a": SER[a][0], "b": SER[b][0], "note": "too little data"}); continue
    r = np.log(df).diff().dropna()
    if "rapeseed" in (a, b):
        gap = df.index.to_series().diff() > pd.Timedelta(days=5)
        r = r[~gap.reindex(r.index, fill_value=False)]
    # front-month series jump when the contract rolls: drop days with a move over 4 standard deviations in either series
    jumps = (r["a"].abs() > 4 * r["a"].std()) | (r["b"].abs() > 4 * r["b"].std())
    # gasoil: a roll shows up as a gasoil move that heating oil (same product, New York) doesn't share
    for side, key in (("a", a), ("b", b)):
        if key == "gasoil" and SER["heatoil"][2] is not None:
            ho = np.log(SER["heatoil"][2]).diff().reindex(r.index)
            gap = (r[side] - ho).dropna()
            jumps = jumps | ((r[side] - ho).abs() > 2.5 * gap.std()).reindex(r.index, fill_value=False)
    r = r[~jumps]
    roll = r["a"].rolling(30, min_periods=25).corr(r["b"])
    # rebase raw prices to the median of the first 5 sessions, so a one-day squeeze at the start (e.g. MATIF expiry) doesn't set the base
    start = end - pd.Timedelta(days=183)
    base = pd.Series({"a": float(sa[sa.index >= start].head(5).median()), "b": float(sb[sb.index >= start].head(5).median())})
    idx = df / base * 100
    for d_, row in df.iterrows():
        corr_rows.append({"pair": pid, "date": f"{d_:%Y-%m-%d}", "a": round(float(row.a), 4), "b": round(float(row.b), 4),
                          "a_idx": round(float(idx.loc[d_, "a"]), 2), "b_idx": round(float(idx.loc[d_, "b"]), 2),
                          "corr30": None if pd.isna(roll.get(d_)) else round(float(roll.get(d_)), 3)})
    beta = float(np.cov(r["b"], r["a"])[0, 1] / np.var(r["a"])) if np.var(r["a"]) else None
    last21 = r.tail(21)
    corr_stats.append({"pair": pid, "a": SER[a][0], "a_unit": SER[a][1], "b": SER[b][0], "b_unit": SER[b][1],
                       "start": f"{df.index[0]:%Y-%m-%d}", "end": f"{df.index[-1]:%Y-%m-%d}", "days": int(len(df)),
                       "corr_returns_6m": round(float(r["a"].corr(r["b"])), 3), "corr_returns_1m": round(float(last21["a"].corr(last21["b"])), 3),
                       "corr_levels_6m": round(float(df["a"].corr(df["b"])), 3), "corr30_now": None if pd.isna(roll.iloc[-1]) else round(float(roll.iloc[-1]), 3),
                       "corr30_min": round(float(roll.min()), 3), "corr30_max": round(float(roll.max()), 3),
                       "beta_b_on_a": None if beta is None else round(beta, 3),
                       "roll_days_dropped": int(jumps.sum()),
                       "a_change_pct": round(float((sa.iloc[-1] / base["a"] - 1) * 100), 1), "b_change_pct": round(float((sb.iloc[-1] / base["b"] - 1) * 100), 1),
                       "a_start": round(float(base["a"]), 2), "b_start": round(float(base["b"]), 2), "a_last": round(float(sa.iloc[-1]), 2), "b_last": round(float(sb.iloc[-1]), 2),
                       "a_last_date": f"{sa.index[-1]:%Y-%m-%d}", "b_last_date": f"{sb.index[-1]:%Y-%m-%d}",
                       "note": ""})
for i, r_ in enumerate(corr_rows): r_["id"] = f"c{i:05d}"
dump("corr_series.json", corr_rows)
dump("corr_stats.json", corr_stats)
print("correlations", [(s_["pair"], s_.get("corr_returns_6m"), s_.get("corr30_now"), s_.get("note")) for s_ in corr_stats])

# ---------- D4 RIN generation vs the pace the RFS needs (EPA EMTS) ----------
# EMTS generationbreakout files are year-to-date per RIN year; monthly = difference between consecutive months.
# D4 needed = advanced standard incl. SRE reallocation - cellulosic - ~0.28bn D5 (what is left for biomass-based diesel).
# Sources: EPA Set 2 final rule (Apr 2026) fact sheet; EPA SRE supplemental proposal (16 Oct 2026, 770M extra RINs).
D5_BN = 0.28
RFS = {  # year: {scenario: (advanced incl. reallocation, cellulosic)}, billion RINs
    2025: {"final": (7.33 - 0.17, 1.21)},  # Set 1 advanced 7.33, cellulosic waived 1.38 -> 1.21 (advanced cut by the same)
    2026: {"current": (11.10, 1.36), "fifty": (11.22, 1.36), "all2027": (11.10, 1.36)},
    2027: {"current": (11.32, 1.43), "fifty": (11.45, 1.43), "all2027": (11.57, 1.43)},
}
SCN = {"final": "Final rule", "current": "Current rule (no extra reallocation)", "fifty": "Proposal: 50/50 to 2026 and 2027", "all2027": "Proposal: all to 2027"}
emts_p = os.path.join(D, "rins", "emts_generation.csv")
if os.path.exists(emts_p):
    em = pd.read_csv(emts_p)
    em = em[em["Fuel Code"].astype(str) == "4"].copy()
    mm = em["file"].str.extract(r"_([a-z]{3})(\d{4})\.csv$")
    em["fm"] = pd.to_datetime("1 " + mm[0] + " " + mm[1], format="%d %b %Y", errors="coerce")
    em = em.dropna(subset=["fm"])
    em = em[em["RIN_YEAR"] == em["fm"].dt.year]
    em = em.sort_values("fm").drop_duplicates("fm", keep="last").set_index("fm")
    tot = em["Total RINs"].astype(float)
    imp = (em["IMPORTER"].astype(float) + em["Foreign Generation"].astype(float))
    prev_t = tot.shift(1).where(tot.index.month != 1, 0.0)
    prev_i = imp.shift(1).where(imp.index.month != 1, 0.0)
    gap_ok = (tot.index.to_series().diff().dt.days.fillna(31) < 40) | (tot.index.month == 1)
    mon = ((tot - prev_t) / 1e6).where(gap_ok)
    imon = ((imp - prev_i) / 1e6).where(gap_ok)
    det_p = os.path.join(D, "rins", "epa_generation_detail.csv")
    if os.path.exists(det_p):  # RINs by the month they were generated (EPA dashboard); better than year-to-date differences
        dt_ = pd.read_csv(det_p); dt_ = dt_[dt_["d_code"] == "D4"]
        dt_["fm"] = pd.to_datetime(dict(year=dt_["rin_year"], month=dt_["month"], day=1))
        gm = dt_.groupby("fm")["rins"].sum() / 1e6
        gi = dt_[dt_["producer_type"] != "Domestic"].groupby("fm")["rins"].sum().reindex(gm.index, fill_value=0) / 1e6
        for k_, v_ in gm.items():
            if k_ in mon.index: mon[k_] = v_; imon[k_] = gi[k_]
    need = {y: {k: a - c - D5_BN for k, (a, c) in v.items()} for y, v in RFS.items()}
    rows_d4 = []
    for fm_, v in mon.items():
        if fm_.year < 2025: continue
        y = fm_.year; nd = need.get(y, {})
        rows_d4.append({"id": f"m-{fm_:%Y-%m}", "kind": "month", "month": f"{fm_:%Y-%m}",
                        "actual_mn": None if pd.isna(v) else round(float(v), 1),
                        "ytd_bn": round(float(tot[fm_]) / 1e9, 3),
                        "import_share_pct": None if pd.isna(v) or not v else round(float(imon[fm_] / v * 100), 1),
                        "req_current_mn": round(nd.get("current", nd.get("final", float("nan"))) * 1000 / 12, 1) if nd else None,
                        "req_fifty_mn": round(nd.get("fifty", nd.get("final", float("nan"))) * 1000 / 12, 1) if nd else None,
                        "req_all2027_mn": round(nd.get("all2027", nd.get("final", float("nan"))) * 1000 / 12, 1) if nd else None})
    last_m = mon.dropna().index.max()
    pace3 = float(mon.dropna().iloc[-3:].mean())  # million RINs a month, last 3 reported months
    for y in sorted(RFS):
        gen = float(tot[tot.index.year == y].iloc[-1]) / 1e9 if (tot.index.year == y).any() else 0.0
        done_m = int(tot[tot.index.year == y].index.max().month) if (tot.index.year == y).any() else 0
        left = 12 - done_m
        proj = gen + pace3 * left / 1000
        for k, nb in need[y].items():
            rows_d4.append({"id": f"y-{y}-{k}", "kind": "year", "year": y, "scenario": SCN[k], "scenario_key": k,
                            "need_bn": round(nb, 2), "need_mn_month": round(nb * 1000 / 12, 0),
                            "generated_bn": round(gen, 3), "months_reported": done_m,
                            "still_needed_mn_month": round((nb - gen) * 1000 / left, 0) if left else None,
                            "pace3m_mn": round(pace3, 0) if left else None,
                            "yearend_at_pace_bn": round(proj, 2),
                            "surplus_bn": round(proj - nb, 2),
                            "last_month": f"{last_m:%Y-%m}", "status": "Final" if left == 0 else ("Projected" if done_m == 0 else "Partial")})
    dump("d4_pace.json", rows_d4)
    print("d4", last_m, round(pace3, 1), [(r_["id"], r_.get("surplus_bn")) for r_ in rows_d4 if r_["kind"] == "year"])


# ---------- RIN generation by D code, fuel and producer type (EPA EMTS dashboard) ----------
det_p = os.path.join(D, "rins", "epa_generation_detail.csv")
if os.path.exists(det_p):
    g = pd.read_csv(det_p)
    g["fuel"] = g["fuel_category"].str.replace(r"\s*\(EV [0-9.]+\)", "", regex=True).str.replace("Non-ester Renewable Diesel", "Renewable diesel") \
        .str.replace("Renewable Jet Fuel", "Renewable jet fuel (SAF)").str.replace("Non-cellulosic Ethanol", "Ethanol").str.replace("Cellulosic Ethanol", "Cellulosic ethanol") \
        .str.replace("Renewable Natural Gas - RNG", "Renewable natural gas").str.replace("Renewable Compressed Natural Gas - CNG", "Renewable CNG") \
        .str.replace("Renewable Liquefied Natural Gas - LNG", "Renewable LNG").str.replace("Renewable Heating Oil", "Renewable heating oil").str.replace("Renewable Naphtha", "Renewable naphtha")
    g["fuel"] = g["fuel"].replace({"Renewable Compressed Natural Gas": "Renewable CNG", "Renewable Liquefied Natural Gas": "Renewable LNG",
        "Cellulosic Heating Oil (EV application required)": "Cellulosic heating oil", "Cellulosic Diesel (EV application required)": "Cellulosic diesel",
        "Renewable Gasoline": "Renewable gasoline"})
    g["origin"] = g["producer_type"].map({"Domestic": "Domestic"}).fillna("Imported")
    g["m"] = g["rin_year"].astype(int).astype(str) + "-" + g["month"].astype(int).map("{:02d}".format)
    a = g.groupby(["m", "d_code", "fuel", "origin"], as_index=False)[["rins", "gallons"]].sum()
    a = a[a["m"] >= "2016-01"]
    rows_rf = [{"id": f"{r.m}|{r.d_code}|{r.fuel}|{r.origin}", "month": r.m, "d_code": r.d_code, "fuel": r.fuel, "origin": r.origin,
                "rins_mn": round(r.rins / 1e6, 2), "gal_mn": round(r.gallons / 1e6, 2)} for r in a.itertuples()]
    dump("rin_fuel.json", rows_rf)
    lm = a["m"].max(); print("rin_fuel", len(rows_rf), lm)

# ---------- Argentine oil exports 2026 by product: customs (INDEC) and NABSA sailed, for checking line-up records ----------
OILG = {"sbo": ("Soybean oil (crude)", ("15071000",), ("SOYBEAN OIL",)),
        "nsbo": ("Neutralised soybean oil", ("15079090",), ("NEUTRALIZED SOYBEAN OIL", "NEUTRAL OIL")),
        "sfo": ("Sunflower oil (crude)", ("15121110", "15121120"), ("SUN FLOWER OIL", "SUNFLOWER OIL", "HIGH OLEIC SUNFLOWER OIL")),
        "bio": ("Biodiesel", ("38260000",), ("BIODIESEL",))}
ind_t, ind_s = collections.defaultdict(float), collections.defaultdict(int)
for y in (2026, 2027):
    p = os.path.join(LU, f"indec_exports_{y}.json")
    if not os.path.exists(p): continue
    for r in json.load(open(p))["rows"]:
        if not r["_file"].startswith("exponm"): continue
        for k, (_, ncms, _) in OILG.items():
            if r["NCM"] in ncms:
                key = (k, f"{r['Año']}-{r['Mes']}")
                if r["Pnet(kg)"] in ("s", ""): ind_s[key] += 1
                else: ind_t[key] += float(r["Pnet(kg)"].replace(",", ".")) / 1000
nab_t, nab_basis = collections.defaultdict(float), {}
if len(sailed):
    last_sail = pd.to_datetime(sailed["date"]).max()
    for k, (_, _, cargos) in OILG.items():
        for m, t in sailed[sailed["cargo"].isin(cargos)].groupby("month")["tons"].sum().items():
            nab_t[(k, m)] = float(t)
            nab_basis[(k, m)] = "whole month" if m < f"{last_sail:%Y-%m}" else f"to {last_sail:%-d %b}"
rows_ao = []
for k, (lab, _, _) in OILG.items():
    for mo in range(1, 13):
        m = f"2026-{mo:02d}"
        if (k, m) not in ind_t and (k, m) not in ind_s and (k, m) not in nab_t: continue
        rows_ao.append({"id": f"{k}-{m}", "product_key": k, "product": lab, "month": m,
                        "indec_t": round(ind_t[(k, m)]) if (k, m) in ind_t else None, "indec_confidential_rows": ind_s.get((k, m), 0),
                        "nabsa_t": round(nab_t[(k, m)]) if (k, m) in nab_t else None, "nabsa_basis": nab_basis.get((k, m), "")})
dump("ar_oils_public.json", rows_ao)
print("ar_oils_public", len(rows_ao))

# ---------- price strip: outright prices with trend and range context ----------
PX = [("zl1", "Soyoil", "Jan", "CBOT", "c/lb", "ZLF27_CBT.csv", 2), ("zl2", "Soyoil", "Mar", "CBOT", "c/lb", "ZLH27_CBT.csv", 2),
      ("fcpo", "Palm", "3rd month", "Bursa", "MYR/t", "FCPO.csv", 0), ("dy", "Dalian soyoil", "most active", "DCE", "CNY/t", "DCE_Y0.csv", 0),
      ("dp", "Dalian palm olein", "most active", "DCE", "CNY/t", "DCE_P0.csv", 0), ("zm", "Soymeal", "Jan", "CBOT", "$/st", "ZMF27_CBT.csv", 1),
      ("zs", "Soybeans", "Jan", "CBOT", "c/bu", "ZSF27_CBT.csv", 2), ("bz", "Brent", "front", "ICE", "$/bbl", "BZ_F.csv", 2),
      ("ho", "Heating oil", "front", "NYMEX", "$/gal", "HO_F.csv", 4), ("go", "Gasoil", "front", "ICE", "$/t", "ICE_GO.csv", 2),
      ("rs", "Rapeseed", "front", "Euronext", "EUR/t", "MATIF_RS.csv", 2)]
rows_px = []
for i, (pid, name, contract, exch, unit, fn, dp) in enumerate(PX):
    p = os.path.join(D, "daily", fn)
    if not os.path.exists(p): continue
    d = pd.read_csv(p); d["date"] = pd.to_datetime(d["time_utc"]).dt.normalize()
    d = d[d["date"].dt.dayofweek < 5]
    flat = (d["high"] == d["low"]) & (d["volume"].fillna(0) == 0)          # placeholder rows with no trading
    if (d["volume"].fillna(0) > 0).mean() > 0.5: d = d[~flat]
    c = d.groupby("date")["close"].last().dropna()
    if len(c) < 30: continue
    r = np.log(c).diff()
    delta = c.diff(); up = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); dn = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = float(100 - 100 / (1 + up.iloc[-1] / dn.iloc[-1])) if dn.iloc[-1] > 0 else 100.0
    last, prev = float(c.iloc[-1]), float(c.iloc[-2])
    hi20, lo20 = float(c.iloc[-20:].max()), float(c.iloc[-20:].min())
    ma = {n: float(c.iloc[-n:].mean()) for n in (9, 20, 50, 100) if len(c) >= n}
    rows_px.append({"id": pid, "order": i, "market": name, "contract": contract, "exchange": exch, "unit": unit, "dp": dp, "date": f"{c.index[-1]:%Y-%m-%d}",
                    "last": round(last, dp + 1), "chg": round(last - prev, dp + 1), "chg_pct": round((last / prev - 1) * 100, 2),
                    "chg_5d_pct": round((last / float(c.iloc[-6]) - 1) * 100, 2) if len(c) > 6 else None,
                    **{f"ma{n}": round(v, dp + 1) for n, v in ma.items()},
                    "trend": "".join("+" if last > ma[n] else "-" for n in (9, 20, 50, 100) if n in ma),
                    "rsi": round(rsi, 0), "hi20": round(hi20, dp + 1), "lo20": round(lo20, dp + 1),
                    "pos20": round((last - lo20) / (hi20 - lo20) * 100, 0) if hi20 > lo20 else 50,
                    "vol20": round(float(r.iloc[-20:].std() * np.sqrt(252) * 100), 1)})
dump("prices.json", rows_px)
print("prices", [(r_["id"], r_["date"], r_["last"], r_["trend"]) for r_ in rows_px])

# ---------- key levels for soyoil (Jan) and palm: averages, Bollinger, ranges, realised vol, move to option expiry ----------
LV = [("zl", "Soyoil Jan (CBOT)", "c/lb", "ZLF27_CBT.csv", 2, [("Jan options", "2026-12-24")]),
      ("fcpo", "Palm 3rd month (Bursa)", "MYR/t", "FCPO.csv", 0, [])]
rows_lv = []
for lid, lab, unit, fn, dp, expiries in LV:
    d = pd.read_csv(os.path.join(D, "daily", fn)); d["date"] = pd.to_datetime(d["time_utc"]).dt.normalize()
    d = d[d["date"].dt.dayofweek < 5]
    c = d.groupby("date")["close"].last().dropna()
    if len(c) < 120: continue
    last = float(c.iloc[-1]); r = np.log(c).diff()
    m20, s20 = float(c.iloc[-20:].mean()), float(c.iloc[-20:].std())
    lv = [("100-day average", float(c.iloc[-100:].mean())), ("50-day average", float(c.iloc[-50:].mean())),
          ("20-day average", m20), ("9-day average", float(c.iloc[-9:].mean())),
          ("Upper Bollinger (20, 2)", m20 + 2 * s20), ("Lower Bollinger (20, 2)", m20 - 2 * s20),
          ("20-day high", float(c.iloc[-20:].max())), ("20-day low", float(c.iloc[-20:].min())),
          ("60-day high", float(c.iloc[-60:].max())), ("60-day low", float(c.iloc[-60:].min()))]
    for name, v in lv:
        rows_lv.append({"id": f"{lid}-{name}", "market_key": lid, "market": lab, "unit": unit, "dp": dp, "kind": "level", "name": name,
                        "value": round(v, dp + 1), "last": round(last, dp + 1), "dist": round(v - last, dp + 1), "dist_pct": round((v / last - 1) * 100, 2),
                        "date": f"{c.index[-1]:%Y-%m-%d}"})
    vols = {n: float(r.iloc[-n:].std() * np.sqrt(252)) for n in (10, 20, 60)}
    rows_lv.append({"id": f"{lid}-vol", "market_key": lid, "market": lab, "unit": unit, "dp": dp, "kind": "vol", "last": round(last, dp + 1),
                    "vol10": round(vols[10] * 100, 1), "vol20": round(vols[20] * 100, 1), "vol60": round(vols[60] * 100, 1), "date": f"{c.index[-1]:%Y-%m-%d}"})
    for ename, edate in expiries:
        days = (pd.Timestamp(edate) - c.index[-1]).days
        if days <= 0: continue
        mv = last * vols[20] * np.sqrt(days / 365)
        rows_lv.append({"id": f"{lid}-{ename}", "market_key": lid, "market": lab, "unit": unit, "dp": dp, "kind": "expiry", "name": ename, "expiry": edate,
                        "days": int(days), "move": round(mv, dp + 1), "low": round(last - mv, dp + 1), "high": round(last + mv, dp + 1), "last": round(last, dp + 1)})
dump("levels.json", rows_lv)
print("levels", len(rows_lv))

# ---------- climate: El Nino (Nino 3.4 weekly, ONI) and Indian Ocean Dipole (BoM weekly) ----------
CL = os.path.join(D, "climate")
if os.path.exists(os.path.join(CL, "nino34_weekly.csv")) and os.path.exists(os.path.join(CL, "iod_weekly.csv")):
    ni = pd.read_csv(os.path.join(CL, "nino34_weekly.csv"), parse_dates=["week"])
    io = pd.read_csv(os.path.join(CL, "iod_weekly.csv"), parse_dates=["week"])
    rows_cl = [{"id": f"n-{w:%Y-%m-%d}", "kind": "nino34", "week": f"{w:%Y-%m-%d}", "value": float(v)} for w, v in zip(ni["week"], ni["nino34_anom"]) if w >= pd.Timestamp("2014-01-01")]
    rows_cl += [{"id": f"i-{w:%Y-%m-%d}", "kind": "iod", "week": f"{w:%Y-%m-%d}", "value": float(v)} for w, v in zip(io["week"], io["iod"]) if w >= pd.Timestamp("2014-01-01")]
    if os.path.exists(os.path.join(CL, "oni.csv")):
        on = pd.read_csv(os.path.join(CL, "oni.csv")).tail(12)
        rows_cl += [{"id": f"o-{r.year}-{r.season}", "kind": "oni", "season": f"{r.season} {r.year}", "value": float(r.oni)} for r in on.itertuples()]
    dump("climate.json", rows_cl)
    print("climate", len(rows_cl), ni["week"].max(), io["week"].max())

# ---------- biofuel economics: EPA weekly RIN prices and an indicative soyoil biodiesel margin ----------
rp_p = os.path.join(D, "rins", "epa_rin_prices.csv")
if os.path.exists(rp_p):
    rp = pd.read_csv(rp_p, parse_dates=["week"])
    rp = rp[rp["week"] >= pd.Timestamp("2023-01-01")]
    wk = rp.pivot_table(index="week", columns="d_code", values="price")
    rows_bf = [{"id": f"w-{w:%Y-%m-%d}", "kind": "week", "date": f"{w:%Y-%m-%d}", **{k.lower(): (None if pd.isna(v) else round(float(v), 3)) for k, v in r.items()}}
               for w, r in wk.iterrows()]
    # daily margin: heating oil + 1.5 D4 RINs - 7.6 lb soyoil per gallon - $0.70/gal other costs (no tax credit), D4 = latest EPA week on or before the day
    hz = pd.concat([load("HO_F.csv").rename("ho"), load("ZL_F.csv").rename("zl")], axis=1).dropna()
    hz = hz[(hz.index.dayofweek < 5) & (hz.index >= pd.Timestamp("2023-01-01"))]
    d4 = wk["D4"].dropna() if "D4" in wk else pd.Series(dtype=float)
    hz["d4"] = d4.reindex(hz.index.union(d4.index)).ffill().reindex(hz.index)
    hz["d4_week"] = pd.Series(d4.index, index=d4.index).reindex(hz.index.union(d4.index)).ffill().reindex(hz.index)
    hz = hz.dropna(subset=["d4"])
    hz["margin"] = hz["ho"] + 1.5 * hz["d4"] - 7.6 * hz["zl"] / 100 - 0.70
    hz["boho"] = hz["ho"] - hz["zl"] / 100 * 7.37
    rows_bf += [{"id": f"d-{t:%Y-%m-%d}", "kind": "day", "date": f"{t:%Y-%m-%d}", "ho": round(float(r.ho), 4), "zl": round(float(r.zl), 2),
                 "d4_used": round(float(r.d4), 3), "d4_week": f"{r.d4_week:%Y-%m-%d}", "margin": round(float(r.margin), 3), "boho": round(float(r.boho), 3)}
                for t, r in hz.iterrows()]
    dump("biofuel.json", rows_bf)
    print("biofuel", len(rows_bf), wk.index.max(), hz.index.max(), round(float(hz["margin"].iloc[-1]), 3))

# ---------- soyoil options: implied vol, skew, expected move and open interest from CME settlements ----------
import glob
from math import erf, sqrt, log, exp
def _ncdf(x): return 0.5 * (1 + erf(x / sqrt(2)))
def _b76(F, K, T, v, call):
    if v <= 0 or T <= 0: return max(0.0, (F - K) if call else (K - F))
    s = v * sqrt(T); d1 = (log(F / K) + 0.5 * s * s) / s; d2 = d1 - s
    return F * _ncdf(d1) - K * _ncdf(d2) if call else K * _ncdf(-d2) - F * _ncdf(-d1)
def _iv(F, K, T, p, call):
    intr = max(0.0, (F - K) if call else (K - F))
    if p is None or not np.isfinite(p) or p <= intr + 1e-6 or T <= 0: return None
    lo, hi = 0.01, 3.0
    for _ in range(80):
        m = (lo + hi) / 2
        if _b76(F, K, T, m, call) > p: hi = m
        else: lo = m
    return (lo + hi) / 2
opt_files = sorted(glob.glob(os.path.join(D, "options", "zl_options_*.csv")))
if opt_files:
    rows_op = []
    ufile = {"DEC 26": "ZLZ26_CBT.csv", "JAN 27": "ZLF27_CBT.csv", "MAR 27": "ZLH27_CBT.csv", "MAY 27": "ZLK27_CBT.csv", "JUL 27": "ZLN27_CBT.csv"}
    rv20 = {}
    for k_, f_ in ufile.items():
        if os.path.exists(os.path.join(D, "daily", f_)):
            cc = load(f_); cc = cc[cc.index.dayofweek < 5]
            rv20[k_] = float(np.log(cc).diff().iloc[-20:].std() * np.sqrt(252) * 100)
    latest_file = opt_files[-1]
    for fpath in opt_files[-30:]:
        od = pd.read_csv(fpath)
        for (lab, cid), g in od.groupby(["expiry_label", "contract"], sort=False):
            F = float(g["underlying_settle"].iloc[0]); td = pd.Timestamp(g["trade_date"].iloc[0])
            lt = pd.to_datetime(g["last_trade"].iloc[0], format="%d %b %Y", errors="coerce")
            if not np.isfinite(F) or pd.isna(lt): continue
            T = max((lt - td).days, 0) / 365
            if T <= 0: continue
            pts = []
            for K, gg in g.groupby("strike"):
                c = gg[gg["type"] == "C"]["settle"]; p = gg[gg["type"] == "P"]["settle"]
                c = float(c.iloc[0]) if len(c) else None; p = float(p.iloc[0]) if len(p) else None
                use_call = K >= F
                iv = _iv(F, K, T, c if use_call else p, use_call)
                if iv is None: continue
                s_ = iv * sqrt(T); d1 = (log(F / K) + 0.5 * s_ * s_) / s_
                pts.append({"K": float(K), "iv": iv, "dc": _ncdf(d1), "oi_c": float(gg[gg["type"] == "C"]["open_interest"].sum()),
                            "oi_p": float(gg[gg["type"] == "P"]["open_interest"].sum()), "c": c, "p": p})
            pts = [q for q in pts if abs(log(q["K"] / F)) < 0.25]
            if len(pts) < 5: continue
            P = pd.DataFrame(pts).sort_values("K")
            atm = float(np.interp(F, P["K"], P["iv"]))
            byd = P.sort_values("dc")
            c25 = float(np.interp(0.25, byd["dc"], byd["iv"])); p25 = float(np.interp(0.75, byd["dc"], byd["iv"]))   # 25-delta put = 75-delta call
            und = g["underlying"].iloc[0]
            rows_op.append({"id": f"s-{td:%Y-%m-%d}-{cid}", "kind": "summary", "trade_date": f"{td:%Y-%m-%d}", "expiry": lab, "contract": cid,
                            "last_trade": f"{lt:%Y-%m-%d}", "days": int((lt - td).days), "underlying": und, "F": F,
                            "atm_iv": round(atm * 100, 2), "c25_iv": round(c25 * 100, 2), "p25_iv": round(p25 * 100, 2),
                            "rr25": round((c25 - p25) * 100, 2), "bf25": round(((c25 + p25) / 2 - atm) * 100, 2),
                            "move": round(F * atm * sqrt(T), 2), "rv20": round(rv20[und], 1) if und in rv20 else None,
                            "oi_calls": int(P["oi_c"].sum()), "oi_puts": int(P["oi_p"].sum())})
            if fpath == latest_file:
                rows_op += [{"id": f"k-{cid}-{q.K}", "kind": "smile", "trade_date": f"{td:%Y-%m-%d}", "expiry": lab, "contract": cid, "F": F,
                             "strike": q.K, "iv": round(q.iv * 100, 2), "delta_call": round(q.dc, 3), "oi_call": int(q.oi_c), "oi_put": int(q.oi_p),
                             "call": q.c, "put": q.p} for q in P.itertuples()]
    dump("options.json", rows_op)
    print("options", len(rows_op), [(r_["trade_date"], r_["expiry"], r_["atm_iv"], r_["rr25"], r_["move"], r_["rv20"]) for r_ in rows_op if r_["kind"] == "summary"][-4:])

# ---------- Sunflower oil flows: EU imports by origin (Eurostat) and mirror imports of India, China, Turkey, Egypt (UN Comtrade) ----------
SUN_ORIG = {"UA": "Ukraine", "RU": "Russia", "AR": "Argentina", "MD": "Moldova", "RS": "Serbia", "TR": "Turkey", "EXT_EU27_2020": "All origins"}
sun_rows = []
p_eu = os.path.join(D, "sunoil", "eurostat_eu_imports_1512.json")
if os.path.exists(p_eu):
    agg = collections.defaultdict(lambda: [0.0, 0.0])
    for k_i, prod in enumerate(("151211", "151219")):
        body = json.load(open(p_eu)).get(prod, {}).get("body", {})
        if not (isinstance(body, dict) and "value" in body):
            continue
        ids, size = body["id"], body["size"]
        idx = {dn: {i: c for c, i in body["dimension"][dn]["category"]["index"].items()} for dn in ids}
        for flat, val in body["value"].items():
            f, coords = int(flat), []
            for s_ in reversed(size):
                coords.append(f % s_); f //= s_
            rec = {dn: idx[dn][c] for dn, c in zip(ids, reversed(coords))}
            if rec.get("partner") in SUN_ORIG and val:
                agg[(rec["time"], rec["partner"])][k_i] += val / 10
    for (m_, pc), (cr, rf) in sorted(agg.items()):
        sun_rows.append({"kind": "eu", "month": m_[:4] + "-" + m_[-2:], "reporter": "EU-27", "origin": SUN_ORIG[pc], "tons": round(cr + rf), "crude_t": round(cr), "refined_t": round(rf)})
p_ct = os.path.join(D, "sunoil", "comtrade_sunoil_imports.json")
REP = {699: "India", 156: "China", 792: "Turkey", 818: "Egypt"}
PART = {0: "All origins", 643: "Russia", 804: "Ukraine", 32: "Argentina"}
if os.path.exists(p_ct):
    agg = collections.defaultdict(float)
    for r in json.load(open(p_ct)).get("rows", []):
        if r.get("net_kg") in (None, 0) or r["partner_code"] not in PART or r["reporter_code"] not in REP:
            continue
        agg[(f"{r['period'][:4]}-{r['period'][4:6]}", REP[r["reporter_code"]], PART[r["partner_code"]])] += float(r["net_kg"]) / 1000
    for (m_, rep, org), t in sorted(agg.items()):
        sun_rows.append({"kind": "mirror", "month": m_, "reporter": rep, "origin": org, "tons": round(t)})
for i, r in enumerate(sun_rows): r["id"] = f"s{i:05d}"
dump("sun_oil.json", sun_rows)
print("sun_oil", len(sun_rows), max((r["month"] for r in sun_rows if r["kind"] == "eu"), default=None), sorted({(r["reporter"], max(x["month"] for x in sun_rows if x["reporter"] == r["reporter"])) for r in sun_rows}))
