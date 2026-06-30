import os, json, time
import requests
from main import ema, rsi, calc_atr, wave_trend

TWELVE_API_KEY = os.environ.get("TWELVE_API_KEY", "")
WINDOW = 60
SL_MULT = 1.5
ATR_TP1, ATR_TP2, ATR_TP3 = 2.0, 3.5, 6.0

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

def weighted_analyze(closes,highs,lows,opens,min_score,macd_w,ema_w,rsi_w,wt_w):
    price=closes[-1]
    r=rsi(closes); e20=ema(closes,20); e50=ema(closes,50)
    macd=ema(closes,12)-ema(closes,26)
    a=calc_atr(highs,lows,closes)
    wt1,wt2,wt_sig,oversold,overbought=wave_trend(closes,highs,lows)
    score=0
    if price>e20>e50: score+=ema_w
    elif price<e20<e50: score-=ema_w
    if r<30: score+=rsi_w
    elif r>70: score-=rsi_w
    if macd>0: score+=macd_w
    else: score-=macd_w
    if wt_sig=="BUY": score+=wt_w
    elif wt_sig=="SELL": score-=wt_w
    if score>=min_score: st="BUY"
    elif score<=-min_score: st="SELL"
    else: st="WAIT"
    return st,score,price,a

def simulate(closes,highs,lows,opens,min_score,macd_w,ema_w,rsi_w,wt_w,window=WINDOW):
    trades=[]; open_trade=None; n=len(closes)
    for i in range(window,n):
        cw=closes[i-window:i+1]; hw=highs[i-window:i+1]
        lw=lows[i-window:i+1];   ow=opens[i-window:i+1]
        price=cw[-1]
        if open_trade:
            entry=open_trade["entry"]; sl=open_trade["sl"]
            tp1=open_trade["tp1"]; tp2=open_trade["tp2"]; tp3=open_trade["tp3"]
            is_buy=open_trade["is_buy"]; closed=False
            if (is_buy and price>=tp3) or (not is_buy and price<=tp3):
                pips=round(((price-entry) if is_buy else (entry-price))/0.1,1)
                trades.append({"result":"WIN_BIG","pips":pips}); open_trade=None; closed=True
            elif not open_trade["tp2_hit"] and ((is_buy and price>=tp2) or (not is_buy and price<=tp2)):
                open_trade["tp2_hit"]=True
            elif not open_trade["tp1_hit"] and ((is_buy and price>=tp1) or (not is_buy and price<=tp1)):
                open_trade["tp1_hit"]=True
            if not closed and open_trade:
                stop = tp1 if open_trade["tp2_hit"] else (entry if open_trade["tp1_hit"] else sl)
                if (is_buy and price<=stop) or (not is_buy and price>=stop):
                    pips=round(((price-entry) if is_buy else (entry-price))/0.1,1)
                    result="WIN" if pips>=0 else "LOSS"
                    trades.append({"result":result,"pips":pips}); open_trade=None
            continue
        try:
            st,score,p,atr=weighted_analyze(cw,hw,lw,ow,min_score,macd_w,ema_w,rsi_w,wt_w)
        except Exception:
            continue
        if st=="WAIT": continue
        is_buy = st=="BUY"
        sl_val=round(p-atr*SL_MULT if is_buy else p+atr*SL_MULT,2)
        tp1=round(p+atr*ATR_TP1 if is_buy else p-atr*ATR_TP1,2)
        tp2=round(p+atr*ATR_TP2 if is_buy else p-atr*ATR_TP2,2)
        tp3=round(p+atr*ATR_TP3 if is_buy else p-atr*ATR_TP3,2)
        open_trade={"entry":p,"sl":sl_val,"tp1":tp1,"tp2":tp2,"tp3":tp3,
                    "is_buy":is_buy,"tp1_hit":False,"tp2_hit":False}
    return trades

def build_resampled(series, group):
    out=[]
    n=len(series)
    for j in range(0, n-(n%group), group):
        out.append(series[j:j+group])
    return out

def trend_from_d1(closes,size=100):
    c=closes[-size:] if len(closes)>=size else closes
    if len(c)<20: return "NEUTRAL"
    e20=ema(c,20); e50=ema(c,50) if len(c)>=50 else e20
    price=c[-1]; r=rsi(c)
    if price>e20>e50 and r>45: return "UP"
    elif price<e20<e50 and r<55: return "DOWN"
    else: return "NEUTRAL"

def weighted_analyze_dynamic(closes,highs,lows,opens,min_score,ema_w,rsi_w,wt_w,
                              macd_w_aligned,macd_w_normal,d1_dir):
    price=closes[-1]
    r=rsi(closes); e20=ema(closes,20); e50=ema(closes,50)
    macd=ema(closes,12)-ema(closes,26)
    a=calc_atr(highs,lows,closes)
    wt1,wt2,wt_sig,oversold,overbought=wave_trend(closes,highs,lows)
    macd_dir_up = macd>0
    aligned = (macd_dir_up and d1_dir=="UP") or (not macd_dir_up and d1_dir=="DOWN")
    macd_w = macd_w_aligned if aligned else macd_w_normal
    score=0
    if price>e20>e50: score+=ema_w
    elif price<e20<e50: score-=ema_w
    if r<30: score+=rsi_w
    elif r>70: score-=rsi_w
    if macd>0: score+=macd_w
    else: score-=macd_w
    if wt_sig=="BUY": score+=wt_w
    elif wt_sig=="SELL": score-=wt_w
    if score>=min_score: st="BUY"
    elif score<=-min_score: st="SELL"
    else: st="WAIT"
    return st,score,price,a

def simulate_dynamic(closes,highs,lows,opens,min_score,ema_w,rsi_w,wt_w,
                      macd_w_aligned,macd_w_normal,window=WINDOW):
    trades=[]; open_trade=None; n=len(closes)
    d1_chunks_c=build_resampled(closes,96)
    for i in range(window,n):
        cw=closes[i-window:i+1]; hw=highs[i-window:i+1]
        lw=lows[i-window:i+1];   ow=opens[i-window:i+1]
        price=cw[-1]
        if open_trade:
            entry=open_trade["entry"]; sl=open_trade["sl"]
            tp1=open_trade["tp1"]; tp2=open_trade["tp2"]; tp3=open_trade["tp3"]
            is_buy=open_trade["is_buy"]; closed=False
            if (is_buy and price>=tp3) or (not is_buy and price<=tp3):
                pips=round(((price-entry) if is_buy else (entry-price))/0.1,1)
                trades.append({"result":"WIN_BIG","pips":pips}); open_trade=None; closed=True
            elif not open_trade["tp2_hit"] and ((is_buy and price>=tp2) or (not is_buy and price<=tp2)):
                open_trade["tp2_hit"]=True
            elif not open_trade["tp1_hit"] and ((is_buy and price>=tp1) or (not is_buy and price<=tp1)):
                open_trade["tp1_hit"]=True
            if not closed and open_trade:
                stop = tp1 if open_trade["tp2_hit"] else (entry if open_trade["tp1_hit"] else sl)
                if (is_buy and price<=stop) or (not is_buy and price>=stop):
                    pips=round(((price-entry) if is_buy else (entry-price))/0.1,1)
                    result="WIN" if pips>=0 else "LOSS"
                    trades.append({"result":result,"pips":pips}); open_trade=None
            continue
        d1_complete=(i+1)//96
        d1_closes=[chunk[-1] for chunk in d1_chunks_c[:d1_complete]]
        d1_dir=trend_from_d1(d1_closes,100)
        try:
            st,score,p,atr=weighted_analyze_dynamic(cw,hw,lw,ow,min_score,ema_w,rsi_w,wt_w,
                                                      macd_w_aligned,macd_w_normal,d1_dir)
        except Exception:
            continue
        if st=="WAIT": continue
        is_buy = st=="BUY"
        sl_val=round(p-atr*SL_MULT if is_buy else p+atr*SL_MULT,2)
        tp1=round(p+atr*ATR_TP1 if is_buy else p-atr*ATR_TP1,2)
        tp2=round(p+atr*ATR_TP2 if is_buy else p-atr*ATR_TP2,2)
        tp3=round(p+atr*ATR_TP3 if is_buy else p-atr*ATR_TP3,2)
        open_trade={"entry":p,"sl":sl_val,"tp1":tp1,"tp2":tp2,"tp3":tp3,
                    "is_buy":is_buy,"tp1_hit":False,"tp2_hit":False}
    return trades

def report(trades):
    t=len(trades)
    if t==0: return {"total":0}
    w=len([x for x in trades if "WIN" in x["result"]])
    gains=sum(x["pips"] for x in trades if x["pips"]>0)
    loss_sum=abs(sum(x["pips"] for x in trades if x["pips"]<0))
    pf=round(gains/loss_sum,2) if loss_sum>0 else None
    net=round(sum(x["pips"] for x in trades),1)
    return {"total":t,"wins":w,"losses":t-w,"win_rate":round(w/t*100,1),
            "profit_factor":pf,"net_pips":net,"avg_pips_per_trade":round(net/t,1)}

if __name__=="__main__":
    periods=[(None,"الأحدث"), ("2025-09-15 00:00:00","أبعد (~عام)")]
    configs=[
        ("الحالي (EMA2 RSI2 MACD1 WT2)", dict(min_score=3,macd_w=1,ema_w=2,rsi_w=2,wt_w=2)),
        ("MACD مُرجَّح (EMA1 RSI1 MACD3 WT0)", dict(min_score=3,macd_w=3,ema_w=1,rsi_w=1,wt_w=0)),
    ]
    all_results={}
    for end_date,plabel in periods:
        vals=fetch_chunk(end_date=end_date,outputsize=5000)
        if not vals:
            all_results[plabel]={"error":"فشل الجلب"}; continue
        closes,highs,lows,opens,times=to_series(vals)
        print(plabel,len(closes),times[0],"->",times[-1])
        all_results[plabel]={"period_start":times[0],"period_end":times[-1],"candles":len(closes),"configs":{}}
        for clabel,kw in configs:
            trades=simulate(closes,highs,lows,opens,**kw)
            res=report(trades)
            print(" ",clabel,"=>",json.dumps(res,ensure_ascii=False))
            all_results[plabel]["configs"][clabel]=res
            time.sleep(1)
        dyn_trades=simulate_dynamic(closes,highs,lows,opens,min_score=3,ema_w=2,rsi_w=2,wt_w=2,
                                     macd_w_aligned=3,macd_w_normal=1)
        dyn_res=report(dyn_trades)
        print(" MACD ديناميكي حسب D1 =>",json.dumps(dyn_res,ensure_ascii=False))
        all_results[plabel]["configs"]["MACD ديناميكي حسب D1"]=dyn_res
        time.sleep(2)
    with open("backtest_result.json","w") as f:
        json.dump(all_results,f,ensure_ascii=False,indent=2)
