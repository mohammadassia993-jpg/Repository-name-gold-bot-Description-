import requests, json, os, time, threading
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
TWELVE_API_KEY = os.environ.get("TWELVE_API_KEY", "")
DATA_FILE    = "data.json"
SYRIA_OPEN   = 8
SYRIA_CLOSE  = 23
EQUITY = 200  # رأس المال الحالي (دولار) — حدّث هذا الرقم عند تغيّر رأس المال

def calc_lot(score, entry, sl):
    s=abs(score)
    if s>=7:   risk_pct,label="1.5","كبيرة"
    elif s>=5: risk_pct,label="1.0","متوسطة"
    else:      risk_pct,label="0.5","صغيرة"
    risk_pct=float(risk_pct)
    sl_dist=abs(entry-sl)
    if sl_dist<=0: return 0.01,label,risk_pct,0.0
    risk_amount=EQUITY*risk_pct/100
    ideal_lot=risk_amount/(sl_dist*100)
    lot=int(ideal_lot*100)/100
    if lot<0.01: lot=0.01
    actual_risk_pct=round((lot*100*sl_dist/EQUITY)*100,1)
    return lot,label,risk_pct,actual_risk_pct

# ── نسب SL/TP المحسّنة (R:R أفضل) ──
ATR_SL  = 1.5   # وُسّع من 1.0 بعد اختبار رجعي أثبت تحسناً ثابتاً (PF وWR) في فترتين منفصلتين
ATR_TP1 = 2.0   # 1:2  (كان 1.5)
ATR_TP2 = 3.5   # 1:3.5 (كان 3.0)
ATR_TP3 = 6.0   # 1:6   (كان 5.0)

def syria_now():
    return datetime.now(timezone.utc) + timedelta(hours=3)

def syria_time_str():
    return syria_now().strftime("%Y-%m-%d %H:%M") + " (سوريا)"

BEST_HOURS = {2, 3, 4, 10, 11, 17, 20, 21}  # 4 ممتازة + 4 جيدة = 8 ساعات (توازن جودة/تكرار)

def in_session():
    now = syria_now()
    if now.weekday() >= 5:  # 5=السبت, 6=الأحد
        return False
    if now.hour not in BEST_HOURS:
        return False
    return True

def load_data():
    default = {
        "last_signal":None,"last_price":None,
        "last_sl":None,"last_tp1":None,
        "last_tp2":None,"last_time":None,
        "history":[],"total":0,"wins":0,
        "losses":0,"min_score":3,
        "week_signals":0,"week_wins":0,
        "week_trades":[],"last_report_date":None,
        "consecutive_losses":0,"breaker_until":None,
        "last_check":None,"last_reason":None,
        "tp1_hit":False,"tp2_hit":False,
        "trade_history":[],"profit_factor":None
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
    tp2=data["last_tp2"]; tp3=data.get("last_tp3")
    sig=data["last_signal"]; entry=data["last_price"]
    is_buy="BUY" in sig
    tp1_hit=data.get("tp1_hit",False)
    tp2_hit=data.get("tp2_hit",False)

    def pips(exit_price):
        return round((exit_price-entry)/0.1,1) if is_buy else round((entry-exit_price)/0.1,1)

    def close_trade(result, exit_price, label):
        data["total"]+=1; data["week_signals"]+=1
        p=pips(exit_price)
        if "WIN" in result:
            data["wins"]+=1; data["week_wins"]+=1
            data["consecutive_losses"]=0
            em="✅ ربح كبير" if result=="WIN_BIG" else "✅ ربح"
        else:
            data["losses"]+=1; em="❌ خسارة"
            data["consecutive_losses"]=data.get("consecutive_losses",0)+1
            if data["consecutive_losses"]>=5 and not data.get("breaker_until"):
                until=datetime.now(timezone.utc)+timedelta(hours=8)
                data["breaker_until"]=until.strftime("%Y-%m-%d %H:%M")
                send_telegram("⛔ قاطع الدائرة مُفعّل\n"
                    "5 خسائر متتالية — إيقاف الإشارات 8 ساعات للمراجعة\n"
                    "سيُستأنف العمل تلقائياً بعد: "+data["breaker_until"]+" UTC")
        wr=round(data["wins"]/data["total"]*100) if data["total"]>0 else 0
        hist=data.setdefault("trade_history",[])
        hist.append(p)
        data["trade_history"]=hist[-100:]
        hist=data["trade_history"]
        if len(hist)>=100:
            gains=sum(x for x in hist if x>0)
            losses=abs(sum(x for x in hist if x<0))
            pf=round(gains/losses,2) if losses>0 else 99.0
            data["profit_factor"]=pf
            if pf<1.2 and data["min_score"]<6: data["min_score"]+=1
            elif pf>2.0 and data["min_score"]>3: data["min_score"]-=1
        data.setdefault("week_trades",[]).append({
            "sig":sig,"entry":entry,"exit":exit_price,
            "pips":p,"result":result
        })
        send_telegram(em+" "+label+"\n"
            "النوع: "+sig+"\nالسعر: $"+str(round(exit_price,2))+"\n"
            "النقاط: "+("+" if p>=0 else "")+str(p)+"\n"
            "الاجمالي: "+str(data["wins"])+"W/"
            +str(data["losses"])+"L | "+str(wr)+"%")
        data["last_signal"]=None
        data["tp1_hit"]=False; data["tp2_hit"]=False

    if tp3 is not None and ((is_buy and price>=tp3) or (not is_buy and price<=tp3)):
        close_trade("WIN_BIG", price, "🏆 الهدف النهائي (TP3) تحقق")
        return data

    if not tp2_hit and ((is_buy and price>=tp2) or (not is_buy and price<=tp2)):
        data["tp2_hit"]=True
        send_telegram("🎯 الهدف الثاني (TP2) تحقق!\n"
            "النوع: "+sig+" | السعر: $"+str(round(price,2))+"\n"
            "وقف الخسارة انتقل الآن لـ TP1 ($"+str(tp1)+") لتأمين المكسب.\n"
            "البوت يستمر بمتابعة الهدف النهائي TP3.")
        return data

    if not tp1_hit and ((is_buy and price>=tp1) or (not is_buy and price<=tp1)):
        data["tp1_hit"]=True
        send_telegram("🎯 الهدف الأول (TP1) تحقق!\n"
            "النوع: "+sig+" | السعر: $"+str(round(price,2))+"\n"
            "وقف الخسارة انتقل الآن لنقطة الدخول ($"+str(entry)+") لتأمين الصفقة.\n"
            "البوت يستمر بمتابعة TP2.")
        return data

    sl_dist=abs(entry-sl) if sl else 0
    atr_buf=round(sl_dist*0.2,2)

    if tp2_hit:
        stop=tp1
    elif tp1_hit:
        stop=round(entry-atr_buf if is_buy else entry+atr_buf,2)
    else:
        stop=sl

    if (is_buy and price<=stop) or (not is_buy and price>=stop):
        result="WIN" if pips(price)>=0 else "LOSS"
        close_trade(result, price, "نتيجة الصفقة السابقة")
        return data

    if data.get("last_time"):
        try:
            opened=datetime.strptime(data["last_time"],"%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            elapsed=(datetime.now(timezone.utc)-opened).total_seconds()
            if elapsed>4*3600:
                if tp1_hit and pips(price)>=0:
                    close_trade("WIN", price, "⏱️ انتهت المهلة (4 ساعات) بعد تأمين الهدف الأول")
                elif tp1_hit:
                    close_trade("LOSS", price, "⏱️ انتهت المهلة (تراجع بعد TP1)")
                else:
                    send_telegram("⏱️ انتهت مهلة الصفقة (4 ساعات) بدون نتيجة\n"
                        "النوع: "+sig+" | الدخول: $"+str(entry)+"\n"
                        "البوت جاهز الآن لإشارة جديدة.")
                    data["last_signal"]=None
        except: pass
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
    hist_n=len(data.get("trade_history",[]))
    pf=data.get("profit_factor")
    pf_line="عامل الربح (100 صفقة): "+str(pf) if pf is not None else "عامل الربح: قيد التجميع ("+str(hist_n)+"/100)"
    lines.append("\nالإجمالي: "+str(t)+" | رابحة: "+str(w)+" | خاسرة: "+str(l)
                 +"\nنسبة النجاح: "+str(wr)+"%\n"+pf_line
                 +"\nالحد التكيفي: "+str(data["min_score"])+"/8")
    send_telegram("".join(lines))
    data["week_trades"]=[]
    data["week_signals"]=0; data["week_wins"]=0
    data["last_report_date"]=today_str
    return data

LAST_TG_ERROR=""
def send_telegram(text):
    global LAST_TG_ERROR
    url="https://api.telegram.org/bot"+BOT_TOKEN+"/sendMessage"
    try:
        r=requests.post(url,data={"chat_id":CHAT_ID,"text":text},timeout=10)
        ok=r.json().get("ok",False)
        if not ok:
            LAST_TG_ERROR="HTTP"+str(r.status_code)+": "+str(r.text)[:200]
        return ok
    except Exception as e:
        LAST_TG_ERROR="Exception: "+str(e)
        print("خطا ارسال: "+str(e)); return False

# ── XAUUSD=X أولاً (سعر فوري = نفس MT5) ──
def get_data(interval="15m", days="5d"):
    try:
        tf = {"15m":"15min","1h":"1h","1d":"1day"}.get(interval, "15min")
        url = f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval={tf}&outputsize=60&apikey={TWELVE_API_KEY}"
        r = requests.get(url, timeout=10)
        data = r.json()
        vals = data.get("values", [])
        if not vals:
            print("لا بيانات من Twelve Data: " + str(data))
            return None, None, None, None, None
        vals = vals[::-1]
        closes  = [float(x["close"])  for x in vals]
        highs   = [float(x["high"])   for x in vals]
        lows    = [float(x["low"])    for x in vals]
        opens   = [float(x["open"])   for x in vals]
        volumes = [float(x.get("volume", 0)) for x in vals]
        mn = min(len(closes), len(highs), len(lows), len(opens))
        if mn >= 30:
            return closes[:mn], highs[:mn], lows[:mn], opens[:mn], volumes[:mn]
        return None, None, None, None, None
    except Exception as e:
        print("خطأ Twelve Data: " + str(e))
        return None, None, None, None, None


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
    closes,highs,lows,opens,_=get_data("1d","60d")
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
    closes,highs,lows,opens,_=get_data("1h","15d")
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
    mh,ml=max(highs[-20:]),min(lows[-20:])  # نطاق هيكلي بدون تأخير (20 شمعة)
    zone=round(a*0.3,2)
    lv={
        "entry":price,
        "entry_zone_low" :round(price-zone if buy else price-zone,2),
        "entry_zone_high":round(price+zone if buy else price+zone,2),
        "sl" :round(price-a*ATR_SL  if buy else price+a*ATR_SL, 2),
        "tp1":round(price+a*ATR_TP1 if buy else price-a*ATR_TP1,2),
        "tp2":round(price+a*ATR_TP2 if buy else price-a*ATR_TP2,2),
        "tp3":round(price+a*ATR_TP3 if buy else price-a*ATR_TP3,2),
        "tp_structure":round(mh,2) if buy else round(ml,2)
    }
    return dict(st=st,stx=stx,dr=dr,emoji=em,score=score,
                rsi=r,macd=macd,e20=e20,e50=e50,atr=a,
                wt1=wt1,wt_sig=wt_sig,price=price,
                lv=lv,reasons=reasons)

def build_msg(r,smc,h1n,dxy_n,d1_n,regime_n,filters,wr,total,min_sc,vol_note=""):
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
    lot,size_label,target_risk,actual_risk=calc_lot(r["score"],lv["entry"],sl_final)
    risk_warn="⚠️ " if actual_risk>target_risk*1.5 else ""

    return (
        r["emoji"]+" الذهب XAUUSD M15 — إشارة\n"
        "========================\n"
        "السعر:    $"+str(r["price"])+"\n"
        "الاتجاه:  "+r["dr"]+"\n"
        "الاشارة:  "+r["stx"]+"\n"
        "فني: ["+tbar+"] "+str(abs(r["score"]))+"/8\n"
        "SMC: ["+sbar+"] "+str(smc["smc_score"])+"/8\n"
        "فلاتر: "+str(filters)+"/4"+perf+"\n\n"
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
        "TP3: $"+str(lv["tp3"])+"\n"
        "🎯 هدف هيكلي (20 شمعة): $"+str(lv["tp_structure"])+"\n\n"
        "💰 حجم الصفقة المقترح: "+size_label+" — "+str(lot)+" لوت\n"
        +risk_warn+"الخطر الفعلي: "+str(actual_risk)+"% من $"+str(EQUITY)+" (المستهدف "+str(target_risk)+"%)\n\n"
        "⚠️ استخدم سعر MT5 للدخول\n"
        "الحد: "+str(min_sc)+"/8\n"
        "الوقت: "+now+vol_note
    )

def volume_confirms(volumes, lookback=20, multiplier=1.1):
    if not volumes or len(volumes)<lookback+1: return True  # بدون بيانات → لا نمنع
    avg_vol=sum(volumes[-lookback-1:-1])/lookback
    if avg_vol<=0: return True
    return volumes[-1] >= avg_vol*multiplier

def price_action_signal(closes, highs, lows, h1_closes, d1_closes):
    """
    محرك Price Action نقي:
    - يحدد الاتجاه من بنية الشموع (HH/HL أو LH/LL)
    - يدخل على ارتداد لـEMA20 (Pullback) في اتجاه D1 و H1
    - لا يعتمد على مؤشرات متأخرة
    """
    if len(closes)<30 or len(h1_closes)<20 or len(d1_closes)<10:
        return None

    # اتجاه D1 (الفلتر الأساسي)
    d1_e20=ema(d1_closes,20) if len(d1_closes)>=20 else d1_closes[-1]
    d1_dir="UP" if d1_closes[-1]>d1_e20 else "DOWN"

    # اتجاه H1
    h1_e20=ema(h1_closes,20) if len(h1_closes)>=20 else h1_closes[-1]
    h1_dir="UP" if h1_closes[-1]>h1_e20 else "DOWN"

    # يجب توافق D1 و H1
    if d1_dir!=h1_dir: return None

    price=closes[-1]
    e20=ema(closes,20)

    # تحديد بنية السوق على M15 (آخر 10 شموع)
    recent_highs=highs[-10:]
    recent_lows=lows[-10:]
    prev_highs=highs[-20:-10]
    prev_lows=lows[-20:-10]

    hh=max(recent_highs)>max(prev_highs)  # Higher High
    hl=min(recent_lows)>min(prev_lows)    # Higher Low
    lh=max(recent_highs)<max(prev_highs)  # Lower High
    ll=min(recent_lows)<min(prev_lows)    # Lower Low

    # شراء: D1+H1 صاعد + بنية صاعدة (HH+HL) + ارتداد لـEMA20
    if d1_dir=="UP" and hh and hl:
        if abs(price-e20)/e20 < 0.002:  # السعر قريب من EMA20 (0.2%)
            return "BUY"
        if price>e20 and closes[-2]<e20:  # كسر EMA20 للأعلى للتو
            return "BUY"

    # بيع: D1+H1 هابط + بنية هابطة (LH+LL) + ارتداد لـEMA20
    if d1_dir=="DOWN" and lh and ll:
        if abs(price-e20)/e20 < 0.002:  # السعر قريب من EMA20 (0.2%)
            return "SELL"
        if price<e20 and closes[-2]>e20:  # كسر EMA20 للأسفل للتو
            return "SELL"

    return None

def breakout_signal(closes, highs, lows, volumes, lookback=20):
    """إشارة كسر نطاق حقيقي: اختراق قمة/قاع آخر N شمعة مع تأكيد حجم 130%+"""
    if len(closes)<lookback+2 or not volumes: return None
    pivot_high=max(highs[-lookback-1:-1])
    pivot_low=min(lows[-lookback-1:-1])
    price=closes[-1]
    avg_vol=sum(volumes[-lookback-1:-1])/lookback
    vol_strong=avg_vol>0 and volumes[-1]>=avg_vol*1.3
    if price>pivot_high and vol_strong: return "BUY"
    if price<pivot_low  and vol_strong: return "SELL"
    return None

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
    closes,highs,lows,opens,volumes=get_data("15m","5d")
    if closes is None:
        print("فشل جلب البيانات"); return
    data=reset_daily_signal(data)
    data=check_last_signal(data,closes[-1])
    bu=data.get("breaker_until")
    if bu:
        until_dt=datetime.strptime(bu,"%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) < until_dt:
            print("⛔ قاطع الدائرة نشط حتى "+bu)
            data["last_check"]=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            data["last_reason"]="قاطع الدائرة نشط حتى "+bu
            save_data(data)
            return
        else:
            data["breaker_until"]=None
            data["consecutive_losses"]=0
            send_telegram("✅ انتهى إيقاف القاطع — البوت يعمل بشكل طبيعي الآن")
    min_sc=data["min_score"]

    # ─── المحرك الجديد: Price Action (أولوية عليا) ───
    h1_c,_,_,_,_=get_data("1h","15d")
    d1_c,_,_,_,_=get_data("1d","60d")
    pa_sig=price_action_signal(closes,highs,lows,
                                h1_c if h1_c else [],
                                d1_c if d1_c else [])
    if pa_sig and pa_sig!=data.get("last_signal"):
        atr=calc_atr(highs,lows,closes); price=closes[-1]
        is_buy_pa=pa_sig=="BUY"
        sl_pa=round(price-atr*ATR_SL if is_buy_pa else price+atr*ATR_SL,2)
        tp1_pa=round(price+atr*ATR_TP1 if is_buy_pa else price-atr*ATR_TP1,2)
        tp2_pa=round(price+atr*ATR_TP2 if is_buy_pa else price-atr*ATR_TP2,2)
        tp3_pa=round(price+atr*ATR_TP3 if is_buy_pa else price-atr*ATR_TP3,2)
        mh=max(highs[-20:]); ml=min(lows[-20:])
        tp_struct=round(mh,2) if is_buy_pa else round(ml,2)
        lot,size_label,target_risk,actual_risk=calc_lot(5,price,sl_pa)
        risk_warn="⚠️ " if actual_risk>target_risk*1.5 else ""
        now=syria_time_str()
        msg=(
            "🟢 Price Action XAUUSD M15 — إشارة\n"
            "========================\n"
            "السعر:    $"+str(round(price,2))+"\n"
            "الاتجاه:  "+("صاعد" if is_buy_pa else "هابط")+" (D1+H1+M15 متوافقة)\n"
            "الاشارة:  "+("شراء" if is_buy_pa else "بيع")+" (Price Action)\n\n"
            "========================\n"
            "وقف الخسارة: $"+str(sl_pa)+" (ATR×"+str(ATR_SL)+")\n"
            "TP1: $"+str(tp1_pa)+"\n"
            "TP2: $"+str(tp2_pa)+"\n"
            "TP3: $"+str(tp3_pa)+"\n"
            "🎯 هدف هيكلي (20 شمعة): $"+str(tp_struct)+"\n\n"
            "💰 "+size_label+" — "+str(lot)+" لوت\n"
            +risk_warn+"الخطر: "+str(actual_risk)+"% من $"+str(EQUITY)+"\n\n"
            "⚠️ استخدم سعر MT5 للدخول\n"
            "الوقت: "+now
        )
        if send_telegram(msg):
            data["last_signal"]=pa_sig
            data["last_price"]=price
            data["last_sl"]=sl_pa
            data["last_tp1"]=tp1_pa; data["last_tp2"]=tp2_pa; data["last_tp3"]=tp3_pa
            data["tp1_hit"]=False; data["tp2_hit"]=False
            data["last_time"]=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            data["last_reason"]="إشارة PA مُرسلة: "+pa_sig
        else:
            data["last_reason"]="فشل إرسال PA: "+LAST_TG_ERROR
        data["last_check"]=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        save_data(data); return

    # ─── المحرك القديم: المؤشرات ───
    r=analyze(closes,highs,lows,opens,min_sc)
    if r["st"]=="WAIT":
        bo_sig=breakout_signal(closes,highs,lows,volumes)
        if bo_sig and bo_sig!=data.get("last_signal"):
            atr=r["atr"]; price=closes[-1]; is_buy_bo=bo_sig=="BUY"
            sl_bo=round(price-atr*ATR_SL if is_buy_bo else price+atr*ATR_SL,2)
            tp1_bo=round(price+atr*ATR_TP1 if is_buy_bo else price-atr*ATR_TP1,2)
            tp2_bo=round(price+atr*ATR_TP2 if is_buy_bo else price-atr*ATR_TP2,2)
            tp3_bo=round(price+atr*ATR_TP3 if is_buy_bo else price-atr*ATR_TP3,2)
            mh=max(highs[-20:]); ml=min(lows[-20:])
            tp_struct=round(mh,2) if is_buy_bo else round(ml,2)
            lot,size_label,target_risk,actual_risk=calc_lot(4,price,sl_bo)
            risk_warn="⚠️ " if actual_risk>target_risk*1.5 else ""
            now=syria_time_str()
            msg=(
                "🔵 كسر نطاق XAUUSD M15 — إشارة Breakout\n"
                "========================\n"
                "السعر:    $"+str(round(price,2))+"\n"
                "الاتجاه:  "+("صاعد" if is_buy_bo else "هابط")+"\n"
                "الاشارة:  "+("شراء" if is_buy_bo else "بيع")+" (كسر نطاق+حجم)\n"
                "الحجم:    مرتفع ✅ (تأكيد الكسر)\n\n"
                "========================\n"
                "وقف الخسارة: $"+str(sl_bo)+" (ATR)\n"
                "TP1: $"+str(tp1_bo)+"\n"
                "TP2: $"+str(tp2_bo)+"\n"
                "TP3: $"+str(tp3_bo)+"\n"
                "🎯 هدف هيكلي (20 شمعة): $"+str(tp_struct)+"\n\n"
                "💰 حجم الصفقة المقترح: "+size_label+" — "+str(lot)+" لوت\n"
                +risk_warn+"الخطر الفعلي: "+str(actual_risk)+"% من $"+str(EQUITY)+"\n\n"
                "⚠️ استخدم سعر MT5 للدخول\n"
                "الوقت: "+now
            )
            if send_telegram(msg):
                data["last_signal"]=bo_sig
                data["last_price"]=price
                data["last_sl"]=sl_bo
                data["last_tp1"]=tp1_bo
                data["last_tp2"]=tp2_bo
                data["last_tp3"]=tp3_bo
                data["tp1_hit"]=False; data["tp2_hit"]=False
                data["last_time"]=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                data["last_reason"]="إشارة Breakout مُرسلة: "+bo_sig
            else:
                data["last_reason"]="فشل إرسال Breakout: "+LAST_TG_ERROR
            data["last_check"]=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            save_data(data); return
        print("لا اشارة | Score="+str(r["score"]))
        data["last_check"]=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        data["last_reason"]="لا اشارة (Score="+str(r["score"])+"/"+str(min_sc)+")"
        save_data(data); return
    if r["st"]==data["last_signal"]:
        print("نفس الاشارة")
        data["last_check"]=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        data["last_reason"]="نفس الاشارة السابقة ("+r["st"]+")"
        save_data(data); return
    is_buy="BUY" in r["st"]
    vol_ok=volume_confirms(volumes)
    vol_note="" if vol_ok else "\n⚠️ تحذير: حجم التداول منخفض — تأكد من صحة الدخول"
    filters=0; blocked=False; block_reason=""
    h1_dir,h1_note=get_h1_trend()
    if h1_dir=="UP" and is_buy:         filters+=1
    elif h1_dir=="DOWN" and not is_buy: filters+=1
    elif h1_dir=="NEUTRAL":             filters+=1
    else: blocked=True; block_reason="عكس H1"
    if not blocked:
        dxy_dir,dxy_note=get_dxy_trend()
        if dxy_dir=="DOWN" and is_buy:       filters+=1
        elif dxy_dir=="UP" and not is_buy:   filters+=1
        elif dxy_dir=="NEUTRAL":             filters+=1
        # تعارض DXY لا يمنع الصفقة بعد الآن، فقط لا يُحسب كنقطة تأكيد
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
    if not blocked:
        d1_dir,d1_note=get_d1_trend()
        if d1_dir=="DOWN" and is_buy:
            blocked=True; block_reason="D1 هابط — لا شراء عكس الاتجاه اليومي"
        elif d1_dir=="UP" and not is_buy:
            blocked=True; block_reason="D1 صاعد — لا بيع عكس الاتجاه اليومي"
    else:
        d1_dir,d1_note=get_d1_trend()
    if blocked:
        print("مرفوضة: "+block_reason)
        data["last_check"]=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        data["last_reason"]="مرفوضة ("+r["st"]+"): "+block_reason
        save_data(data); return
    regime,regime_note=detect_market_regime(closes,highs,lows)
    smc=analyze_smc(closes,highs,lows,opens,r["atr"],is_buy)
    total=data["total"]
    wr=round(data["wins"]/total*100) if total>0 else 0
    msg=build_msg(r,smc,h1_note,dxy_note,d1_note,
                  regime_note,filters,wr,total,min_sc,vol_note)
    if send_telegram(msg):
        print("✅ "+r["stx"]+" @ $"+str(r["price"]))
        data["last_signal"]=r["st"]
        data["last_price"]=r["price"]
        data["last_sl"]=smc["ob_sl"] if smc["ob_sl"] else r["lv"]["sl"]
        data["last_tp1"]=r["lv"]["tp1"]
        data["last_tp2"]=r["lv"]["tp2"]
        data["last_tp3"]=r["lv"]["tp3"]
        data["tp1_hit"]=False
        data["tp2_hit"]=False
        data["last_time"]=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        data["last_reason"]="إشارة مُرسلة: "+r["st"]
    else:
        data["last_reason"]="فشل إرسال Telegram: "+LAST_TG_ERROR
    data["last_check"]=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
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
