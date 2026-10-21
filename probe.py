import json, requests, re, time
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
out={}
def t(name, fn):
    try: out[name]=fn()
    except Exception as e: out[name]="ERR "+str(e)[:200]
def sina(codes):
    r=requests.get("https://hq.sinajs.cn/list="+",".join(codes),headers={**UA,"Referer":"https://finance.sina.com.cn"},timeout=20); r.encoding="gbk"; return r.text[:3000]
t("sina_hf", lambda: sina(["hf_BO","hf_SM","hf_S","hf_C","hf_HO","hf_OIL","hf_CL","hf_FCPO","hf_CPO","hf_ZL"]))
t("sina_fx", lambda: sina(["fx_susdmyr","fx_susdbrl","fx_susdinr","fx_susdcny","fx_seurusd","fx_susdidr"]))
def stooq(s):
    r=requests.get(f"https://stooq.com/q/d/l/?s={s}&i=d",headers=UA,timeout=20); return r.text[:300]
for s in ["zl.f","zm.f","zs.f","zc.f","ho.f","cb.f","usdmyr","zlz6.f"]:
    t("stooq_"+s, lambda s=s: stooq(s)); time.sleep(1)
def yf():
    import yfinance as yf
    h=yf.Ticker("ZL=F").history(period="5d"); return h.tail(3).to_string()
t("yfinance_ZL", yf)
def yfc():
    import yfinance as yf
    h=yf.Ticker("ZLZ26.CBT").history(period="5d"); return h.tail(2).to_string()
t("yfinance_ZLZ26", yfc)
print(json.dumps(out,indent=1,ensure_ascii=False))
json.dump(out,open("data/probe.json","w"),indent=1,ensure_ascii=False)
