import os, json, time, sys
import requests
from main import ema, rsi, calc_atr, wave_trend, analyze_smc

TWELVE_API_KEY = os.environ.get("TWELVE_API_KEY", "")
WINDOW = 60
SL_MULT = 1.5
ATR_TP1, ATR_TP2, ATR_TP3 = 2.0, 3.5, 6.0

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

def signal_ema(cw,hw,lw,ow,atr):
    e20=ema(cw,20); e50=ema(cw,50); price=cw[-1]
    if price>e20>e50: return "BUY"
    if price<e20<e50: return "SELL"
    return None

def signal_rsi(cw,hw,lw,ow,atr):
    r=rsi(cw)
    if r<30: return "BUY"
    if r>70: return "SELL"
    return None

def signal_macd(cw,hw,lw,ow,atr):
    macd=ema(cw,12)-ema(cw,26)
    return "BUY" if macd>0 else "SELL"

def signal_wavetrend(cw,hw,lw,ow,atr):
    wt1,wt2,wt_sig,oversold,overbought=wave_trend(cw,hw,lw)
    if wt_sig=="BUY": return "BUY"
    if wt_sig=="SELL": return "SELL"
    return None

def signal_smc(cw,hw,lw,ow,atr):
    smc_buy=analyze_smc(cw,hw,lw,ow,atr,True)
    smc_sell=analyze_smc(cw,hw,lw,ow,atr,False)
    if smc_buy["smc_score"]>=3 and smc_buy["smc_score"]>smc_sell["smc_score"]:
        return "BUY"
    if smc_sell["smc_score"]>=3 and smc_sell["smc_score"]>smc_buy["smc_score"]:
        return "SELL"
    return None

COMPONENTS = {
    "EMA20/50 فقط": signal_ema,
    "RSI فقط": signal_rsi,
    "MACD فقط": signal_macd,
    "WaveTrend فقط": signal_wavetrend,
    "SMC فقط": signal_smc,
}

def simulate_component(closes,highs,lows,opens,signal_fn,window=WINDOW):
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
                trades.append({"result":"WIN_BIG","pips":pips})
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
                    trades.append({"result":result,"pips":pips})
                    open_trade=None
            continue

        try:
            atr=calc_atr(hw,lw,cw)
            sig=signal_fn(cw,hw,lw,ow,atr)
        except Exception:
            continue
        if sig is None: continue
        is_buy = sig=="BUY"
        sl_val=round(price-atr*SL_MULT if is_buy else price+atr*SL_MULT,2)
        tp1=round(price+atr*ATR_TP1 if is_buy else price-atr*ATR_TP1,2)
        tp2=round(price+atr*ATR_TP2 if is_buy else price-atr*ATR_TP2,2)
        tp3=round(price+atr*ATR_TP3 if is_buy else price-atr*ATR_TP3,2)
        open_trade={"entry":price,"sl":sl_val,"tp1":tp1,"tp2":tp2,"tp3":tp3,
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
    all_results={}
    for end_date,plabel in periods:
        vals=fetch_chunk(end_date=end_date,outputsize=5000)
        if not vals:
            all_results[plabel]={"error":"فشل الجلب"}; continue
        closes,highs,lows,opens,times=to_series(vals)
        print(plabel, len(closes), times[0],"->",times[-1])
        all_results[plabel]={"period_start":times[0],"period_end":times[-1],"candles":len(closes),"components":{}}
        for clabel,fn in COMPONENTS.items():
            trades=simulate_component(closes,highs,lows,opens,fn)
            res=report(trades)
            print(" ",clabel,"=>",json.dumps(res,ensure_ascii=False))
            all_results[plabel]["components"][clabel]=res
            time.sleep(1)
        time.sleep(2)
    with open("backtest_result.json","w") as f:
        json.dump(all_results,f,ensure_ascii=False,indent=2)
