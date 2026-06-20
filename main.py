import requests, json, os, time, threading
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

BOT_TOKEN    = "8901717984:AAFaG9H3FNiIgfa2AGRVU8q7nTdn0kCoK4s"
CHAT_ID      = "888229115"
DATA_FILE    = "data.json"
SYRIA_OPEN   = 8
SYRIA_CLOSE  = 23

# ── نسب SL/TP المحسّنة (R:R أفضل) ──
ATR_SL  = 1.0   # أضيق من قبل (كان 1.5)
ATR_TP1 = 2.0   # 1:2  (كان 1.5)
ATR_TP2 = 3.5   # 1:3.5 (كان 3.0)
ATR_TP3 = 6.0   # 1:6   (كان 5.0)

def syria_now():
    return datetime.now(timezone.utc) + timedelta(hours=3)

def syria_time_str():
    return syria_now().strftime("%Y-%m-%d %H:%M") + " (سوريا)"

def in_session():
    now = syria_now()
    if now.weekday() >= 5:  # 5=السبت, 6=الأحد
        return False
    h = now.hour
    return SYRIA_OPEN <= h < SYRIA_CLOSE

def load_data():
    default = {
        "last_signal":None,"last_price":None,
        "last_sl":None,"last_tp1":None,
        "last_tp2":None,"last_time":None,
        "history":[],"total":0,"wins":0,
        "losses":0,"min_score":3,
        "week_signals":0,"week_wins":0,
        "week_trades":[],"last_report_date":None
    }
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE,"r") as f:
                default.update(json.load(f))
    except: pass
    return default

def save_data(data):
    try:
        with open(DATA_FILE,"w") as f:
            json.dump(data,f,ensure_ascii=False,indent=2)
    except Exception as e:
        print("خطا حفظ: "+str(e))

def reset_daily_signal(data):
    if not data.get("last_time"): return data
    try:
        last_dt=datetime.strptime(data["last_time"],"%Y-%m-%d %H:%M")
        last_dt=last_dt.replace(tzinfo=timezone.utc)
        hours=(datetime.now(timezone.utc)-last_dt).total_seconds()/3600
        if hours>15:
            data["last_signal"]=None
            print("تجديد يومي — "+str(round(hours))+" ساعة")
    except: pass
    return data

def check_last_signal(data, price):
    if not data["last_signal"] or not data["last_price"]:
        return data
    sl=data["last_sl"]; tp1=data["last_tp1"]
    tp2=data["last_tp2"]; sig=data["last_signal"]
    is_buy="BUY" in sig; result=None
    if is_buy:
        if price>=tp2:   result="WIN_BIG"
        elif price>=tp1: result="WIN"
        elif price<=sl:  result="LOSS"
    else:
        if price<=tp2:   result="WIN_BIG"
        elif price<=tp1: result="WIN"
        elif price>=sl:  result="LOSS"
    if result:
        data["total"]+=1; data["week_signals"]+=1
        pips=round((price-data["last_price"])/0.1,1) if is_buy else round((data["last_price"]-price)/0.1,1)
        if "WIN" in result:
            data["wins"]+=1; data["week_wins"]+=1
            em="✅ ربح كبير" if result=="WIN_BIG" else "✅ ربح"
        else:
            data["losses"]+=1; em="❌ خسارة"
        wr=round(data["wins"]/data["total"]*100) if data["total"]>0 else 0
        if data["total"]>=10:
            if wr<50 and data["min_score"]<6: data["min_score"]+=1
            elif wr>70 and data["min_score"]>3: data["min_score"]-=1
        data.setdefault("week_trades",[]).append({
            "sig":sig,"entry":data["last_price"],"exit":price,
            "pips":pips,"result":result
        })
        send_telegram(em+" نتيجة الصفقة السابقة\n"
            "النوع: "+sig+"\nالسعر: $"+str(round(price,2))+"\n"
            "النقاط: "+("+" if pips>=0 else "")+str(pips)+"\n"
            "الاجمالي: "+str(data["wins"])+"W/"
            +str(data["losses"])+"L | "+str(wr)+"%")
        data["last_signal"]=None
    return data

def check_weekly_report(data):
    now=syria_now()
    if now.weekday()!=5:
        return data
    today_str=now.strftime("%Y-%m-%d")
    if data.get("last_report_date")==today_str:
        return data
    trades=data.get("week_trades",[])
    t=len(trades)
    w=sum(1 for x in trades if "WIN" in x["result"])
    l=t-w
    wr=round(w/t*100) if t>0 else 0
    lines=["📊 التقرير الأسبوعي (آخر 5 أيام)\n"]
    if trades:
        for i,tr in enumerate(trades,1):
            emj="✅" if "WIN" in tr["result"] else "❌"
            sgn="+" if tr["pips"]>=0 else ""
            lines.append(str(i)+") "+tr["sig"]+" "+emj+" "+sgn+str(tr["pips"])+" نقطة\n")
    else:
        lines.append("لا صفقات هذا الأسبوع\n")
    lines.append("\nالإجمالي: "+str(t)+" | رابحة: "+str(w)+" | خاسرة: "+str(l)
                 +"\nنسبة النجاح: "+str(wr)+"%\nالحد التكيفي: "+str(data["min_score"])+"/8")
    send_telegram("".join(lines))
    data["week_trades"]=[]
    data["week_signals"]=0; data["week_wins"]=0
    data["last_report_date"]=today_str
    return data

def send_telegram(text):
    url="https://api.telegram.org/bot"+BOT_TOKEN+"/sendMessage"
    try:
        r=requests.post(url,data={"chat_id":CHAT_ID,"text":text},timeout=10)
        return r.json().get("ok",False)
    except Exception as e:
        print("خطا ارسال: "+str(e)); return False

# ── XAUUSD=X أولاً (سعر فوري = نفس MT5) ──
def get_data(interval="15m", days="5d"):
    try:
        tf = {"15m":"15min","1h":"1h","1d":"1day"}.get(interval, "15min")
        url = f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval={tf}&outputsize=60&apikey=79e9b614595f44d3aa03a0be47e19ae6"
        r = requests.get(url, timeout=10)
        data = r.json()
        vals = data.get("values", [])
        if not vals:
            print("لا بيانات من Twelve Data: " + str(data))
            return None, None, None, None
        vals = vals[::-1]
        closes = [float(x["close"]) for x in vals]
        highs  = [float(x["high"])  for x in vals]
        lows   = [float(x["low"])   for x in vals]
        opens  = [float(x["open"])  for x in vals]
        mn = min(len(closes), len(highs), len(lows), len(opens))
        if mn >= 30:
            return closes[:mn], highs[:mn], lows[:mn], opens[:mn]
        return None, None, None, None
    except Exception as e:
        print("خطأ Twelve Data: " + str(e))
        return None, None, None, None


def ema(prices,n):
    if len(prices)<n: return prices[-1]
    k=2/(n+1); e=sum(prices[:n])/n
    for p in prices[n:]: e=p*k+e*(1-k)
    return round(e,2)

def rsi(closes,n=14):
    if len(closes)<n+1: return 50.0
    d=[closes[i]-closes[i-1] for i in range(1,len(closes))]
    ag=sum(max(x,0) for x in d[-n:])/n
    al=sum(max(-x,0) for x in d[-n:])/n
    return round(100-100/(1+ag/al),2) if al else 100.0

def calc_atr(highs,lows,closes,n=14):
    mn=min(len(highs),len(lows),len(closes))
    trs=[max(highs[i]-lows[i],
             abs(highs[i]-closes[i-1]),
             abs(lows[i]-closes[i-1]))
         for i in range(1,mn)]
    return round(sum(trs[-n:])/n,2) if len(trs)>=n else 15.0

def wave_trend(closes,highs,lows,n1=10,n2=21):
    mn=min(len(closes),len(highs),len(lows))
    c=closes[-mn:]; h=highs[-mn:]; l=lows[-mn:]
    hlc3=[(h[i]+l[i]+c[i])/3 for i in range(mn)]
    def el(data,n):
        if len(data)<n: return data[:]
        k=2/(n+1); e=sum(data[:n])/n
        res=[0]*(n-1)+[e]
        for v in data[n:]: e=v*k+e*(1-k); res.append(e)
        return res
    esa=el(hlc3,n1)
    de=el([abs(hlc3[i]-esa[i]) for i in range(mn)],n1)
    ci=[(hlc3[i]-esa[i])/(0.015*de[i] if de[i] else 0.0001)
        for i in range(mn)]
    tci=el(ci,n2)
    wt2=[sum(tci[i-3:i+1])/4 if i>=3 else tci[i] for i in range(mn)]
    w1=round(tci[-1],2); w2=round(wt2[-1],2)
    p1=tci[-2] if len(tci)>1 else w1
    p2=wt2[-2] if len(wt2)>1 else w2
    sig="BUY" if (p1<=p2 and w1>w2) else(
        "SELL" if (p1>=p2 and w1<w2) else "NEUTRAL")
    return w1,w2,sig,w1<-53,w1>53

def get_dxy_trend():
    headers={"User-Agent":"Mozilla/5.0"}
    for sym in ["DX-Y.NYB","UUP"]:
        try:
            url=("https://query1.finance.yahoo.com/v8/finance/chart/"
                 +sym+"?interval=1h&range=10d")
            r=requests.get(url,headers=headers,timeout=8)
            q=r.json()["chart"]["result"][0]["indicators"]["quote"][0]
            closes=[x for x in q["close"] if x]
            if len(closes)<20: continue
            if closes[-1]>ema(closes,20):
                return "UP","DXY صاعد (ضغط على الذهب)"
            else:
                return "DOWN","DXY هابط (دعم للذهب)"
        except: pass
    return "NEUTRAL","DXY غير متاح"

def get_d1_trend():
    closes,highs,lows,opens=get_data("1d","60d")
    if closes is None: return "NEUTRAL","D1 غير متاح"
    e20=ema(closes,20)
    e50=ema(closes,50) if len(closes)>=50 else e20
    price=closes[-1]; r=rsi(closes)
    if price>e20>e50 and r>45: return "UP","D1 صاعد"
    elif price<e20<e50 and r<55: return "DOWN","D1 هابط"
    else: return "NEUTRAL","D1 محايد"

def detect_market_regime(closes,highs,lows):
    if len(closes)<20: return "TREND","سوق متحرك"
    hr=max(highs[-20:])-min(highs[-20:])
    a=calc_atr(highs,lows,closes)
    if hr/(a*20)>1.5: return "TREND","سوق في اتجاه واضح"
    else: return "RANGE","سوق جانبي"

def get_h1_trend():
    closes,highs,lows,opens=get_data("1h","15d")
    if closes is None: return "NEUTRAL","H1 غير متاح"
    e20=ema(closes,20); e50=ema(closes,50)
    price=closes[-1]; r=rsi(closes)
    if price>e20>e50 and r>45: return "UP","H1 صاعد"
    elif price<e20<e50 and r<55: return "DOWN","H1 هابط"
    else: return "NEUTRAL","H1 محايد"

def find_key_levels(highs,lows,closes):
    lp=closes[-1]
    res=min([h for h in sorted(highs[-50:],reverse=True)[:3]
             if h>lp],default=None)
    sup=max([l for l in sorted(lows[-50:])[:3]
             if l<lp],default=None)
    return res,sup

def check_near_level(price,level,atr,is_res):
    if level is None: return False,""
    if abs(price-level)<atr*0.5:
        return True,"قريب من "+("مقاومة" if is_res else "دعم")
    return False,""

def check_news():
    try:
        r=requests.get(
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            timeout=8)
        now=datetime.now(timezone.utc)
        kws=["Non-Farm","CPI","FOMC","Fed","Interest Rate",
             "GDP","NFP","Powell"]
        for ev in r.json():
            if ev.get("impact","")!="High": continue
            if ev.get("currency","") not in ["USD","XAU"]: continue
            try:
                et=datetime.fromisoformat(
                    ev.get("date","").replace("Z","+00:00"))
                diff=(et-now).total_seconds()/60
                if -15<=diff<=60:
                    t=ev.get("title","")
                    if any(k.lower() in t.lower() for k in kws):
                        return True,"خبر: "+t
            except: continue
        return False,""
    except: return False,""

def find_swing_points(highs,lows,n=3):
    sh,sl=[],[]
    for i in range(n,len(highs)-n):
        if all(highs[i]>=highs[i-j] and highs[i]>=highs[i+j]
               for j in range(1,n+1)):
            sh.append((i,highs[i]))
        if all(lows[i]<=lows[i-j] and lows[i]<=lows[i+j]
               for j in range(1,n+1)):
            sl.append((i,lows[i]))
    return sh,sl

def detect_bos(closes,highs,lows):
    sh,sl=find_swing_points(highs,lows)
    if not sh or not sl: return "NONE",None
    current=closes[-1]
    if current>sh[-1][1]: return "BOS_BULL",round(sh[-1][1],2)
    if current<sl[-1][1]: return "BOS_BEAR",round(sl[-1][1],2)
    return "NONE",None

def find_order_blocks(closes,highs,lows,opens,atr):
    current=closes[-1]; bull_ob=bear_ob=None
    min_move=atr*1.5; lb=min(30,len(closes)-3)
    for i in range(len(closes)-3,len(closes)-lb,-1):
        if i<1: break
        if opens[i]>closes[i]:
            if (i+2<len(closes) and
                    closes[i+2]-closes[i]>=min_move and
                    closes[i+1]>opens[i+1] and
                    closes[i+2]>opens[i+2]):
                if bull_ob is None:
                    ol,oh=round(lows[i],2),round(highs[i],2)
                    if current>=ol: bull_ob=(ol,oh)
        if opens[i]<closes[i]:
            if (i+2<len(closes) and
                    closes[i]-closes[i+2]>=min_move and
                    closes[i+1]<opens[i+1] and
                    closes[i+2]<opens[i+2]):
                if bear_ob is None:
                    ol,oh=round(lows[i],2),round(highs[i],2)
                    if current<=oh: bear_ob=(ol,oh)
    return bull_ob,bear_ob

def find_fvg(highs,lows,closes):
    current=closes[-1]; bull_fvgs=[]; bear_fvgs=[]
    start=max(0,len(closes)-25)
    for i in range(start,len(closes)-2):
        if lows[i+2]>highs[i]:
            fl,fh=round(highs[i],2),round(lows[i+2],2)
            if current>fh: bull_fvgs.append((fl,fh))
        if highs[i+2]<lows[i]:
            fl,fh=round(highs[i+2],2),round(lows[i],2)
            if current<fl: bear_fvgs.append((fl,fh))
    return bull_fvgs,bear_fvgs

def check_liquidity_sweep(closes,highs,lows,atr):
    tol=atr*0.3; rh=highs[-20:]; rl=lows[-20:]
    current=closes[-1]
    for i in range(len(rl)-3):
        for j in range(i+1,len(rl)-1):
            if abs(rl[i]-rl[j])<tol:
                level=min(rl[i],rl[j])
                if min(lows[-3:])<level and current>level:
                    return "BULL_SWEEP",round(level,2)
    for i in range(len(rh)-3):
        for j in range(i+1,len(rh)-1):
            if abs(rh[i]-rh[j])<tol:
                level=max(rh[i],rh[j])
                if max(highs[-3:])>level and current<level:
                    return "BEAR_SWEEP",round(level,2)
    return "NONE",None

def analyze_smc(closes,highs,lows,opens,atr,is_buy):
    bos_type,bos_level=detect_bos(closes,highs,lows)
    bull_ob,bear_ob=find_order_blocks(closes,highs,lows,opens,atr)
    bull_fvgs,bear_fvgs=find_fvg(highs,lows,closes)
    liq_type,liq_level=check_liquidity_sweep(closes,highs,lows,atr)
    current=closes[-1]; smc_score=0; smc_notes=[]
    ob_sl=None

    if is_buy and bos_type=="BOS_BULL":
        smc_score+=2; smc_notes.append("BOS صاعد $"+str(bos_level))
    elif not is_buy and bos_type=="BOS_BEAR":
        smc_score+=2; smc_notes.append("BOS هابط $"+str(bos_level))
    else:
        smc_notes.append("لا BOS واضح")

    if is_buy and bull_ob:
        ol,oh=bull_ob
        if ol<=current<=oh*1.005:
            smc_score+=3
            smc_notes.append("داخل OB شراء $"+str(ol)+"—$"+str(oh))
            ob_sl=round(ol-atr*0.3,2)
        elif current>oh:
            smc_score+=1
            smc_notes.append("OB شراء: $"+str(ol)+"—$"+str(oh))
    elif not is_buy and bear_ob:
        ol,oh=bear_ob
        if ol*0.995<=current<=oh:
            smc_score+=3
            smc_notes.append("داخل OB بيع $"+str(ol)+"—$"+str(oh))
            ob_sl=round(oh+atr*0.3,2)
        elif current<ol:
            smc_score+=1
            smc_notes.append("OB بيع: $"+str(ol)+"—$"+str(oh))

    if is_buy and bull_fvgs:
        fvg=bull_fvgs[-1]
        if abs(current-fvg[0])<atr*3:
            smc_score+=1
            smc_notes.append("FVG صاعد $"+str(fvg[0])+"—$"+str(fvg[1]))
    elif not is_buy and bear_fvgs:
        fvg=bear_fvgs[-1]
        if abs(current-fvg[1])<atr*3:
            smc_score+=1
            smc_notes.append("FVG هابط $"+str(fvg[0])+"—$"+str(fvg[1]))

    if is_buy and liq_type=="BULL_SWEEP":
        smc_score+=2
        smc_notes.append("اصطياد سيولة صاعد $"+str(liq_level))
    elif not is_buy and liq_type=="BEAR_SWEEP":
        smc_score+=2
        smc_notes.append("اصطياد سيولة هابط $"+str(liq_level))

    return {"smc_score":smc_score,"smc_notes":smc_notes,
            "bos_type":bos_type,"ob_sl":ob_sl}

def analyze(closes,highs,lows,opens,min_score):
    price=round(closes[-1],2)
    r=rsi(closes); e20=ema(closes,20); e50=ema(closes,50)
    macd=round(ema(closes,12)-ema(closes,26),2)
    a=calc_atr(highs,lows,closes)
    wt1,wt2,wt_sig,oversold,overbought=wave_trend(closes,highs,lows)
    score,reasons=0,[]

    if price>e20>e50:
        score+=2; reasons.append("فوق EMA20/50 صاعد")
    elif price<e20<e50:
        score-=2; reasons.append("تحت EMA20/50 هابط")
    else: reasons.append("EMA محايد")
    if len(closes)>=200:
        e200=ema(closes,200)
        if price>e200: score+=1; reasons.append("فوق EMA200 صاعد")
        else: score-=1; reasons.append("تحت EMA200 هابط")
    if r<30:   score+=2; reasons.append("RSI="+str(r)+" ذروة بيع")
    elif r>70: score-=2; reasons.append("RSI="+str(r)+" ذروة شراء")
    else:      reasons.append("RSI="+str(r)+" محايد")
    if macd>0: score+=1; reasons.append("MACD="+str(macd)+" صاعد")
    else:      score-=1; reasons.append("MACD="+str(macd)+" هابط")
    wz=" ذروة بيع" if oversold else(" ذروة شراء" if overbought else "")
    if wt_sig=="BUY":    score+=2; reasons.append("WaveTrend صاعد"+wz)
    elif wt_sig=="SELL": score-=2; reasons.append("WaveTrend هابط"+wz)
    else: reasons.append("WaveTrend="+str(wt1)+" محايد"+wz)

    if   score>=5:          st,stx,dr,em="BUY_S","شراء قوي جدا","صاعد قوي جدا","🟢"
    elif score>=min_score:  st,stx,dr,em="BUY_W","شراء","صاعد","🔵"
    elif score<=-5:         st,stx,dr,em="SELL_S","بيع قوي جدا","هابط قوي جدا","🔴"
    elif score<=-min_score: st,stx,dr,em="SELL_W","بيع","هابط","🟠"
    else:                   st,stx,dr,em="WAIT","انتظار","جانبي","⚪"

    buy="BUY" in st
    zone=round(a*0.3,2)
    lv={
        "entry":price,
        "entry_zone_low" :round(price-zone if buy else price-zone,2),
        "entry_zone_high":round(price+zone if buy else price+zone,2),
        "sl" :round(price-a*ATR_SL  if buy else price+a*ATR_SL, 2),
        "tp1":round(price+a*ATR_TP1 if buy else price-a*ATR_TP1,2),
        "tp2":round(price+a*ATR_TP2 if buy else price-a*ATR_TP2,2),
        "tp3":round(price+a*ATR_TP3 if buy else price-a*ATR_TP3,2)
    }
    return dict(st=st,stx=stx,dr=dr,emoji=em,score=score,
                rsi=r,macd=macd,e20=e20,e50=e50,atr=a,
                wt1=wt1,wt_sig=wt_sig,price=price,
                lv=lv,reasons=reasons)

def build_msg(r,smc,h1n,dxy_n,d1_n,regime_n,filters,wr,total,min_sc):
    lv=r["lv"]
    rs="\n".join("- "+x for x in r["reasons"])
    sn="\n".join("- "+x for x in smc["smc_notes"])
    now=syria_time_str()
    arrow="↑" if r["wt_sig"]=="BUY" else("↓" if r["wt_sig"]=="SELL" else"-")
    tbar="".join(["█" if i<abs(r["score"]) else "░" for i in range(8)])
    sbar="".join(["█" if i<smc["smc_score"] else "░" for i in range(8)])
    sl_final=smc["ob_sl"] if smc["ob_sl"] else lv["sl"]
    sl_note="(OB)" if smc["ob_sl"] else "(ATR)"
    perf=" | "+str(wr)+"%" if total>0 else ""

    # نسبة R:R
    rr=round(abs(lv["tp1"]-lv["entry"])/abs(lv["sl"]-lv["entry"]),1) if lv["sl"]!=lv["entry"] else 0

    return (
        r["emoji"]+" الذهب XAUUSD M15 — إشارة\n"
        "========================\n"
        "السعر:    $"+str(r["price"])+"\n"
        "الاتجاه:  "+r["dr"]+"\n"
        "الاشارة:  "+r["stx"]+"\n"
        "فني: ["+tbar+"] "+str(abs(r["score"]))+"/8\n"
        "SMC: ["+sbar+"] "+str(smc["smc_score"])+"/8\n"
        "فلاتر: "+str(filters)+"/3"+perf+"\n\n"
        "السياق:\n"
        "- "+h1n+" | "+d1_n+"\n"
        "- "+dxy_n+"\n"
        "- "+regime_n+"\n\n"
        "فني:\n"+rs+"\n\n"
        "SMC:\n"+sn+"\n\n"
        "========================\n"
        "منطقة الدخول (Spot):\n"
        "$"+str(lv["entry_zone_low"])+" — $"+str(lv["entry_zone_high"])+"\n"
        "وقف الخسارة: $"+str(sl_final)+" "+sl_note+"\n"
        "TP1 (R:R=1:"+str(rr)+"): $"+str(lv["tp1"])+"\n"
        "TP2: $"+str(lv["tp2"])+"\n"
        "TP3: $"+str(lv["tp3"])+"\n\n"
        "⚠️ استخدم سعر MT5 للدخول\n"
        "الحد: "+str(min_sc)+"/8\n"
        "الوقت: "+now
    )

def job():
    data=load_data()
    if syria_now().weekday()==5:
        print("السبت — تقرير اسبوعي فقط")
        data=check_weekly_report(data)
        save_data(data)
        return
    if not in_session():
        print("خارج ساعات العمل")
        return
    closes,highs,lows,opens=get_data("15m","5d")
    if closes is None:
        print("فشل جلب البيانات"); return
    data=reset_daily_signal(data)
    data=check_last_signal(data,closes[-1])
    min_sc=data["min_score"]
    r=analyze(closes,highs,lows,opens,min_sc)
    if r["st"]=="WAIT":
        print("لا اشارة | Score="+str(r["score"])); save_data(data); return
    if r["st"]==data["last_signal"]:
        print("نفس الاشارة"); save_data(data); return
    is_buy="BUY" in r["st"]
    filters=0; blocked=False; block_reason=""
    h1_dir,h1_note=get_h1_trend()
    if h1_dir=="UP" and is_buy:         filters+=1
    elif h1_dir=="DOWN" and not is_buy: filters+=1
    elif h1_dir=="NEUTRAL":             filters+=1
    else: blocked=True; block_reason="عكس H1"
    if not blocked:
        res,sup=find_key_levels(highs,lows,closes)
        nr,_=check_near_level(r["price"],res,r["atr"],True)
        ns,_=check_near_level(r["price"],sup,r["atr"],False)
        if is_buy and nr:       blocked=True; block_reason="مقاومة"
        elif not is_buy and ns: blocked=True; block_reason="دعم"
        else: filters+=1
    if not blocked:
        nd,nn=check_news()
        if nd: blocked=True; block_reason=nn
        else: filters+=1
    if blocked:
        print("مرفوضة: "+block_reason); save_data(data); return
    dxy_dir,dxy_note=get_dxy_trend()
    d1_dir,d1_note=get_d1_trend()
    regime,regime_note=detect_market_regime(closes,highs,lows)
    smc=analyze_smc(closes,highs,lows,opens,r["atr"],is_buy)
    total=data["total"]
    wr=round(data["wins"]/total*100) if total>0 else 0
    msg=build_msg(r,smc,h1_note,dxy_note,d1_note,
                  regime_note,filters,wr,total,min_sc)
    if send_telegram(msg):
        print("✅ "+r["stx"]+" @ $"+str(r["price"]))
        data["last_signal"]=r["st"]
        data["last_price"]=r["price"]
        data["last_sl"]=smc["ob_sl"] if smc["ob_sl"] else r["lv"]["sl"]
        data["last_tp1"]=r["lv"]["tp1"]
        data["last_tp2"]=r["lv"]["tp2"]
        data["last_time"]=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    save_data(data)

# ════════════════════════════════════════
# للتشغيل على PythonAnywhere Web App
# ════════════════════════════════════════
class KeepAlive(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Gold Bot Running!")
    def log_message(self,*a): pass

def run_server():
    HTTPServer(('0.0.0.0',8080),KeepAlive).serve_forever()

def run_bot():
    while True:
        try: job()
        except Exception as e: print("خطا: "+str(e))
        time.sleep(300)

# ════════════════════════════════════════
if __name__ == "__main__":
    print("بوت الذهب v10")
    print(syria_time_str())
    job()
