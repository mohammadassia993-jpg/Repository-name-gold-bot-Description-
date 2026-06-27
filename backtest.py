import os, json, time, sys
import requests
from main import analyze

TWELVE_API_KEY = os.environ.get("TWELVE_API_KEY", "")
WINDOW = 60  # نفس النافذة المستخدمة فعلياً في البوت الحي (get_data outputsize=60)

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
    vals = d["values"]
    return vals

def to_series(vals):
    closes=[float(x["close"]) for x in vals]
    highs=[float(x["high"]) for x in vals]
    lows=[float(x["low"]) for x in vals]
    opens=[float(x["open"]) for x in vals]
    times=[x["datetime"] for x in vals]
    return closes,highs,lows,opens,times

def simulate(closes,highs,lows,opens,min_score=3):
    trades=[]
    open_trade=None
    n=len(closes)
    for i in range(WINDOW, n):
        cw=closes[i-WINDOW:i+1]; hw=highs[i-WINDOW:i+1]
        lw=lows[i-WINDOW:i+1];   ow=opens[i-WINDOW:i+1]
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
        except Exception as e:
            continue
        if r["st"]!="WAIT":
            lv=r["lv"]
            open_trade={
                "sig":r["st"],"entry":lv["entry"],"sl":lv["sl"],
                "tp1":lv["tp1"],"tp2":lv["tp2"],"tp3":lv["tp3"],
                "is_buy":"BUY" in r["st"],"tp1_hit":False,"tp2_hit":False
            }
    return trades

def report(trades):
    t=len(trades)
    if t==0:
        return {"total":0}
    wins=[x for x in trades if "WIN" in x["result"]]
    losses=[x for x in trades if x["result"]=="LOSS"]
    w=len(wins); l=len(losses)
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
    return {
        "total":t,"wins":w,"losses":l,
        "win_rate":round(w/t*100,1),
        "profit_factor":pf,"net_pips":net,
        "avg_pips_per_trade":round(net/t,1),
        "by_type":by_type
    }

if __name__=="__main__":
    end_date = sys.argv[1] if len(sys.argv)>1 else None
    out_name = sys.argv[2] if len(sys.argv)>2 else "backtest_result.json"
    print("جلب البيانات التاريخية...", "end_date=", end_date)
    vals = fetch_chunk(end_date=end_date, outputsize=5000)
    if not vals:
        print("فشل الجلب — توقف"); sys.exit(1)
    closes,highs,lows,opens,times = to_series(vals)
    print(f"عدد الشموع: {len(closes)} | من {times[0]} إلى {times[-1]}")
    trades = simulate(closes,highs,lows,opens,min_score=3)
    result = report(trades)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    with open(out_name,"w") as f:
        json.dump({"period_start":times[0],"period_end":times[-1],
                   "candles":len(closes),"result":result,
                   "trades":trades}, f, ensure_ascii=False, indent=2)
