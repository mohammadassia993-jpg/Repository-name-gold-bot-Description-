import os, json, time, sys
import requests
from main import analyze, analyze_smc, find_key_levels, check_near_level, ema, rsi

TWELVE_API_KEY = os.environ.get("TWELVE_API_KEY", "")
WINDOW = 250  # بعد إصلاح EMA200 — يطابق outputsize الجديد المقترح للبوت الحي

def fetch_chunk(end_date=None, outputsize=5000):
    url = (f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval=15min"
           f"&outputsize={outputsize}&apikey={TWELVE_API_KEY}&order=ASC")
    if end_date:
        url += f"&end_date={end_date}"
    r = requests.get(url, timeout=30)
    d = r.json()
    if "values" not in d:
        print("API ERROR:", d)
        return None
    return d["values"]

def to_series(vals):
    closes=[float(x["close"]) for x in vals]
    highs=[float(x["high"]) for x in vals]
    lows=[float(x["low"]) for x in vals]
    opens=[float(x["open"]) for x in vals]
    times=[x["datetime"] for x in vals]
    return closes,highs,lows,opens,times

def build_resampled(series, group):
    out=[]
    n=len(series)
    for j in range(0, n-(n%group), group):
        out.append(series[j:j+group])
    return out

def trend_from_series(closes, size=100):
    c = closes[-size:] if len(closes)>=size else closes
    if len(c)<20: return "NEUTRAL"
    e20=ema(c,20); e50=ema(c,50) if len(c)>=50 else e20
    price=c[-1]; r=rsi(c)
    if price>e20>e50 and r>45: return "UP"
    elif price<e20<e50 and r<55: return "DOWN"
    else: return "NEUTRAL"

def simulate(closes,highs,lows,opens,min_score=3,
             use_smc_gate=False, use_dynamic_d1=False, smc_min=2):
    trades=[]
    open_trade=None
    n=len(closes)

    h1_chunks_c=build_resampled(closes,4)
    d1_chunks_c=build_resampled(closes,96)

    for i in range(WINDOW, n):
        cw=closes[i-WINDOW:i+1]; hw=highs[i-WINDOW:i+1]
        lw=lows[i-WINDOW:i+1];  ow=opens[i-WINDOW:i+1]
        price=cw[-1]

        if open_trade:
            entry=open_trade["entry"]; sl=open_trade["sl"]
            tp1=open_trade["tp1"]; tp2=open_trade["tp2"]; tp3=open_trade["tp3"]
            is_buy=open_trade["is_buy"]
            closed=False
            if (is_buy and price>=tp3) or (not is_buy and price<=tp3):
                pips=round(((price-entry) if is_buy else (entry-price))/0.1,1)
                trades.append({"sig":open_trade["sig"],"result":"WIN_BIG","pips":pips})
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
                    trades.append({"sig":open_trade["sig"],"result":result,"pips":pips})
                    open_trade=None
            continue

        try:
            r=analyze(cw,hw,lw,ow,min_score)
        except Exception:
            continue
        if r["st"]=="WAIT":
            continue
        is_buy="BUY" in r["st"]

        h1_complete=(i+1)//4
        h1_closes=[chunk[-1] for chunk in h1_chunks_c[:h1_complete]]
        h1_dir=trend_from_series(h1_closes,100)

        d1_complete=(i+1)//96
        d1_closes=[chunk[-1] for chunk in d1_chunks_c[:d1_complete]]
        d1_dir=trend_from_series(d1_closes,100)

        if use_dynamic_d1:
            eff_min=min_score
            if d1_dir=="UP" and is_buy: eff_min=min_score-1
            elif d1_dir=="DOWN" and not is_buy: eff_min=min_score-1
            elif d1_dir=="UP" and not is_buy: eff_min=min_score+1
            elif d1_dir=="DOWN" and is_buy: eff_min=min_score+1
            eff_min=max(2,eff_min)
            if abs(r["score"])<eff_min:
                continue

        if h1_dir=="UP" and is_buy: pass
        elif h1_dir=="DOWN" and not is_buy: pass
        elif h1_dir=="NEUTRAL": pass
        else: continue

        smc=analyze_smc(cw,hw,lw,ow,r["atr"],is_buy)
        if use_smc_gate and smc["smc_score"]<smc_min:
            continue

        res,sup=find_key_levels(hw,lw,cw)
        nr,_=check_near_level(r["price"],res,r["atr"],True)
        ns,_=check_near_level(r["price"],sup,r["atr"],False)
        if is_buy and nr: continue
        if not is_buy and ns: continue

        lv=r["lv"]
        open_trade={
            "sig":r["st"],"entry":lv["entry"],"sl":lv["sl"],
            "tp1":lv["tp1"],"tp2":lv["tp2"],"tp3":lv["tp3"],
            "is_buy":is_buy,"tp1_hit":False,"tp2_hit":False
        }
    return trades

def report(trades):
    t=len(trades)
    if t==0: return {"total":0}
    w=len([x for x in trades if "WIN" in x["result"]])
    l=t-w
    gains=sum(x["pips"] for x in trades if x["pips"]>0)
    loss_sum=abs(sum(x["pips"] for x in trades if x["pips"]<0))
    pf=round(gains/loss_sum,2) if loss_sum>0 else None
    net=round(sum(x["pips"] for x in trades),1)
    by_type={}
    for x in trades:
        by_type.setdefault(x["sig"],{"n":0,"w":0,"pips":0})
        by_type[x["sig"]]["n"]+=1
        if "WIN" in x["result"]: by_type[x["sig"]]["w"]+=1
        by_type[x["sig"]]["pips"]+=x["pips"]
    return {"total":t,"wins":w,"losses":l,"win_rate":round(w/t*100,1),
            "profit_factor":pf,"net_pips":net,
            "avg_pips_per_trade":round(net/t,1),"by_type":by_type}

if __name__=="__main__":
    periods=[(None,"الأحدث"), ("2025-09-15 00:00:00","أبعد (~عام)")]
    configs=[
        ("baseline", dict(use_smc_gate=False, use_dynamic_d1=False)),
        ("محسّن", dict(use_smc_gate=True, use_dynamic_d1=True)),
    ]
    all_results={}
    for end_date,plabel in periods:
        vals=fetch_chunk(end_date=end_date,outputsize=5000)
        if not vals:
            all_results[plabel]={"error":"فشل الجلب"}; continue
        closes,highs,lows,opens,times=to_series(vals)
        print(plabel, len(closes), times[0], "->", times[-1])
        all_results[plabel]={"period_start":times[0],"period_end":times[-1],"candles":len(closes),"configs":{}}
        for clabel,kw in configs:
            trades=simulate(closes,highs,lows,opens,min_score=3,**kw)
            res=report(trades)
            print(" ", clabel, "=>", json.dumps(res,ensure_ascii=False))
            all_results[plabel]["configs"][clabel]=res
            time.sleep(1)
        time.sleep(2)
    with open("backtest_result.json","w") as f:
        json.dump(all_results,f,ensure_ascii=False,indent=2)
