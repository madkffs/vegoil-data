"""One-off: Baltic Exchange weekly report as republished by DCN (public) -> TC14/TC2 sentences."""
import re, json, os, time, datetime as dt, requests
from bs4 import BeautifulSoup
UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
os.makedirs("out",exist_ok=True); out=[]
d=dt.date(2025,10,31)
while d<=dt.date(2026,11,20):
    got=False
    for dd in [d, d-dt.timedelta(days=1), d+dt.timedelta(days=3)]:
        slug=f"baltic-exchange-weekly-report-{dd.day}-{dd.strftime('%B').lower()}-{dd.year}"
        u=f"https://www.thedcn.com.au/news/{slug}"
        try:
            r=requests.get(u,headers=UA,timeout=40)
        except Exception as e:
            continue
        if r.status_code==200 and "TC14" in r.text:
            s=BeautifulSoup(r.text,"html.parser"); txt=" ".join(s.get_text(" ").split())
            sents=[x for x in re.split(r"(?<=[.!?])\s+",txt) if "TC14" in x or "TC2 " in x or "TC2," in x or "MR " in x and "Atlantic" in x]
            out.append({"week_of":str(d),"page_date":str(dd),"url":u,"sentences":sents[:12]}); got=True; break
        time.sleep(0.4)
    if not got: out.append({"week_of":str(d),"missing":True})
    d+=dt.timedelta(days=7)
json.dump(out,open("out/tc14_dcn.json","w"),indent=1)
print(sum(1 for x in out if not x.get("missing")),"of",len(out))
