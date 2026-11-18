import re, json, os, requests
UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
os.makedirs("out",exist_ok=True); res={}
def txt(h): return " ".join(re.sub(r"<[^>]+>"," ",re.sub(r"<script.*?</script>|<style.*?</style>"," ",h,flags=re.S)).split())
r=requests.get("https://theedgemalaysia.com/news-search-results?keywords=Baltic%20Exchange%20shipping%20updates",headers=UA,timeout=40).text
res["edge_raw_snips"]=[r[max(0,m.start()-400):m.start()+300] for m in re.finditer(r"Baltic Exchange shipping updates",r)][:4]
res["edge_nodes"]=re.findall(r"/node/(\d+)",r)[:40]
r2=requests.get("https://theedgemalaysia.com/news-search-results?keywords=Baltic%20Exchange%20shipping%20updates&page=2",headers=UA,timeout=40).text
res["edge_p2_titles"]=re.findall(r"Baltic Exchange shipping updates: (\w{3} \d{1,2}, \d{4})",r2)[:20]
sb=requests.get("https://shipandbunker.com/prices/av/global/av-g20-global-20-ports-average",headers=UA,timeout=40).text
m=re.search(r"const PORT_CHART\s*=\s*(\{.*?\});",sb,re.S)
if m:
    j=json.loads(m.group(1)); res["sb_keys"]={k:(len(v),v[0],v[-1]) for k,v in j.items()}
hs=requests.get("https://www.hellenicshippingnews.com/mabux-global-bunker-market-to-maintain-a-firm-but-highly-volatile-trend-in-november/",headers=UA,timeout=40).text
t=txt(hs); i=t.find("MABUX"); res["hsn_mabux_month"]=t[i:i+3000]
hs2=requests.get("https://www.hellenicshippingnews.com/mabux-bunker-prices-volatility-to-continue-next-week/",headers=UA,timeout=40).text
t2=txt(hs2); i=t2.find("World Bunker Index"); res["hsn_mabux_week"]=t2[max(0,i-300):i+2500]
json.dump(res,open("out/probe2.json","w"),indent=1); print("ok")
