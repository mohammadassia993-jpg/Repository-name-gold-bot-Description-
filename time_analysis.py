import os, json, time
import requests
from datetime import datetime, timedelta
from main import analyze

TWELVE_API_KEY = os.environ.get("TWELVE_API_KEY", "")
WINDOW = 60
SL_MULT = 1.5

def fetch_chunk(end_date=None, outputsize=5000):
    url = (f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval=15min"
           f"&outputsize={outputsize}&apikey={TWELVE_API_KEY}&order=ASC")
    if end_date: url += f"&end_date={end_date}"
    r = requests.get(url, timeout=30)
    d = r.json()
    if "values" not in d:
        print("API ERROR:", d); return None
    return d["values"]

def to_series(vals):
    closes=[float(x["close"]) for x in vals]
    highs=[float(x["high"]) for x in vals]
    lows=[float(x["low"]) for x in vals]
    opens=[float(x["open"]) for x in vals]
    times=[x["datetime"] for x in vals]
    return closes,highs,lows,opens,times

def simulate_with_time(closes,highs,lows,opens,times,min_score=3,window=WINDOW,sl_mult=SL_MULT):
    trades=[]
    open_trade=None
    n=len(closes)
    for i in range(window, n):
        cw=closes[i-window:i+1]; hw=highs[i-window:i+1]
        lw=lows[i-window:i+1];   ow=opens[i-window:i+1]
        price=cw[-1]

        if open_trade:
            entry=open_trade["entry"]; sl=open_trade["sl"]
            tp1=open_trade["tp1"]; tp2=open_trade["tp2"]; tp3=open_trade["tp3"]
            is_buy=open_trade["is_buy"]
            closed=False
            if (is_buy and price>=tp3) or (not is_buy and price<=tp3):
                pips=round(((price-entry) if is_buy else (entry-price))/0.1,1)
                trades.append({"result":"WIN_BIG","pips":pips,"hour":open_trade["hour"],"weekday":open_trade["weekday"]})
                open_trade=None; closed=True
            elif not open_trade["tp2_hit"] and ((is_buy and price>=tp2) or (not is_buy and price<=tp2)):
                open_trade["tp2_hit"]=True
            elif not open_trade["tp1_hit"] and ((is_buy and price>=tp1) or (not is_buy and price<=tp1)):
                open_trade["tp1_hit"]=True
            if not closed and open_trade:
                stop = tp1 if open_trade["tp2_hit"] else (entry if open_trade["tp1_hit"] else sl)
                if (is_buy and price<=stop) or (not is_buy and price>=stop):
                    pips=round(((price-entry) if is_buy else (entry-price))/0.1,1)
                    result="WIN" if pips>=0 else "LOSS"
                    trades.append({"result":result,"pips":pips,"hour":open_trade["hour"],"weekday":open_trade["weekday"]})
                    open_trade=None
            continue

        try:
            r=analyze(cw,hw,lw,ow,min_score)
        except Exception:
            continue
        if r["st"]=="WAIT":
            continue
        is_buy="BUY" in r["st"]
        lv=r["lv"]
        sl_val=round(lv["entry"]-r["atr"]*sl_mult if is_buy else lv["entry"]+r["atr"]*sl_mult,2)

        dt=datetime.strptime(times[i],"%Y-%m-%d %H:%M:%S")
        syria_dt = dt + timedelta(hours=3)  # بيانات Twelve Data بتوقيت UTC تقريباً

        open_trade={
            "entry":lv["entry"],"sl":sl_val,
            "tp1":lv["tp1"],"tp2":lv["tp2"],"tp3":lv["tp3"],
            "is_buy":is_buy,"tp1_hit":False,"tp2_hit":False,
            "hour":syria_dt.hour,"weekday":syria_dt.weekday()
        }
    return trades

def bucket_report(trades, key):
    buckets={}
    for t in trades:
        k=t[key]
        b=buckets.setdefault(k,{"n":0,"w":0,"pips":0.0})
        b["n"]+=1
        if "WIN" in t["result"]: b["w"]+=1
        b["pips"]+=t["pips"]
    out={}
    for k,v in sorted(buckets.items()):
        gains=sum(t["pips"] for t in trades if t[key]==k and t["pips"]>0)
        losses=abs(sum(t["pips"] for t in trades if t[key]==k and t["pips"]<0))
        pf=round(gains/losses,2) if losses>0 else None
        out[str(k)]={"n":v["n"],"win_rate":round(v["w"]/v["n"]*100,1),
                     "net_pips":round(v["pips"],1),"profit_factor":pf}
    return out

if __name__=="__main__":
    periods=[(None,"الأحدث"), ("2025-09-15 00:00:00","أبعد (~عام)")]
    all_results={}
    for end_date,plabel in periods:
        vals=fetch_chunk(end_date=end_date,outputsize=5000)
        if not vals:
            all_results[plabel]={"error":"فشل الجلب"}; continue
        closes,highs,lows,opens,times=to_series(vals)
        print(plabel,len(closes),times[0],"->",times[-1])
        trades=simulate_with_time(closes,highs,lows,opens,times)
        print(f" عدد الصفقات: {len(trades)}")
        by_hour=bucket_report(trades,"hour")
        by_day=bucket_report(trades,"weekday")
        print(" حسب الساعة (سوريا):", json.dumps(by_hour,ensure_ascii=False))
        print(" حسب اليوم (0=اثنين):", json.dumps(by_day,ensure_ascii=False))
        all_results[plabel]={"period_start":times[0],"period_end":times[-1],
                              "total_trades":len(trades),
                              "by_hour":by_hour,"by_weekday":by_day}
        time.sleep(2)
    with open("backtest_result.json","w") as f:
        json.dump(all_results,f,ensure_ascii=False,indent=2)
