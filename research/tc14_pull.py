"""One-off: Baltic Exchange weekly tanker round-ups -> TC14 / TC2 Worldscale and TCE (public pages)."""
import re, json, os, time, requests
from bs4 import BeautifulSoup
UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
os.makedirs("out",exist_ok=True); rows=[]; raw={}
pages=[(2025,w) for w in range(38,54)]+[(2026,w) for w in range(1,48)]
for y,w in pages:
    u=f"https://www.balticexchange.com/en/data-services/WeeklyRoundup/tanker/news/{y}/tanker-report-week-{w}.html"
    try:
        r=requests.get(u,headers=UA,timeout=40)
        if r.status_code!=200: rows.append({"year":y,"week":w,"status":r.status_code}); continue
        s=BeautifulSoup(r.text,"html.parser"); txt=" ".join(s.get_text(" ").split())
        raw[f"{y}-{w}"]=txt[:20000]
        m=re.search(r"(\d{1,2}(?:st|nd|rd|th)?\s+[A-Z][a-z]+\s+20\d\d)",txt)
        rows.append({"year":y,"week":w,"status":200,"date_text":m.group(1) if m else None,"url":u})
    except Exception as e:
        rows.append({"year":y,"week":w,"status":repr(e)[:100]})
    time.sleep(0.5)
json.dump(rows,open("out/tc14_index.json","w"),indent=1); json.dump(raw,open("out/tc14_raw.json","w"))
print(sum(1 for r in rows if r.get("status")==200),"pages")
