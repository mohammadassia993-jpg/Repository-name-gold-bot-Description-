import requests, json, os
from datetime import datetime, timezone, timedelta

BOT_TOKEN    = "8901717984:AAFaG9H3FNiIgfa2AGRVU8q7nTdn0kCoK4s"
CHAT_ID      = "888229115"
LDN_O, LDN_C = 8, 16
NY_O,  NY_C  = 13, 21
ATR_SL=1.5; ATR_TP1=1.5; ATR_TP2=3.0; ATR_TP3=5.0
DATA_FILE    = "data.json"

# ════════════════════════════════════════
# إدارة البيانات المستمرة
# ════════════════════════════════════════
def load_data():
    default = {
        "last_signal": None,
        "last_price": None,
        "last_sl": None,
        "last_tp1": None,
        "last_tp2": None,
        "last_tp3": None,
        "last_time": None,
        "history": [],
        "total": 0,
        "wins": 0,
        "losses": 0,
        "min_score": 3,
        "week_signals": 0,
        "week_wins": 0
    }
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE,"r") as f:
                saved = json.load(f)
                default.update(saved)
    except:
        pass
    return default

def save_data(data):
    try:
        with open(DATA_FILE,"w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("خطا حفظ البيانات: "+str(e))

# ════════════════════════════════════════
# تتبع نتيجة الصفقة السابقة
# ════════════════════════════════════════
def check_last_signal(data, current_price):
    if not data["last_signal"] or not data["last_price"]:
        return data

    sl   = data["last_sl"]
    tp1  = data["last_tp1"]
    tp2  = data["last_tp2"]
    sig  = data["last_signal"]
    is_buy = "BUY" in sig
    result = None

    if is_buy:
        if current_price >= tp2:  result = "WIN_BIG"
        elif current_price >= tp1: result = "WIN"
        elif current_price <= sl:  result = "LOSS"
    else:
        if current_price <= tp2:  result = "WIN_BIG"
        elif current_price <= tp1: result = "WIN"
        elif current_price >= sl:  result = "LOSS"

    if result:
        data["total"] += 1
        data["week_signals"] += 1
        if "WIN" in result:
            data["wins"] += 1
            data["week_wins"] += 1
            emoji = "✅ ربح كبير" if result=="WIN_BIG" else "✅ ربح"
        else:
            data["losses"] += 1
            emoji = "❌ خسارة"

        win_rate = round(data["wins"]/data["total"]*100) if data["total"]>0 else 0
        data["history"].append({
            "signal": sig,
            "result": result,
            "time": data["last_time"]
        })
        data["history"] = data["history"][-20:]

        # تكيف تلقائي للحد الأدنى
        if data["total"] >= 10:
            if win_rate < 50 and data["min_score"] < 5:
                data["min_score"] += 1
                print("تم رفع الحد الأدنى للنقاط إلى "+str(data["min_score"]))
            elif win_rate > 70 and data["min_score"] > 3:
                data["min_score"] -= 1
                print("تم خفض الحد الأدنى للنقاط إلى "+str(data["min_score"]))

        send_telegram(
            "نتيجة الصفقة السابقة: "+emoji+"\n"
            "النوع: "+sig+"\n"
            "السعر الحالي: $"+str(round(current_price,2))+"\n"
            "الاجمالي: "+str(data["wins"])+"W / "+str(data["losses"])+"L"
            " | نسبة النجاح: "+str(win_rate)+"%"
        )
        data["last_signal"] = None

    return data

# ════════════════════════════════════════
# تقرير نهاية الأسبوع (الجمعة 19:00 UTC)
# ════════════════════════════════════════
def check_weekly_report(data):
    now = datetime.now(timezone.utc)
    if now.weekday() == 4 and 18 <= now.hour <= 20:
        total  = data["total"]
        wins   = data["wins"]
        losses = data["losses"]
        wr     = round(wins/total*100) if total>0 else 0
        bar    = "█"*int(wr/10) + "░"*(10-int(wr/10))
        msg = (
            "📊 تقرير الأسبوع — بوت الذهب\n"
            "================================\n"
            "الصفقات الكلية:  "+str(total)+"\n"
            "الرابحة:         "+str(wins)+"\n"
            "الخاسرة:         "+str(losses)+"\n"
            "نسبة النجاح:     "+str(wr)+"%\n"
            "["+bar+"]\n\n"
            "هذا الأسبوع:\n"
            "إشارات:  "+str(data["week_signals"])+"\n"
            "أرباح:   "+str(data["week_wins"])+"\n\n"
            "الحد الأدنى للنقاط: "+str(data["min_score"])+"/8\n"
            "تعديل تلقائي حسب الأداء"
        )
        send_telegram(msg)
        data["week_signals"] = 0
        data["week_wins"] = 0

# ════════════════════════════════════════
# إرسال تيليغرام
# ════════════════════════════════════════
def send_telegram(text):
    url = "https://api.telegram.org/bot"+BOT_TOKEN+"/sendMessage"
    try:
        r = requests.post(url,data={"chat_id":CHAT_ID,"text":text},timeout=10)
        return r.json().get("ok",False)
    except Exception as e:
        print("خطا ارسال: "+str(e))
        return False

def in_session():
    h = datetime.now(timezone.utc).hour
    return (LDN_O<=h<LDN_C) or (NY_O<=h<NY_C)

# ════════════════════════════════════════
# جلب البيانات
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
            if len(closes)>=30: return closes,highs,lows
        except Exception as e:
            print("خطا بيانات "+interval+": "+str(e))
    return None,None,None

# ════════════════════════════════════════
# المؤشرات
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
    closes=closes[-mn:]; highs=highs[-mn:]; lows=lows[-mn:]
    hlc3=[(highs[i]+lows[i]+closes[i])/3 for i in range(mn)]
    def ema_list(data,n):
        if len(data)<n: return data[:]
        k=2/(n+1); e=sum(data[:n])/n
        result=[0]*(n-1)+[e]
        for v in data[n:]: e=v*k+e*(1-k); result.append(e)
        return result
    esa=ema_list(hlc3,n1)
    d_ema=ema_list([abs(hlc3[i]-esa[i]) for i in range(mn)],n1)
    ci=[(hlc3[i]-esa[i])/(0.015*d_ema[i] if d_ema[i] else 0.0001)
        for i in range(mn)]
    tci=ema_list(ci,n2)
    wt2=[sum(tci[i-3:i+1])/4 if i>=3 else tci[i] for i in range(mn)]
    wt1=round(tci[-1],2); w2=round(wt2[-1],2)
    p1=tci[-2] if len(tci)>1 else wt1
    p2=wt2[-2] if len(wt2)>1 else w2
    sig="BUY" if (p1<=p2 and wt1>w2) else("SELL" if (p1>=p2 and wt1<w2) else "NEUTRAL")
    return wt1,w2,sig,wt1<-53,wt1>53

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
            e20=ema(closes,20); e50=ema(closes,50) if len(closes)>=50 else e20
            price=closes[-1]
            if price>e20: return "UP","DXY صاعد (ضغط على الذهب)"
            else: return "DOWN","DXY هابط (دعم للذهب)"
        except: pass
    return "NEUTRAL","DXY غير متاح"

def get_d1_trend():
    closes,highs,lows=get_data("1d","60d")
    if closes is None: return "NEUTRAL","D1 غير متاح"
    e20=ema(closes,20); e50=ema(closes,50) if len(closes)>=50 else e20
    price=closes[-1]; r=rsi(closes)
    if price>e20>e50 and r>45: return "UP","D1 صاعد"
    elif price<e20<e50 and r<55: return "DOWN","D1 هابط"
    else: return "NEUTRAL","D1 محايد"

def detect_market_regime(closes,highs,lows):
    if len(closes)<20: return "TREND","سوق متحرك"
    recent_highs=highs[-20:]; recent_lows=lows[-20:]
    high_range=max(recent_highs)-min(recent_highs)
    atr_val=calc_atr(highs,lows,closes)
    ratio=high_range/(atr_val*20) if atr_val>0 else 1
    if ratio>1.5: return "TREND","سوق في اتجاه واضح"
    else: return "RANGE","سوق جانبي — تداول بحذر"

def get_h1_trend():
    closes,highs,lows=get_data("1h","15d")
    if closes is None: return "NEUTRAL","H1 غير متاح"
    e20=ema(closes,20); e50=ema(closes,50)
    price=closes[-1]; r=rsi(closes)
    if price>e20>e50 and r>45: return "UP","H1 صاعد"
    elif price<e20<e50 and r<55: return "DOWN","H1 هابط"
    else: return "NEUTRAL","H1 محايد"

def find_key_levels(highs,lows,closes):
    last_price=closes[-1]
    rh=sorted(highs[-50:],reverse=True)[:3]
    rl=sorted(lows[-50:])[:3]
    res=min([h for h in rh if h>last_price],default=None)
    sup=max([l for l in rl if l<last_price],default=None)
    return res,sup

def check_near_level(price,level,atr,is_res):
    if level is None: return False,""
    if abs(price-level)<atr*0.5:
        return True,"قريب من "+("مقاومة" if is_res else "دعم")+" ("+str(round(level,2))+")"
    return False,""

def check_news():
    try:
        r=requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",timeout=8)
        now_utc=datetime.now(timezone.utc)
        kws=["Non-Farm","CPI","FOMC","Fed","Interest Rate","GDP","NFP","Powell"]
        for ev in r.json():
            if ev.get("impact","")!="High": continue
            if ev.get("currency","") not in ["USD","XAU"]: continue
            try:
                et=datetime.fromisoformat(ev.get("date","").replace("Z","+00:00"))
                diff=(et-now_utc).total_seconds()/60
                if -15<=diff<=60:
                    t=ev.get("title","")
                    if any(k.lower() in t.lower() for k in kws):
                        return True,"خبر: "+t
            except: continue
        return False,""
    except: return False,""

# ════════════════════════════════════════
# التقييم الذكي المحدّث
# ════════════════════════════════════════
def smart_analysis(score,rsi_val,macd_val,wt1,wt_sig,
                   h1_dir,atr_val,is_buy,filters,
                   dxy_dir,d1_dir,regime,win_rate,total):
    notes=[]
    if score>=5: conf="ثقة عالية جداً"; size="الحجم الكامل 100%"
    else:        conf="ثقة جيدة";       size="50% الى 75% من الحجم"

    # DXY
    if is_buy and dxy_dir=="DOWN":
        notes.append("DXY هابط — يدعم صعود الذهب")
    elif is_buy and dxy_dir=="UP":
        notes.append("DXY صاعد — يضغط على الذهب، انتبه")
    elif not is_buy and dxy_dir=="UP":
        notes.append("DXY صاعد — يدعم هبوط الذهب")

    # D1
    if d1_dir=="UP" and is_buy:   notes.append("D1 يدعم الصعود — اتجاه يومي موافق")
    elif d1_dir=="DOWN" and not is_buy: notes.append("D1 يدعم الهبوط — اتجاه يومي موافق")
    elif d1_dir=="NEUTRAL": notes.append("D1 محايد — انتبه للمستويات")

    # طبيعة السوق
    if regime=="RANGE":
        notes.append("سوق جانبي — استهدف TP1 فقط وأغلق مبكراً")
    else:
        notes.append("سوق في اتجاه — يمكن الاحتفاظ لـ TP2/TP3")

    # WaveTrend
    if wt_sig=="BUY" and wt1<-53: notes.append("WaveTrend ذروة بيع — فرصة انعكاس قوية")
    elif wt_sig=="SELL" and wt1>53: notes.append("WaveTrend ذروة شراء — فرصة انعكاس قوية")

    # RSI
    if is_buy and rsi_val<40:   notes.append("RSI منخفض — زخم في البداية")
    elif is_buy and rsi_val>65: notes.append("RSI مرتفع — تباطؤ محتمل")
    elif not is_buy and rsi_val>60: notes.append("RSI مرتفع — زخم بيع في البداية")

    # ATR
    if atr_val<8:   risk="تقلب منخفض — التزم بـ SL بدقة"
    elif atr_val>20: risk="تقلب عالٍ — قلل الحجم"
    else:            risk="تقلب طبيعي — المستويات مناسبة"

    # الأداء التاريخي
    if total>=10:
        notes.append("نسبة نجاحك التاريخية: "+str(win_rate)+"%")

    return conf,size,risk,"\n".join("• "+n for n in notes)

# ════════════════════════════════════════
# التحليل الرئيسي
# ════════════════════════════════════════
def analyze(closes,highs,lows,min_score):
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

    abs_score=abs(score)
    if   score>=5:          st,stx,dr,em="BUY_S","شراء قوي جدا","صاعد قوي جدا","🟢"
    elif score>=min_score:  st,stx,dr,em="BUY_W","شراء","صاعد","🔵"
    elif score<=-5:         st,stx,dr,em="SELL_S","بيع قوي جدا","هابط قوي جدا","🔴"
    elif score<=-min_score: st,stx,dr,em="SELL_W","بيع","هابط","🟠"
    else:                   st,stx,dr,em="WAIT","انتظار","جانبي","⚪"

    buy="BUY" in st
    lv={"entry":price,
        "sl" :round(price-a*ATR_SL  if buy else price+a*ATR_SL, 2),
        "tp1":round(price+a*ATR_TP1 if buy else price-a*ATR_TP1,2),
        "tp2":round(price+a*ATR_TP2 if buy else price-a*ATR_TP2,2),
        "tp3":round(price+a*ATR_TP3 if buy else price-a*ATR_TP3,2)}
    return dict(st=st,stx=stx,dr=dr,emoji=em,score=score,
                rsi=r,macd=macd,e20=e20,e50=e50,atr=a,
                wt1=wt1,wt_sig=wt_sig,price=price,lv=lv,reasons=reasons)

def build_msg(r,h1n,dxy_n,d1_n,regime_n,filters,conf,size,risk,ai_notes,wr,total,min_sc):
    lv=r["lv"]
    rs="\n".join("- "+x for x in r["reasons"])
    now=datetime.now().strftime("%Y-%m-%d %H:%M")
    arrow="↑" if r["wt_sig"]=="BUY" else("↓" if r["wt_sig"]=="SELL" else"-")
    bar="".join(["█" if i<abs(r["score"]) else "░" for i in range(8)])
    perf=""
    if total>0:
        perf="\nالاداء: "+str(wr)+"% | "+str(total)+" صفقة"
    return (
        r["emoji"]+" تحليل الذهب XAUUSD\n"
        "================================\n"
        "السعر:    $"+str(r["price"])+"\n"
        "الاتجاه:  "+r["dr"]+"\n"
        "الاشارة:  "+r["stx"]+"\n"
        "القوة:    ["+bar+"] "+str(abs(r["score"]))+"/8\n"
        "الفلاتر:  "+str(filters)+"/3\n"
        "الحد:     "+str(min_sc)+"/8 (تكيف تلقائي)"+perf+"\n\n"
        "المؤشرات:\n"
        "RSI="+str(r["rsi"])+" | MACD="+str(r["macd"])+"\n"
        "EMA20="+str(r["e20"])+" | EMA50="+str(r["e50"])+"\n"
        "ATR="+str(r["atr"])+" | WT="+str(r["wt1"])+" "+arrow+"\n\n"
        "السياق:\n"
        "• "+h1n+"\n"
        "• "+d1_n+"\n"
        "• "+dxy_n+"\n"
        "• "+regime_n+"\n\n"
        "التحليل M15:\n"+rs+"\n\n"
        "================================\n"
        "🧠 التقييم الذكي:\n"
        "الثقة: "+conf+"\n"
        "الحجم: "+size+"\n\n"
        "التفاصيل:\n"+ai_notes+"\n\n"
        "المخاطرة: "+risk+"\n\n"
        "================================\n"
        "مستويات التداول:\n"
        "الدخول:      $"+str(lv["entry"])+"\n"
        "وقف الخسارة: $"+str(lv["sl"])+"\n"
        "TP1: $"+str(lv["tp1"])+"\n"
        "TP2: $"+str(lv["tp2"])+"\n"
        "TP3: $"+str(lv["tp3"])+"\n\n"
        "الوقت: "+now
    )

# ════════════════════════════════════════
# الدالة الرئيسية
# ════════════════════════════════════════
def job():
    data=load_data()

    if not in_session():
        print("خارج جلسة التداول")
        return

    closes,highs,lows=get_data("15m","5d")
    if closes is None:
        print("فشل جلب M15")
        return

    current_price=closes[-1]

    # تتبع الصفقة السابقة
    data=check_last_signal(data,current_price)

    # تقرير أسبوعي
    check_weekly_report(data)

    # التحليل
    min_sc=data["min_score"]
    r=analyze(closes,highs,lows,min_sc)

    if r["st"]=="WAIT":
        print("لا اشارة | Score="+str(r["score"])+" | حد="+str(min_sc))
        save_data(data)
        return

    if r["st"]==data["last_signal"]:
        print("نفس الاشارة - تخطي")
        save_data(data)
        return

    is_buy="BUY" in r["st"]
    filters=0; blocked=False; block_reason=""

    # فلتر H1
    h1_dir,h1_note=get_h1_trend()
    if h1_dir=="UP" and is_buy:       filters+=1
    elif h1_dir=="DOWN" and not is_buy: filters+=1
    elif h1_dir=="NEUTRAL":            filters+=1
    else: blocked=True; block_reason="عكس H1"

    # فلتر دعم/مقاومة
    if not blocked:
        res,sup=find_key_levels(highs,lows,closes)
        nr,_=check_near_level(r["price"],res,r["atr"],True)
        ns,_=check_near_level(r["price"],sup,r["atr"],False)
        if is_buy and nr:       blocked=True; block_reason="قريب مقاومة"
        elif not is_buy and ns: blocked=True; block_reason="قريب دعم"
        else: filters+=1

    # فلتر أخبار
    if not blocked:
        nd,nn=check_news()
        if nd: blocked=True; block_reason=nn
        else: filters+=1

    if blocked:
        print("مرفوضة: "+block_reason)
        save_data(data)
        return

    # المستوى 1 — DXY + D1 + طبيعة السوق
    dxy_dir,dxy_note=get_dxy_trend()
    d1_dir,d1_note=get_d1_trend()
    regime,regime_note=detect_market_regime(closes,highs,lows)

    # تحذير DXY معاكس
    if is_buy and dxy_dir=="UP":
        print("تحذير: DXY صاعد يعاكس الشراء — إرسال مع تحذير")
    elif not is_buy and dxy_dir=="DOWN":
        print("تحذير: DXY هابط يعاكس البيع — إرسال مع تحذير")

    # الإحصائيات
    total=data["total"]
    wr=round(data["wins"]/total*100) if total>0 else 0

    # التقييم الذكي
    conf,size,risk,ai_notes=smart_analysis(
        r["score"],r["rsi"],r["macd"],r["wt1"],r["wt_sig"],
        h1_dir,r["atr"],is_buy,filters,
        dxy_dir,d1_dir,regime,wr,total)

    msg=build_msg(r,h1_note,dxy_note,d1_note,regime_note,
                  filters,conf,size,risk,ai_notes,wr,total,min_sc)

    if send_telegram(msg):
        print("تم: "+r["stx"]+" @ $"+str(r["price"])+" | "+str(filters)+"/3")
        data["last_signal"]=r["st"]
        data["last_price"]=r["price"]
        data["last_sl"]=r["lv"]["sl"]
        data["last_tp1"]=r["lv"]["tp1"]
        data["last_tp2"]=r["lv"]["tp2"]
        data["last_tp3"]=r["lv"]["tp3"]
        data["last_time"]=datetime.now().strftime("%Y-%m-%d %H:%M")
    else:
        print("فشل الارسال")

    save_data(data)

print("بوت الذهب v8 - المستويات الثلاثة")
print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
job()
