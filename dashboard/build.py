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
