import requests, json, os
from datetime import datetime, timezone

BOT_TOKEN    = "8901717984:AAFaG9H3FNiIgfa2AGRVU8q7nTdn0kCoK4s"
CHAT_ID      = "888229115"
LDN_O, LDN_C = 8, 16
NY_O,  NY_C  = 13, 21
ATR_SL=1.5; ATR_TP1=1.5; ATR_TP2=3.0; ATR_TP3=5.0
DATA_FILE    = "data.json"

# ════════════════════════════════════════
# البيانات المستمرة
# ════════════════════════════════════════
def load_data():
    default = {
        "last_signal":None,"last_price":None,
        "last_sl":None,"last_tp1":None,
        "last_tp2":None,"last_time":None,
        "history":[],"total":0,"wins":0,
        "losses":0,"min_score":3,
        "week_signals":0,"week_wins":0
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

def check_last_signal(data, price):
    if not data["last_signal"] or not data["last_price"]:
        return data
    sl=data["last_sl"]; tp1=data["last_tp1"]
    tp2=data["last_tp2"]; sig=data["last_signal"]
    is_buy="BUY" in sig; result=None
    if is_buy:
        if price>=tp2: result="WIN_BIG"
        elif price>=tp1: result="WIN"
        elif price<=sl: result="LOSS"
    else:
        if price<=tp2: result="WIN_BIG"
        elif price<=tp1: result="WIN"
        elif price>=sl: result="LOSS"
    if result:
        data["total"]+=1; data["week_signals"]+=1
        if "WIN" in result:
            data["wins"]+=1; data["week_wins"]+=1
            em="✅ ربح كبير" if result=="WIN_BIG" else "✅ ربح"
        else:
            data["losses"]+=1; em="❌ خسارة"
        wr=round(data["wins"]/data["total"]*100) if data["total"]>0 else 0
        if data["total"]>=10:
            if wr<50 and data["min_score"]<5: data["min_score"]+=1
            elif wr>70 and data["min_score"]>3: data["min_score"]-=1
        send_telegram(em+" نتيجة الصفقة السابقة\n"
            "النوع: "+sig+"\nالسعر: $"+str(round(price,2))+"\n"
            "الاجمالي: "+str(data["wins"])+"W/"+str(data["losses"])+"L"
            " | "+str(wr)+"%")
        data["last_signal"]=None
    return data

def check_weekly_report(data):
    now=datetime.now(timezone.utc)
    if now.weekday()==4 and 18<=now.hour<=20:
        t=data["total"]; w=data["wins"]; l=data["losses"]
        wr=round(w/t*100) if t>0 else 0
        bar="█"*int(wr/10)+"░"*(10-int(wr/10))
        send_telegram("📊 تقرير الأسبوع\n"
            "========================\n"
            "الكلي: "+str(t)+" | ربح: "+str(w)+" | خسارة: "+str(l)+"\n"
            "نسبة النجاح: "+str(wr)+"%\n["+bar+"]\n"
            "هذا الأسبوع: "+str(data["week_signals"])+" إشارة | "
            +str(data["week_wins"])+" ربح\n"
            "الحد التكيفي: "+str(data["min_score"])+"/8")
        data["week_signals"]=0; data["week_wins"]=0

# ════════════════════════════════════════
# إرسال + جلسة
# ════════════════════════════════════════
def send_telegram(text):
    url="https://api.telegram.org/bot"+BOT_TOKEN+"/sendMessage"
    try:
        r=requests.post(url,data={"chat_id":CHAT_ID,"text":text},timeout=10)
        return r.json().get("ok",False)
    except Exception as e:
        print("خطا ارسال: "+str(e)); return False

def in_session():
    h=datetime.now(timezone.utc).hour
    return (LDN_O<=h<LDN_C) or (NY_O<=h<NY_C)

# ════════════════════════════════════════
# جلب البيانات (مع Open)
# ════════════════════════════════════════
def get_data(interval="15m", days="5d"):
    headers={"User-Agent":"Mozilla/5.0"}
    for sym in ["GC=F","XAUUSD=X"]:
        try:
            url=("https://query1.finance.yahoo.com/v8/finance/chart/"
                 +sym+"?interval="+interval+"&range="+days)
            r=requests.get(url,headers=headers,timeout=10)
            q=r.json()["chart"]["result"][0]["indicators"]["quote"][0]
            closes=[x for x in q["close"] if x]
            highs =[x for x in q["high"]  if x]
            lows  =[x for x in q["low"]   if x]
            opens =[x for x in q["open"]  if x]
            mn=min(len(closes),len(highs),len(lows),len(opens))
            if mn>=30:
                return closes[:mn],highs[:mn],lows[:mn],opens[:mn]
        except Exception as e:
            print("خطا "+interval+": "+str(e))
    return None,None,None,None

# ════════════════════════════════════════
# المؤشرات الكلاسيكية
# ════════════════════════════════════════
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
    ci=[(hlc3[i]-esa[i])/(0.015*de[i] if de[i] else 0.0001) for i in range(mn)]
    tci=el(ci,n2)
    wt2=[sum(tci[i-3:i+1])/4 if i>=3 else tci[i] for i in range(mn)]
    w1=round(tci[-1],2); w2=round(wt2[-1],2)
    p1=tci[-2] if len(tci)>1 else w1
    p2=wt2[-2] if len(wt2)>1 else w2
    sig="BUY" if (p1<=p2 and w1>w2) else("SELL" if (p1>=p2 and w1<w2) else "NEUTRAL")
    return w1,w2,sig,w1<-53,w1>53

# ════════════════════════════════════════
# المستوى 1 — DXY + D1 + طبيعة السوق
# ════════════════════════════════════════
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
            e20=ema(closes,20)
            if closes[-1]>e20: return "UP","DXY صاعد (ضغط على الذهب)"
            else: return "DOWN","DXY هابط (دعم للذهب)"
        except: pass
    return "NEUTRAL","DXY غير متاح"

def get_d1_trend():
    closes,highs,lows,opens=get_data("1d","60d")
    if closes is None: return "NEUTRAL","D1 غير متاح"
    e20=ema(closes,20); e50=ema(closes,50) if len(closes)>=50 else e20
    price=closes[-1]; r=rsi(closes)
    if price>e20>e50 and r>45: return "UP","D1 صاعد"
    elif price<e20<e50 and r<55: return "DOWN","D1 هابط"
    else: return "NEUTRAL","D1 محايد"

def detect_market_regime(closes,highs,lows):
    if len(closes)<20: return "TREND","سوق متحرك"
    hr=max(highs[-20:])-min(highs[-20:])
    a=calc_atr(highs,lows,closes)
    return ("TREND","سوق في اتجاه واضح") if hr/(a*20)>1.5 else ("RANGE","سوق جانبي")

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
    res=min([h for h in sorted(highs[-50:],reverse=True)[:3] if h>lp],default=None)
    sup=max([l for l in sorted(lows[-50:])[:3] if l<lp],default=None)
    return res,sup

def check_near_level(price,level,atr,is_res):
    if level is None: return False,""
    if abs(price-level)<atr*0.5:
        return True,"قريب من "+("مقاومة" if is_res else "دعم")
    return False,""

def check_news():
    try:
        r=requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",timeout=8)
        now=datetime.now(timezone.utc)
        kws=["Non-Farm","CPI","FOMC","Fed","Interest Rate","GDP","NFP","Powell"]
        for ev in r.json():
            if ev.get("impact","")!="High": continue
            if ev.get("currency","") not in ["USD","XAU"]: continue
            try:
                et=datetime.fromisoformat(ev.get("date","").replace("Z","+00:00"))
                diff=(et-now).total_seconds()/60
                if -15<=diff<=60:
                    t=ev.get("title","")
                    if any(k.lower() in t.lower() for k in kws):
                        return True,"خبر: "+t
            except: continue
        return False,""
    except: return False,""

# ════════════════════════════════════════
# SMC — Smart Money Concepts
# ════════════════════════════════════════
def find_swing_points(highs, lows, n=3):
    sh, sl = [], []
    for i in range(n, len(highs)-n):
        if all(highs[i]>=highs[i-j] and highs[i]>=highs[i+j]
               for j in range(1,n+1)):
            sh.append((i, highs[i]))
        if all(lows[i]<=lows[i-j] and lows[i]<=lows[i+j]
               for j in range(1,n+1)):
            sl.append((i, lows[i]))
    return sh, sl

def detect_bos(closes, highs, lows):
    sh, sl = find_swing_points(highs, lows)
    if not sh or not sl: return "NONE", None
    current = closes[-1]
    if current > sh[-1][1]: return "BOS_BULL", round(sh[-1][1],2)
    if current < sl[-1][1]: return "BOS_BEAR", round(sl[-1][1],2)
    return "NONE", None

def find_order_blocks(closes, highs, lows, opens, atr):
    current = closes[-1]
    bull_ob = bear_ob = None
    min_move = atr * 1.5
    lb = min(30, len(closes)-3)
    for i in range(len(closes)-3, len(closes)-lb, -1):
        if i < 1: break
        # Bullish OB
        if opens[i] > closes[i]:
            move = closes[min(i+2,len(closes)-1)] - closes[i]
            if (move >= min_move and i+2 < len(closes)
                    and closes[i+1]>opens[i+1]
                    and closes[i+2]>opens[i+2]):
                if bull_ob is None:
                    ol,oh = round(lows[i],2), round(highs[i],2)
                    if current >= ol:
                        bull_ob = (ol, oh)
        # Bearish OB
        if opens[i] < closes[i]:
            move = closes[i] - closes[min(i+2,len(closes)-1)]
            if (move >= min_move and i+2 < len(closes)
                    and closes[i+1]<opens[i+1]
                    and closes[i+2]<opens[i+2]):
                if bear_ob is None:
                    ol,oh = round(lows[i],2), round(highs[i],2)
                    if current <= oh:
                        bear_ob = (ol, oh)
    return bull_ob, bear_ob

def find_fvg(highs, lows, closes):
    current = closes[-1]
    bull_fvgs = []; bear_fvgs = []
    start = max(0, len(closes)-25)
    for i in range(start, len(closes)-2):
        if lows[i+2] > highs[i]:
            fl,fh = round(highs[i],2), round(lows[i+2],2)
            if current > fh: bull_fvgs.append((fl,fh))
        if highs[i+2] < lows[i]:
            fl,fh = round(highs[i+2],2), round(lows[i],2)
            if current < fl: bear_fvgs.append((fl,fh))
    return bull_fvgs, bear_fvgs

def check_liquidity_sweep(closes, highs, lows, atr):
    tol = atr * 0.3
    rh = highs[-20:]; rl = lows[-20:]
    current = closes[-1]
    for i in range(len(rl)-3):
        for j in range(i+1, len(rl)-1):
            if abs(rl[i]-rl[j]) < tol:
                level = min(rl[i],rl[j])
                if min(lows[-3:]) < level and current > level:
                    return "BULL_SWEEP", round(level,2)
    for i in range(len(rh)-3):
        for j in range(i+1, len(rh)-1):
            if abs(rh[i]-rh[j]) < tol:
                level = max(rh[i],rh[j])
                if max(highs[-3:]) > level and current < level:
                    return "BEAR_SWEEP", round(level,2)
    return "NONE", None

def analyze_smc(closes, highs, lows, opens, atr, is_buy):
    bos_type,bos_level = detect_bos(closes,highs,lows)
    bull_ob,bear_ob    = find_order_blocks(closes,highs,lows,opens,atr)
    bull_fvgs,bear_fvgs = find_fvg(highs,lows,closes)
    liq_type,liq_level = check_liquidity_sweep(closes,highs,lows,atr)
    current = closes[-1]
    smc_score = 0; smc_notes = []
    ob_sl = None; active_ob = None; nearest_fvg = None

    # BOS
    if is_buy and bos_type=="BOS_BULL":
        smc_score+=2; smc_notes.append("BOS صاعد عند $"+str(bos_level))
    elif not is_buy and bos_type=="BOS_BEAR":
        smc_score+=2; smc_notes.append("BOS هابط عند $"+str(bos_level))
    else:
        smc_notes.append("لا BOS واضح — اتجاه غير مؤكد هيكلياً")

    # Order Block
    if is_buy and bull_ob:
        ol,oh = bull_ob
        if ol <= current <= oh*1.005:
            smc_score+=3
            smc_notes.append("داخل OB شراء: $"+str(ol)+" — $"+str(oh)+" ← دخول مثالي")
            ob_sl = round(ol - atr*0.3, 2)
            active_ob = bull_ob
        elif current > oh:
            smc_score+=1
            smc_notes.append("OB شراء أسفل السعر: $"+str(ol)+" — $"+str(oh))
            active_ob = bull_ob
    elif not is_buy and bear_ob:
        ol,oh = bear_ob
        if ol*0.995 <= current <= oh:
            smc_score+=3
            smc_notes.append("داخل OB بيع: $"+str(ol)+" — $"+str(oh)+" ← دخول مثالي")
            ob_sl = round(oh + atr*0.3, 2)
            active_ob = bear_ob
        elif current < ol:
            smc_score+=1
            smc_notes.append("OB بيع فوق السعر: $"+str(ol)+" — $"+str(oh))
            active_ob = bear_ob

    # FVG
    if is_buy and bull_fvgs:
        fvg = bull_fvgs[-1]
        if abs(current-fvg[0]) < atr*3:
            smc_score+=1
            smc_notes.append("FVG صاعد قريب: $"+str(fvg[0])+" — $"+str(fvg[1]))
            nearest_fvg = fvg
    elif not is_buy and bear_fvgs:
        fvg = bear_fvgs[-1]
        if abs(current-fvg[1]) < atr*3:
            smc_score+=1
            smc_notes.append("FVG هابط قريب: $"+str(fvg[0])+" — $"+str(fvg[1]))
            nearest_fvg = fvg

    # Liquidity Sweep
    if is_buy and liq_type=="BULL_SWEEP":
        smc_score+=2
        smc_notes.append("اصطياد سيولة صاعد عند $"+str(liq_level)+" ← انعكاس مؤكد")
    elif not is_buy and liq_type=="BEAR_SWEEP":
        smc_score+=2
        smc_notes.append("اصطياد سيولة هابط عند $"+str(liq_level)+" ← انعكاس مؤكد")

    return {
        "smc_score":smc_score,"smc_notes":smc_notes,
        "bos_type":bos_type,"bos_level":bos_level,
        "active_ob":active_ob,"ob_sl":ob_sl,
        "nearest_fvg":nearest_fvg,
        "liq_type":liq_type,"liq_level":liq_level
    }

# ════════════════════════════════════════
# التحليل الرئيسي
# ════════════════════════════════════════
def analyze(closes,highs,lows,opens,min_score):
    price=round(closes[-1],2)
    r=rsi(closes); e20=ema(closes,20); e50=ema(closes,50)
    macd=round(ema(closes,12)-ema(closes,26),2)
    a=calc_atr(highs,lows,closes)
    wt1,wt2,wt_sig,oversold,overbought=wave_trend(closes,highs,lows)
    score,reasons=0,[]

    if price>e20>e50: score+=2; reasons.append("السعر فوق EMA20/50 صاعد")
    elif price<e20<e50: score-=2; reasons.append("السعر تحت EMA20/50 هابط")
    else: reasons.append("EMA محايد")
    if len(closes)>=200:
        e200=ema(closes,200)
        if price>e200: score+=1; reasons.append("فوق EMA200 صاعد طويل")
        else: score-=1; reasons.append("تحت EMA200 هابط طويل")
    if r<30:   score+=2; reasons.append("RSI="+str(r)+" ذروة بيع")
    elif r>70: score-=2; reasons.append("RSI="+str(r)+" ذروة شراء")
    else:      reasons.append("RSI="+str(r)+" محايد")
    if macd>0: score+=1; reasons.append("MACD="+str(macd)+" صاعد")
    else:      score-=1; reasons.append("MACD="+str(macd)+" هابط")
    wz=" ذروة بيع" if oversold else(" ذروة شراء" if overbought else "")
    if wt_sig=="BUY":  score+=2; reasons.append("WaveTrend تقاطع صاعد"+wz)
    elif wt_sig=="SELL": score-=2; reasons.append("WaveTrend تقاطع هابط"+wz)
    else: reasons.append("WaveTrend="+str(wt1)+" محايد"+wz)

    if   score>=5: st,stx,dr,em="BUY_S","شراء قوي جدا","صاعد قوي جدا","🟢"
    elif score>=min_score: st,stx,dr,em="BUY_W","شراء","صاعد","🔵"
    elif score<=-5: st,stx,dr,em="SELL_S","بيع قوي جدا","هابط قوي جدا","🔴"
    elif score<=-min_score: st,stx,dr,em="SELL_W","بيع","هابط","🟠"
    else: st,stx,dr,em="WAIT","انتظار","جانبي","⚪"

    buy="BUY" in st
    lv={"entry":price,
        "sl" :round(price-a*ATR_SL  if buy else price+a*ATR_SL, 2),
        "tp1":round(price+a*ATR_TP1 if buy else price-a*ATR_TP1,2),
        "tp2":round(price+a*ATR_TP2 if buy else price-a*ATR_TP2,2),
        "tp3":round(price+a*ATR_TP3 if buy else price-a*ATR_TP3,2)}
    return dict(st=st,stx=stx,dr=dr,emoji=em,score=score,
                rsi=r,macd=macd,e20=e20,e50=e50,atr=a,
                wt1=wt1,wt_sig=wt_sig,price=price,lv=lv,reasons=reasons)

def build_msg(r,smc,h1n,dxy_n,d1_n,regime_n,filters,wr,total,min_sc):
    lv=r["lv"]
    rs="\n".join("- "+x for x in r["reasons"])
    sn="\n".join("• "+x for x in smc["smc_notes"])
    now=datetime.now().strftime("%Y-%m-%d %H:%M")
    arrow="↑" if r["wt_sig"]=="BUY" else("↓" if r["wt_sig"]=="SELL" else"-")
    tbar="".join(["█" if i<abs(r["score"]) else "░" for i in range(8)])
    sbar="".join(["█" if i<smc["smc_score"] else "░" for i in range(8)])

    # SL: استخدم OB إذا متاح، وإلا ATR
    sl_final = smc["ob_sl"] if smc["ob_sl"] else lv["sl"]
    sl_note  = "(تحت OB)" if smc["ob_sl"] else "(ATR)"

    perf=""
    if total>0:
        perf=" | أداء: "+str(wr)+"%"

    return (
        r["emoji"]+" تحليل الذهب XAUUSD M15\n"
        "================================\n"
        "السعر:    $"+str(r["price"])+"\n"
        "الاتجاه:  "+r["dr"]+"\n"
        "الاشارة:  "+r["stx"]+"\n"
        "فني:  ["+tbar+"] "+str(abs(r["score"]))+"/8\n"
        "SMC:  ["+sbar+"] "+str(smc["smc_score"])+"/8\n"
        "الفلاتر: "+str(filters)+"/3"+perf+"\n\n"
        "السياق:\n"
        "• "+h1n+" | "+d1_n+"\n"
        "• "+dxy_n+"\n"
        "• "+regime_n+"\n\n"
        "التحليل الفني:\n"+rs+"\n\n"
        "================================\n"
        "🏛 Smart Money (SMC):\n"+sn+"\n\n"
        "================================\n"
        "مستويات التداول:\n"
        "الدخول:      $"+str(lv["entry"])+"\n"
        "وقف الخسارة: $"+str(sl_final)+" "+sl_note+"\n"
        "TP1: $"+str(lv["tp1"])+"\n"
        "TP2: $"+str(lv["tp2"])+"\n"
        "TP3: $"+str(lv["tp3"])+"\n\n"
        "الحد التكيفي: "+str(min_sc)+"/8\n"
        "الوقت: "+now
    )

# ════════════════════════════════════════
# الدالة الرئيسية
# ════════════════════════════════════════
def job():
    data=load_data()
    if not in_session():
        print("خارج جلسة التداول"); return

    closes,highs,lows,opens=get_data("15m","5d")
    if closes is None:
        print("فشل جلب M15"); return

    data=check_last_signal(data,closes[-1])
    check_weekly_report(data)

    min_sc=data["min_score"]
    r=analyze(closes,highs,lows,opens,min_sc)

    if r["st"]=="WAIT":
        print("لا اشارة | Score="+str(r["score"]))
        save_data(data); return

    if r["st"]==data["last_signal"]:
        print("نفس الاشارة - تخطي")
        save_data(data); return

    is_buy="BUY" in r["st"]
    filters=0; blocked=False; block_reason=""

    h1_dir,h1_note=get_h1_trend()
    if h1_dir=="UP" and is_buy:       filters+=1
    elif h1_dir=="DOWN" and not is_buy: filters+=1
    elif h1_dir=="NEUTRAL":            filters+=1
    else: blocked=True; block_reason="عكس H1"

    if not blocked:
        res,sup=find_key_levels(highs,lows,closes)
        nr,_=check_near_level(r["price"],res,r["atr"],True)
        ns,_=check_near_level(r["price"],sup,r["atr"],False)
        if is_buy and nr:       blocked=True; block_reason="قريب مقاومة"
        elif not is_buy and ns: blocked=True; block_reason="قريب دعم"
        else: filters+=1

    if not blocked:
        nd,nn=check_news()
        if nd: blocked=True; block_reason=nn
        else: filters+=1

    if blocked:
        print("مرفوضة: "+block_reason)
        save_data(data); return

    dxy_dir,dxy_note=get_dxy_trend()
    d1_dir,d1_note=get_d1_trend()
    regime,regime_note=detect_market_regime(closes,highs,lows)

    # تحليل SMC
    smc=analyze_smc(closes,highs,lows,opens,r["atr"],is_buy)
    print("SMC Score: "+str(smc["smc_score"])+"/8")

    total=data["total"]
    wr=round(data["wins"]/total*100) if total>0 else 0

    msg=build_msg(r,smc,h1_note,dxy_note,d1_note,
                  regime_note,filters,wr,total,min_sc)

    if send_telegram(msg):
        print("تم: "+r["stx"]+" @ $"+str(r["price"])
              +" | فني:"+str(r["score"])
              +" SMC:"+str(smc["smc_score"]))
        data["last_signal"]=r["st"]
        data["last_price"]=r["price"]
        data["last_sl"]=smc["ob_sl"] if smc["ob_sl"] else r["lv"]["sl"]
        data["last_tp1"]=r["lv"]["tp1"]
        data["last_tp2"]=r["lv"]["tp2"]
        data["last_time"]=datetime.now().strftime("%Y-%m-%d %H:%M")
    else:
        print("فشل الارسال")

    save_data(data)

print("بوت الذهب v9 - SMC احترافي")
print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
job()
