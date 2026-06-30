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

def simulate_random(closes,highs,lows,opens,window=250,entry_prob=0.02,seed=None,sl_mult=None):
    import random
    rng=random.Random(seed)
    trades=[]
    open_trade=None
    n=len(closes)
    for i in range(window, n):
        price=closes[i]; atr_v=calc_atr_simple(highs,lows,closes,i)
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
        if atr_v is None or rng.random()>entry_prob:
            continue
        is_buy = rng.random()<0.5
        m = sl_mult if sl_mult is not None else 1.5
        sl_val = round(price-atr_v*m if is_buy else price+atr_v*m,2)
        tp1 = round(price+atr_v*2.0 if is_buy else price-atr_v*2.0,2)
        tp2 = round(price+atr_v*3.5 if is_buy else price-atr_v*3.5,2)
        tp3 = round(price+atr_v*6.0 if is_buy else price-atr_v*6.0,2)
        open_trade={"sig":"BUY_RND" if is_buy else "SELL_RND","entry":price,"sl":sl_val,
                    "tp1":tp1,"tp2":tp2,"tp3":tp3,"is_buy":is_buy,"tp1_hit":False,"tp2_hit":False}
    return trades

def calc_atr_simple(highs,lows,closes,i,n=14):
    if i<n+1: return None
    trs=[]
    for k in range(i-n+1,i+1):
        tr=max(highs[k]-lows[k], abs(highs[k]-closes[k-1]), abs(lows[k]-closes[k-1]))
        trs.append(tr)
    return sum(trs)/len(trs)

def simulate(closes,highs,lows,opens,min_score=3,
             use_smc_gate=False, use_dynamic_d1=False, smc_min=2, window=250,
             sl_mult=None):
    trades=[]
    open_trade=None
    n=len(closes)

    h1_chunks_c=build_resampled(closes,4)
    d1_chunks_c=build_resampled(closes,96)

    for i in range(window, n):
        cw=closes[i-window:i+1]; hw=highs[i-window:i+1]
        lw=lows[i-window:i+1];  ow=opens[i-window:i+1]
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
        sl_val=lv["sl"]
        if sl_mult is not None:
            entry_p=lv["entry"]; atr_v=r["atr"]
            sl_val=round(entry_p-atr_v*sl_mult if is_buy else entry_p+atr_v*sl_mult,2)
        open_trade={
            "sig":r["st"],"entry":lv["entry"],"sl":sl_val,
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
    real_kw=dict(use_smc_gate=False, use_dynamic_d1=False, window=60, sl_mult=1.5)
    all_results={}
    for end_date,plabel in periods:
        vals=fetch_chunk(end_date=end_date,outputsize=5000)
        if not vals:
            all_results[plabel]={"error":"فشل الجلب"}; continue
        closes,highs,lows,opens,times=to_series(vals)
        print(plabel, len(closes), times[0], "->", times[-1])
        all_results[plabel]={"period_start":times[0],"period_end":times[-1],"candles":len(closes),"configs":{}}

        real_trades=simulate(closes,highs,lows,opens,min_score=3,**real_kw)
        real_res=report(real_trades)
        print(" الإستراتيجية الحقيقية =>", json.dumps(real_res,ensure_ascii=False))
        all_results[plabel]["configs"]["الإستراتيجية الحقيقية"]=real_res

        target_n = max(real_res.get("total",50),50)
        entry_prob = min(0.5, target_n / max(1,(len(closes)-60)))
        rand_runs=[]
        for seed in range(5):
            rt=simulate_random(closes,highs,lows,opens,window=60,entry_prob=entry_prob,seed=seed,sl_mult=1.5)
            rr=report(rt)
            rand_runs.append(rr)
            print(f"  عشوائي #{seed} =>", json.dumps(rr,ensure_ascii=False))
            time.sleep(0.5)
        valid=[r for r in rand_runs if r.get("total",0)>0]
        if valid:
            avg_pf=round(sum(r["profit_factor"] or 0 for r in valid)/len(valid),2)
            avg_wr=round(sum(r["win_rate"] for r in valid)/len(valid),1)
            avg_net=round(sum(r["net_pips"] for r in valid)/len(valid),1)
            avg_total=round(sum(r["total"] for r in valid)/len(valid),1)
        else:
            avg_pf=avg_wr=avg_net=avg_total=None
        summary={"avg_total":avg_total,"avg_win_rate":avg_wr,"avg_profit_factor":avg_pf,"avg_net_pips":avg_net,"runs":rand_runs}
        print(" متوسط العشوائي (5 محاولات) =>", json.dumps(summary,ensure_ascii=False))
        all_results[plabel]["configs"]["متوسط عشوائي (5 محاولات)"]=summary
        time.sleep(2)
    with open("backtest_result.json","w") as f:
        json.dump(all_results,f,ensure_ascii=False,indent=2)
