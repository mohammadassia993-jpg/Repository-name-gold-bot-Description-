import subprocess, sys

def install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

print("جاري تثبيت المكتبات...")
install("requests")
install("schedule")
print("تم التثبيت\n")

import requests, schedule, time
from datetime import datetime, timezone

BOT_TOKEN   = "8901717984:AAFaG9H3FNiIgfa2AGRVU8q7nTdn0kCoK4s"
CHAT_ID     = "888229115"
CHECK_EVERY = 30
LDN_O, LDN_C = 8, 16
NY_O,  NY_C  = 13, 21
ATR_SL=1.5; ATR_TP1=1.5; ATR_TP2=3.0; ATR_TP3=5.0
last_signal = None

def send_telegram(text):
    url = "https://api.telegram.org/bot"+BOT_TOKEN+"/sendMessage"
    try:
        r = requests.post(url, data={"chat_id":CHAT_ID,"text":text}, timeout=10)
        return r.json().get("ok", False)
    except Exception as e:
        print("خطا ارسال: "+str(e))
        return False

def in_session():
    h = datetime.now(timezone.utc).hour
    return (LDN_O<=h<LDN_C) or (NY_O<=h<NY_C)

def get_data():
    headers = {"User-Agent":"Mozilla/5.0"}
    for sym in ["GC=F","XAUUSD=X"]:
        try:
            url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
                   +sym+"?interval=15m&range=5d")
            r = requests.get(url, headers=headers, timeout=10)
            data = r.json()
            q = data["chart"]["result"][0]["indicators"]["quote"][0]
            closes = [x for x in q["close"] if x]
            highs  = [x for x in q["high"]  if x]
            lows   = [x for x in q["low"]   if x]
            if len(closes) >= 60:
                return closes, highs, lows
        except Exception as e:
            print("خطا بيانات: "+str(e))
    return None, None, None

def ema(prices, n):
    if len(prices) < n:
        return prices[-1]
    k = 2/(n+1)
    e = sum(prices[:n])/n
    for p in prices[n:]:
        e = p*k + e*(1-k)
    return round(e, 2)

def sma(values, n):
    if len(values) < n:
        return values[-1]
    return round(sum(values[-n:])/n, 2)

def rsi(closes, n=14):
    if len(closes) < n+1:
        return 50.0
    d = [closes[i]-closes[i-1] for i in range(1,len(closes))]
    ag = sum(max(x,0) for x in d[-n:])/n
    al = sum(max(-x,0) for x in d[-n:])/n
    return round(100-100/(1+ag/al), 2) if al else 100.0

def calc_atr(highs, lows, closes, n=14):
    mn = min(len(highs),len(lows),len(closes))
    trs = [max(highs[i]-lows[i],
               abs(highs[i]-closes[i-1]),
               abs(lows[i]-closes[i-1]))
           for i in range(1,mn)]
    return round(sum(trs[-n:])/n, 2) if len(trs)>=n else 15.0

def wave_trend(closes, highs, lows, n1=10, n2=21):
    """
    Wave Trend مستوحى من VuManchu Cipher B
    n1 = Channel Length = 10
    n2 = Average Length = 21
    مناطق ذروة: +53 ذروة شراء | -53 ذروة بيع
    """
    mn = min(len(closes), len(highs), len(lows))
    closes = closes[-mn:]
    highs  = highs[-mn:]
    lows   = lows[-mn:]

    # HLC3 = متوسط السعر الثلاثي
    hlc3 = [(highs[i]+lows[i]+closes[i])/3 for i in range(mn)]

    # حساب ESA = EMA(HLC3, n1)
    def ema_list(data, n):
        if len(data) < n:
            return data[:]
        k = 2/(n+1)
        e = sum(data[:n])/n
        result = [0]*(n-1) + [e]
        for v in data[n:]:
            e = v*k + e*(1-k)
            result.append(e)
        return result

    esa_list = ema_list(hlc3, n1)
    d_list   = [abs(hlc3[i]-esa_list[i]) for i in range(mn)]
    d_ema    = ema_list(d_list, n1)

    ci_list = []
    for i in range(mn):
        denom = 0.015 * d_ema[i] if d_ema[i] != 0 else 0.0001
        ci_list.append((hlc3[i] - esa_list[i]) / denom)

    tci_list = ema_list(ci_list, n2)
    wt2_list = []
    for i in range(mn):
        if i < 3:
            wt2_list.append(tci_list[i])
        else:
            wt2_list.append(sum(tci_list[i-3:i+1])/4)

    wt1 = round(tci_list[-1], 2)
    wt2 = round(wt2_list[-1], 2)
    wt1_prev = tci_list[-2] if len(tci_list)>1 else wt1
    wt2_prev = wt2_list[-2] if len(wt2_list)>1 else wt2

    # تقاطع صاعد: wt1 كانت تحت wt2 وأصبحت فوقها
    cross_up   = (wt1_prev <= wt2_prev) and (wt1 > wt2)
    # تقاطع هابط: wt1 كانت فوق wt2 وأصبحت تحتها
    cross_down = (wt1_prev >= wt2_prev) and (wt1 < wt2)

    oversold   = wt1 < -53
    overbought = wt1 > 53

    if cross_up:   wt_signal = "BUY"
    elif cross_down: wt_signal = "SELL"
    else:            wt_signal = "NEUTRAL"

    return wt1, wt2, wt_signal, oversold, overbought

def analyze(closes, highs, lows):
    price = round(closes[-1], 2)
    r     = rsi(closes)
    e20   = ema(closes, 20)
    e50   = ema(closes, 50)
    macd  = round(ema(closes,12)-ema(closes,26), 2)
    a     = calc_atr(highs,lows,closes)
    wt1, wt2, wt_sig, oversold, overbought = wave_trend(closes,highs,lows)

    score, reasons = 0, []

    # ── EMA ──────────────────────────────
    if price > e20 > e50:
        score+=2; reasons.append("السعر فوق EMA20 و EMA50 - صاعد")
    elif price < e20 < e50:
        score-=2; reasons.append("السعر تحت EMA20 و EMA50 - هابط")
    else:
        reasons.append("EMA محايد")

    if len(closes)>=200:
        e200=ema(closes,200)
        if price>e200: score+=1; reasons.append("فوق EMA200 - صاعد طويل")
        else:          score-=1; reasons.append("تحت EMA200 - هابط طويل")

    # ── RSI ──────────────────────────────
    if r<30:   score+=2; reasons.append("RSI="+str(r)+" ذروة بيع")
    elif r>70: score-=2; reasons.append("RSI="+str(r)+" ذروة شراء")
    else:      reasons.append("RSI="+str(r)+" محايد")

    # ── MACD ─────────────────────────────
    if macd>0: score+=1; reasons.append("MACD="+str(macd)+" زخم صاعد")
    else:      score-=1; reasons.append("MACD="+str(macd)+" زخم هابط")

    # ── Wave Trend (VuManchu) ─────────────
    wt_zone = ""
    if oversold:    wt_zone = " في ذروة البيع"
    elif overbought: wt_zone = " في ذروة الشراء"

    if wt_sig == "BUY":
        score+=2
        reasons.append("WaveTrend تقاطع صاعد"+wt_zone+" - اشارة شراء قوية")
    elif wt_sig == "SELL":
        score-=2
        reasons.append("WaveTrend تقاطع هابط"+wt_zone+" - اشارة بيع قوية")
    else:
        reasons.append("WaveTrend="+str(wt1)+" محايد"+wt_zone)

    # ── الحكم النهائي ─────────────────────
    if   score>=5:  st,stx,dr="BUY_S","شراء قوي جدا","صاعد قوي جدا"
    elif score>=3:  st,stx,dr="BUY_W","شراء قوي","صاعد قوي"
    elif score>=1:  st,stx,dr="BUY_C","شراء بحذر","صاعد ضعيف"
    elif score<=-5: st,stx,dr="SELL_S","بيع قوي جدا","هابط قوي جدا"
    elif score<=-3: st,stx,dr="SELL_W","بيع قوي","هابط قوي"
    elif score<=-1: st,stx,dr="SELL_C","بيع بحذر","هابط ضعيف"
    else:           st,stx,dr="WAIT","انتظار","جانبي"

    buy="BUY" in st
    lv={
        "entry": price,
        "sl":  round(price-a*ATR_SL  if buy else price+a*ATR_SL,  2),
        "tp1": round(price+a*ATR_TP1 if buy else price-a*ATR_TP1, 2),
        "tp2": round(price+a*ATR_TP2 if buy else price-a*ATR_TP2, 2),
        "tp3": round(price+a*ATR_TP3 if buy else price-a*ATR_TP3, 2),
    }
    return dict(st=st,stx=stx,dr=dr,score=score,
                rsi=r,macd=macd,e20=e20,e50=e50,
                atr=a,wt1=wt1,wt2=wt2,wt_sig=wt_sig,
                price=price,lv=lv,reasons=reasons)

def build_msg(r):
    lv  = r["lv"]
    rs  = "\n".join("- "+x for x in r["reasons"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    wt_arrow = "↑" if r["wt_sig"]=="BUY" else ("↓" if r["wt_sig"]=="SELL" else "-")
    return (
        "تحليل الذهب XAUUSD M15\n"
        "========================\n"
        "السعر:    $"+str(r["price"])+"\n"
        "الاتجاه:  "+r["dr"]+"\n"
        "الاشارة:  "+r["stx"]+"\n"
        "القوة:    "+str(r["score"])+" / 8\n\n"
        "المؤشرات:\n"
        "RSI="+str(r["rsi"])+" | MACD="+str(r["macd"])+"\n"
        "EMA20="+str(r["e20"])+" | EMA50="+str(r["e50"])+"\n"
        "ATR="+str(r["atr"])+"\n"
        "WaveTrend="+str(r["wt1"])+" "+wt_arrow+"\n\n"
        "الاسباب:\n"+rs+"\n\n"
        "مستويات التداول:\n"
        "الدخول:      $"+str(lv["entry"])+"\n"
        "وقف الخسارة: $"+str(lv["sl"])+"\n"
        "TP1: $"+str(lv["tp1"])+"\n"
        "TP2: $"+str(lv["tp2"])+"\n"
        "TP3: $"+str(lv["tp3"])+"\n\n"
        "الوقت: "+now
    )

def job():
    global last_signal
    now_str = datetime.now().strftime("%H:%M")

    if not in_session():
        print("خارج جلسة التداول - "+now_str)
        return

    closes,highs,lows = get_data()
    if closes is None:
        print("فشل جلب البيانات")
        return

    r = analyze(closes,highs,lows)

    if r["st"]=="WAIT":
        print("لا اشارة | Score="+str(r["score"])+" | "+now_str)
        return

    if r["st"]==last_signal:
        print("نفس الاشارة - تخطي")
        return

    last_signal = r["st"]
    msg = build_msg(r)

    if send_telegram(msg):
        print("تم الارسال: "+r["stx"]+" @ $"+str(r["price"]))
    else:
        print("فشل الارسال")

print("بوت الذهب v5 - مع Wave Trend")
print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
print("-"*35)

job()

schedule.every(CHECK_EVERY).minutes.do(job)

while True:
    try:
        schedule.run_pending()
        time.sleep(60)
    except KeyboardInterrupt:
        print("تم الايقاف")
        break
    except Exception as e:
        print("خطا: "+str(e))
        time.sleep(60)
