"""Probe public sources for bunker history and TC14 cross-check (research branch)."""
import re, json, os, requests
UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
os.makedirs("out",exist_ok=True); res={}
urls={
 "sb_g20":"https://shipandbunker.com/prices/av/global/av-g20-global-20-ports-average",
 "sb_prices":"https://shipandbunker.com/prices",
 "sb_sin":"https://shipandbunker.com/prices/apac/sea/sg-sin-singapore",
 "hsn_mabux":"https://www.hellenicshippingnews.com/?s=MABUX",
 "hsn_mabux_p2":"https://www.hellenicshippingnews.com/page/2/?s=MABUX",
 "hsn_tc14":"https://www.hellenicshippingnews.com/?s=TC14",
 "edge_search":"https://theedgemalaysia.com/news-search-results?keywords=Baltic%20Exchange%20weekly",
 "mabux":"https://www.mabux.com/",
 "bunkerindex":"https://www.bunkerindex.com/prices/bixfree.php?priceindex_id=4",
 "bunkerindex2":"https://www.bunkerindex.com/",
 "dcn_search":"https://www.thedcn.com.au/?s=baltic+exchange+weekly+report",
}
for k,u in urls.items():
    try:
        r=requests.get(u,headers=UA,timeout=40); t=r.text
        res[k]={"status":r.status_code,"len":len(t),"title":(re.search(r"<title>(.*?)</title>",t,re.S).group(1).strip()[:150] if "<title>" in t else None),
                "has_json_series":bool(re.search(r"\[\s*\[\s*\d{10,13}\s*,\s*[\d.]+\s*\]",t)),
                "scripts":[s[:300] for s in re.findall(r"<script[^>]*>(.*?)</script>",t,re.S) if any(w in s for w in ("data","series","chart","price"))][:6],
                "links":list(dict.fromkeys(re.findall(r'href="(https://www\.hellenicshippingnews\.com/[a-z0-9\-]+/)"',t)))[:40] if "hsn" in k else None,
                "text":" ".join(re.sub(r"<[^>]+>"," ",re.sub(r"<script.*?</script>|<style.*?</style>"," ",t,flags=re.S)).split())[:6000]}
    except Exception as e:
        res[k]={"error":repr(e)[:200]}
json.dump(res,open("out/probe.json","w"),indent=1)
print({k:(v.get("status"),v.get("len"),v.get("has_json_series")) for k,v in res.items()})
