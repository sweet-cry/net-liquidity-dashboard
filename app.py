from flask import Flask, jsonify, send_file
from flask_cors import CORS
import yfinance as yf
import requests
from datetime import datetime, timedelta
import pytz

app = Flask(__name__)
CORS(app)

FRED_API_KEY = "3d022b35a44eabf7bb45dbdd9a1cfa01"
KST = pytz.timezone("Asia/Seoul")

# ── 유틸: FRED 최신값 가져오기 ─────────────────────────────
def fred_latest(series_id):
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 2,
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        obs = r.json().get("observations", [])
        vals = [o for o in obs if o["value"] != "."]
        if len(vals) >= 1:
            latest = float(vals[0]["value"])
            prev   = float(vals[1]["value"]) if len(vals) >= 2 else latest
            return latest, prev
    except Exception:
        pass
    return None, None

# ── 유틸: yfinance 최신 종가 ────────────────────────────────
def yf_price(ticker):
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="5d")
        hist = hist.dropna(subset=["Close"])  # NaN 행 제거
        if len(hist) >= 2:
            return float(hist["Close"].iloc[-1]), float(hist["Close"].iloc[-2])
        elif len(hist) == 1:
            return float(hist["Close"].iloc[-1]), float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None, None

# ── 유틸: Yellow Cake plc API → U3O8 현물가 $/lb ───────────
def fetch_u3o8_price():
    try:
        r = requests.get(
            "https://www.yellowcakeplc.com/api/spotUraniumPrice.php",
            timeout=10, headers={"User-Agent": "Mozilla/5.0"}
        )
        text = r.text
        # "US$83.75/lb" 패턴에서 숫자 추출
        import re
        m = re.search(r'US\$([0-9]+\.?[0-9]*)/lb', text)
        if m:
            price = float(m.group(1))
            # Daily Change "$-0.49" 패턴 추출
            chg_m = re.search(r'Daily Change[^\$]*\$([+-]?[0-9]+\.?[0-9]*)', text)
            chg = float(chg_m.group(1)) if chg_m else 0
            return price, price - chg
    except Exception:
        pass
    return None, None

# ── 유틸: pct 계산 (0~100 클램프) ─────────────────────────
def to_pct(val, lo, hi):
    if val is None:
        return 50
    return max(0, min(100, int((val - lo) / (hi - lo) * 100)))

# ── 유틸: sig 판단 ──────────────────────────────────────────
def sig(chg_pct, bull_th=0.3, bear_th=-0.3):
    if chg_pct is None:
        return "neut"
    if chg_pct > bull_th:
        return "bull"
    if chg_pct < bear_th:
        return "bear"
    return "neut"

def sector_signal(ret_1d):
    if ret_1d is None:
        return "neut"
    if ret_1d > 1.0:
        return "strong-bull"
    if ret_1d > 0.2:
        return "bull"
    if ret_1d < -1.0:
        return "strong-bear"
    if ret_1d < -0.2:
        return "bear"
    return "neut"

# ═══════════════════════════════════════════════════════════
# /api/macro
# ═══════════════════════════════════════════════════════════
@app.route("/api/macro")
def api_macro():
    # CPI YoY — 지수값 2개 가져와서 직접 계산
    def fred_series_2(series_id, limit=13):
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {"series_id": series_id, "api_key": FRED_API_KEY,
                  "file_type": "json", "sort_order": "desc", "limit": limit}
        try:
            r = requests.get(url, params=params, timeout=10)
            obs = [o for o in r.json().get("observations", []) if o["value"] != "."]
            return [float(o["value"]) for o in obs]
        except Exception:
            return []

    cpi_vals = fred_series_2("CPIAUCSL", 14)
    if len(cpi_vals) >= 13:
        cpi_yoy = round((cpi_vals[0] - cpi_vals[12]) / cpi_vals[12] * 100, 1)
    else:
        cpi_yoy = None

    # ISM Manufacturing — MANEMP 대신 ISLMPMF (ISM PMI) 또는 NAPMPI 시도
    ism, ism_prev = fred_latest("MANEMP")   # 제조업 고용 (proxy)
    # 실제 ISM PMI는 유료라 FRED에 없음 → T10Y2Y 기반 proxy 사용
    # 대신 Industrial Production Index로 경기 판단
    ip, ip_prev = fred_latest("INDPRO")
    # ISM proxy: IP 전월비 → 50 기준 스케일링
    if ip and ip_prev and ip_prev > 0:
        ip_mom = (ip - ip_prev) / ip_prev * 100
        ism_proxy = round(50 + ip_mom * 10, 1)  # 대략적 PMI 근사
        ism_proxy = max(35, min(65, ism_proxy))
    else:
        ism_proxy = None

    # Yield Curve 2s10s (T10Y2Y)
    yc, yc_prev = fred_latest("T10Y2Y")

    # CLI (OECD Leading Indicator)
    cli, cli_prev = fred_latest("USALOLITONOSTSAM")

    # ism_proxy를 ism으로 사용
    ism = ism_proxy

    # Regime 판단 로직
    regime = "LATE CYCLE"
    sub    = "데이터 기반 판단"
    badge  = "CAUTION"

    if yc is not None:
        if yc < 0 and (cpi_yoy and cpi_yoy > 3.0):
            regime, sub, badge = "STAGFLATION", "침체 압력 / 스태그플레이션", "BEARISH"
        elif yc < 0:
            regime, sub, badge = "LATE CYCLE",  "성장 둔화 / 역전 커브 지속", "CAUTION"
        elif yc > 0.5 and (cpi_yoy and cpi_yoy < 3.0):
            regime, sub, badge = "EXPANSION",   "성장 가속 / 물가 안정",      "BULLISH"
        elif yc > 0.5 and (cpi_yoy and cpi_yoy >= 3.0):
            regime, sub, badge = "OVERHEATING", "성장 호조 / 인플레 압력",    "CAUTION"
        else:
            regime, sub, badge = "RECOVERY",    "경기 회복 초입 / 정책 완화 기대", "WATCH"

    indicators = [
        {
            "label": "ISM (proxy)",
            "val":   f"{ism:.1f}" if ism else "N/A",
            "color": "#3fb950" if (ism and ism > 50) else "#f85149",
            "pct":   to_pct(ism, 40, 65),
        },
        {
            "label": "CPI YoY",
            "val":   f"{cpi_yoy:.1f}%" if cpi_yoy is not None else "N/A",
            "color": "#f85149" if (cpi_yoy and cpi_yoy > 3.0) else "#C9A84C",
            "pct":   to_pct(cpi_yoy, 0, 8),
        },
        {
            "label": "Yield Curve",
            "val":   f"{yc:.2f}" if yc else "N/A",
            "color": "#f85149" if (yc and yc < 0) else "#3fb950",
            "pct":   to_pct(yc, -2, 2),
        },
        {
            "label": "CLI",
            "val":   f"{cli:.1f}" if cli else "N/A",
            "color": "#3fb950" if (cli and cli > 100) else "#8b949e",
            "pct":   to_pct(cli, 96, 104),
        },
    ]

    # 판단 근거 텍스트 생성
    reasons = []
    if yc is not None:
        reasons.append(f"Yield Curve {yc:.2f}% ({'역전' if yc < 0 else '정상'})")
    if cpi_yoy is not None:
        reasons.append(f"CPI YoY {cpi_yoy:.1f}%")
    if cli is not None:
        reasons.append(f"CLI {cli:.1f} ({'선행↑' if cli > 100 else '선행↓'})")
    regime_reason = " · ".join(reasons) if reasons else "FRED 데이터 기반 자동 판단"

    return jsonify({
        "regime":        regime,
        "sub":           sub,
        "badge":         badge,
        "indicators":    indicators,
        "regime_reason": regime_reason,
    })

# ═══════════════════════════════════════════════════════════
# /api/ficc
# ═══════════════════════════════════════════════════════════
@app.route("/api/ficc")
def api_ficc():
    # ── Rates: FRED에서 직접 가져오기 (yfinance ^IRX/^TNX는 단위 불안정) ──
    r2y_val,  r2y_prev  = fred_latest("DGS2")    # 2Y CMT %
    r10y_val, r10y_prev = fred_latest("DGS10")   # 10Y CMT %
    r30y_val, r30y_prev = fred_latest("DGS30")   # 30Y CMT %
    yc_val,   _         = fred_latest("T10Y2Y")  # 2s10s spread %

    def rate_chg(v, p):
        if v and p:
            bp = round((v - p) * 100)
            return f"+{bp}bp" if bp >= 0 else f"{bp}bp"
        return ""

    spr = round(yc_val, 2) if yc_val else (
        round(r10y_val - r2y_val, 2) if (r10y_val and r2y_val) else None
    )

    rates = [
        {"name": "US 2Y",        "val": f"{r2y_val:.2f}%"  if r2y_val  else "N/A",
         "sig": "bear" if (r2y_val  and r2y_val  > 4.0) else "neut",
         "chg": rate_chg(r2y_val, r2y_prev)},
        {"name": "US 10Y",       "val": f"{r10y_val:.2f}%" if r10y_val else "N/A",
         "sig": "bear" if (r10y_val and r10y_val > 4.2) else "neut",
         "chg": rate_chg(r10y_val, r10y_prev)},
        {"name": "2s10s Spread", "val": f"{int(spr*100)}bp" if spr else "N/A",
         "sig": "bear" if (spr and spr < 0) else "neut", "chg": ""},
        {"name": "TIPS (30Y)",   "val": f"{r30y_val:.2f}%" if r30y_val else "N/A",
         "sig": "neut", "chg": rate_chg(r30y_val, r30y_prev)},
    ]

    # ── FX ────────────────────────────────────────────────
    dxy,  dxy_p  = yf_price("DX-Y.NYB")
    krw,  krw_p  = yf_price("KRW=X")
    jpy,  jpy_p  = yf_price("JPY=X")
    eurusd, eu_p = yf_price("EURUSD=X")

    def chg_str(v, p, fmt="{:.2f}%"):
        if v and p and p != 0:
            c = (v - p) / p * 100
            return f"+{c:.2f}%" if c >= 0 else f"{c:.2f}%"
        return ""

    fx = [
        {"name": "DXY",     "val": f"{dxy:.1f}"  if dxy  else "N/A",
         "sig": sig((dxy-dxy_p)/dxy_p*100 if dxy and dxy_p else None), "chg": chg_str(dxy, dxy_p)},
        {"name": "USD/KRW", "val": f"{krw:,.0f}" if krw  else "N/A",
         "sig": "bear" if (krw and krw > 1350) else "neut", "chg": chg_str(krw, krw_p)},
        {"name": "USD/JPY", "val": f"{jpy:.1f}"  if jpy  else "N/A",
         "sig": sig((jpy-jpy_p)/jpy_p*100 if jpy and jpy_p else None), "chg": chg_str(jpy, jpy_p)},
        {"name": "EUR/USD", "val": f"{eurusd:.3f}" if eurusd else "N/A",
         "sig": sig((eurusd-eu_p)/eu_p*100 if eurusd and eu_p else None), "chg": chg_str(eurusd, eu_p)},
    ]

    # ── Commodities ────────────────────────────────────────
    wti, wti_p   = yf_price("CL=F")
    gold, gold_p = yf_price("GC=F")
    ura, ura_p   = fetch_u3o8_price()  # Yellow Cake plc API → U3O8 현물가 $/lb
    cop, cop_p   = yf_price("HG=F")

    commodities = [
        {"name": "WTI Crude",   "val": f"{wti:.1f}"  if wti  else "N/A",
         "sig": sig((wti-wti_p)/wti_p*100   if wti  and wti_p  else None), "chg": chg_str(wti, wti_p)},
        {"name": "Gold",        "val": f"{gold:,.0f}" if gold else "N/A",
         "sig": sig((gold-gold_p)/gold_p*100 if gold and gold_p else None), "chg": chg_str(gold, gold_p)},
        {"name": "Uranium U3O8",  "val": f"${ura:.2f}/lb" if ura else "N/A",
         "sig": "watch", "chg": chg_str(ura, ura_p)},
        {"name": "Copper",      "val": f"{cop:.2f}"  if cop  else "N/A",
         "sig": sig((cop-cop_p)/cop_p*100   if cop  and cop_p  else None), "chg": chg_str(cop, cop_p)},
    ]

    return jsonify({"rates": rates, "fx": fx, "commodities": commodities})

# ═══════════════════════════════════════════════════════════
# /api/equity
# ═══════════════════════════════════════════════════════════
SECTOR_TICKERS = [
    ("Tech",      "XLK"),
    ("Energy",    "XLE"),
    ("Semis",     "SOXX"),
    ("Finance",   "XLF"),
    ("Health",    "XLV"),
    ("Util",      "XLU"),
    ("RE",        "IYR"),
    ("Cons.Disc", "XLY"),
    ("Cons.Stpl", "XLP"),
    ("Materials", "XLB"),
    ("Telecom",   "XLC"),
    ("Aero",      "ITA"),
]

def build_equity_simple():
    result = []
    for sector, ticker in SECTOR_TICKERS:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="35d").dropna(subset=["Close"])
            if len(hist) < 2:
                result.append({"sector": sector, "score": "N/A", "signal": "neut"})
                continue
            closes = hist["Close"].values
            now    = float(closes[-1])
            prev1d = float(closes[-2])
            prev1w = float(closes[max(0, len(closes)-6)])
            prev1m = float(closes[0])

            ret_1d = (now - prev1d) / prev1d * 100
            ret_1w = (now - prev1w) / prev1w * 100
            ret_1m = (now - prev1m) / prev1m * 100

            # 복합 점수: 1D(30%) + 1W(40%) + 1M(30%)
            composite = round(ret_1d * 0.3 + ret_1w * 0.4 + ret_1m * 0.3, 1)
            score  = f"+{composite}" if composite >= 0 else f"{composite}"
            signal = sector_signal(composite)
            result.append({"sector": sector, "score": score, "signal": signal})
        except Exception:
            result.append({"sector": sector, "score": "N/A", "signal": "neut"})
    return result

def build_equity_weighted(simple):
    # 가중 모드: 시총 가중 (여기선 간단히 섹터별 가중치 적용)
    weights = {
        "Tech": 1.3, "Semis": 1.2, "Energy": 1.1, "Finance": 1.0,
        "Health": 0.9, "Util": 0.7, "RE": 0.7, "Cons.Disc": 0.9,
        "Cons.Stpl": 0.8, "Materials": 1.0, "Telecom": 0.8, "Aero": 1.1,
    }
    result = []
    for item in simple:
        try:
            raw = float(item["score"])
            w   = weights.get(item["sector"], 1.0)
            adj = raw * w
            score  = f"+{adj:.1f}" if adj >= 0 else f"{adj:.1f}"
            signal = sector_signal(adj)
        except (ValueError, TypeError):
            score, signal = item["score"], item["signal"]
        result.append({"sector": item["sector"], "score": score, "signal": signal})
    return result

def build_equity_regime(simple, regime):
    # 레짐 모드: 레짐에 따라 방어/공격 섹터 조정
    offense  = {"Tech", "Semis", "Energy", "Finance", "Aero", "Materials"}
    defense  = {"Health", "Util", "Cons.Stpl"}

    result = []
    for item in simple:
        try:
            raw = float(item["score"])
            if regime in ("EXPANSION", "RECOVERY", "OVERHEATING"):
                adj = raw * 1.2 if item["sector"] in offense else raw * 0.8
            else:
                adj = raw * 0.7 if item["sector"] in offense else raw * 1.3
            score  = f"+{adj:.1f}" if adj >= 0 else f"{adj:.1f}"
            signal = sector_signal(adj)
        except (ValueError, TypeError):
            score, signal = item["score"], item["signal"]
        result.append({"sector": item["sector"], "score": score, "signal": signal})
    return result

@app.route("/api/equity")
def api_equity():
    simple = build_equity_simple()

    # 현재 레짐 참조 (간단히 FRED T10Y2Y 기반)
    yc, _ = fred_latest("T10Y2Y")
    regime = "LATE CYCLE" if (yc and yc < 0) else "EXPANSION"

    return jsonify({
        "simple":   simple,
        "weighted": build_equity_weighted(simple),
        "regime":   build_equity_regime(simple, regime),
    })

# ═══════════════════════════════════════════════════════════
# /api/risk
# ═══════════════════════════════════════════════════════════
@app.route("/api/risk")
def api_risk():
    vix, vix_p = yf_price("^VIX")

    # VIX 레벨 해석
    if vix:
        if vix > 30:   vix_sub, vix_col = "Extreme Fear",  "#f85149"
        elif vix > 20: vix_sub, vix_col = "Elevated",      "#C9A84C"
        elif vix > 15: vix_sub, vix_col = "Normal",        "#8b949e"
        else:          vix_sub, vix_col = "Complacent",    "#3fb950"
    else:
        vix_sub, vix_col = "N/A", "#8b949e"

    # IG Credit Spread proxy (LQD vs IEI spread)
    lqd, lqd_p = yf_price("LQD")
    iei, iei_p = yf_price("IEI")
    cs_val = "N/A"
    cs_col = "#8b949e"
    cs_pct = 40
    if lqd and iei:
        # LQD yield - IEI yield 근사 (직접 계산 어려우므로 가격 비율 proxy)
        cs_val = f"{round((lqd/iei)*10, 1)}bp"
        cs_col = "#C9A84C"

    gauges = [
        {
            "label": "VIX",
            "val":   f"{vix:.1f}" if vix else "N/A",
            "sub":   vix_sub,
            "color": vix_col,
            "pct":   to_pct(vix, 10, 45),
        },
        {
            "label": "Credit Spread",
            "val":   cs_val,
            "sub":   "LQD/IEI proxy",
            "color": cs_col,
            "pct":   cs_pct,
        },
    ]

    # 섹터 집중도 (상위 2개 섹터 비중)
    tech_ret, _ = yf_price("XLK")
    ene_ret, _  = yf_price("XLE")

    items = [
        {
            "name":   "VIX 전일 대비",
            "val":    f"{vix:.1f}" if vix else "N/A",
            "dot":    "#f85149" if (vix and vix > 20) else "#3fb950",
            "chg":    f"{'▲' if (vix and vix_p and vix>vix_p) else '▼'} {abs(round(vix-vix_p,1)) if vix and vix_p else ''}",
            "chgCol": "#f85149" if (vix and vix_p and vix > vix_p) else "#3fb950",
        },
        {
            "name":   "Tech (XLK) 노출",
            "val":    f"{tech_ret:.2f}" if tech_ret else "N/A",
            "dot":    "#C9A84C",
            "chg":    "— 모니터링",
            "chgCol": "#8b949e",
        },
        {
            "name":   "Energy (XLE) 노출",
            "val":    f"{ene_ret:.2f}" if ene_ret else "N/A",
            "dot":    "#C9A84C",
            "chg":    "— 모니터링",
            "chgCol": "#8b949e",
        },
        {
            "name":   "Yield Curve 리스크",
            "val":    "역전" if (fred_latest("T10Y2Y")[0] or 0) < 0 else "정상",
            "dot":    "#f85149" if (fred_latest("T10Y2Y")[0] or 0) < 0 else "#3fb950",
            "chg":    f"{fred_latest('T10Y2Y')[0]:.2f}bp" if fred_latest("T10Y2Y")[0] else "N/A",
            "chgCol": "#8b949e",
        },
        {
            "name":   "Tail Risk (VIX>30)",
            "val":    "HIGH" if (vix and vix > 30) else "LOW",
            "dot":    "#f85149" if (vix and vix > 30) else "#3fb950",
            "chg":    "▲ WARNING" if (vix and vix > 30) else "— STABLE",
            "chgCol": "#f85149" if (vix and vix > 30) else "#8b949e",
        },
    ]

    # 판단 근거
    risk_reasons = []
    if vix:
        risk_reasons.append(f"VIX {vix:.1f} ({vix_sub})")
    if vix and vix > 20:
        risk_reasons.append("변동성 임계치(20) 초과")
    yc_r, _ = fred_latest("T10Y2Y")
    if yc_r is not None and yc_r < 0:
        risk_reasons.append(f"Yield Curve {yc_r:.2f}% 역전")
    risk_reason = " · ".join(risk_reasons) if risk_reasons else "VIX·크레딧 스프레드 기반 판단"

    return jsonify({"gauges": gauges, "items": items, "risk_reason": risk_reason})

# ═══════════════════════════════════════════════════════════
# /api/briefing
# ═══════════════════════════════════════════════════════════
@app.route("/api/briefing")
def api_briefing():
    now_kst = datetime.now(KST).strftime("%H:%M")

    items = []

    # VIX 기반 리스크 멘트
    vix, vix_p = yf_price("^VIX")
    if vix:
        level = "급등 — 리스크 오프 경고" if vix > 30 else ("상승 — 변동성 주의" if vix > 20 else "안정적")
        items.append({
            "time": now_kst, "tag": "RISK",
            "tagCol": "#f85149", "tagBg": "rgba(248,81,73,0.1)",
            "text": f"<strong>VIX {vix:.1f}</strong> — {level}. 전일 대비 {'+' if vix>vix_p else ''}{round(vix-vix_p,1) if vix_p else 'N/A'} 변동."
        })

    # WTI 기반 에너지 멘트
    wti, wti_p = yf_price("CL=F")
    if wti and wti_p:
        chg = (wti - wti_p) / wti_p * 100
        items.append({
            "time": now_kst, "tag": "ENERGY",
            "tagCol": "#3fb950", "tagBg": "rgba(63,185,80,0.1)",
            "text": f"<strong>WTI ${wti:.1f}</strong> — 전일 대비 {'+' if chg>=0 else ''}{chg:.2f}%. {'상승 모멘텀 지속.' if chg>0 else '단기 조정 구간.'} Bits→Atoms 테마 모니터링."
        })

    # Gold 멘트
    gold, gold_p = yf_price("GC=F")
    if gold and gold_p:
        chg = (gold - gold_p) / gold_p * 100
        items.append({
            "time": now_kst, "tag": "GOLD",
            "tagCol": "#C9A84C", "tagBg": "rgba(201,168,76,0.12)",
            "text": f"<strong>Gold ${gold:,.0f}</strong> — {'+' if chg>=0 else ''}{chg:.2f}%. {'달러 강세 속 상승은 안전자산 수요 강함.' if chg>0 else '달러 강세 압력.'}"
        })

    # USD/KRW 멘트
    krw, krw_p = yf_price("KRW=X")
    if krw:
        items.append({
            "time": now_kst, "tag": "FX",
            "tagCol": "#bc8cff", "tagBg": "rgba(188,140,255,0.1)",
            "text": f"<strong>USD/KRW {krw:,.0f}</strong> — {'원화 약세 지속. 수출기업 헤지 비용 확인 필요.' if krw > 1350 else '원화 안정권 유지.'}"
        })

    # Yield Curve 멘트
    yc, _ = fred_latest("T10Y2Y")
    if yc is not None:
        items.append({
            "time": now_kst, "tag": "RATES",
            "tagCol": "#58a6ff", "tagBg": "rgba(88,166,255,0.1)",
            "text": f"<strong>2s10s Spread {yc:.2f}%</strong> — {'역전 커브 지속. 경기 침체 선행 시그널 모니터링.' if yc < 0 else '커브 정상화 진행 중.'}"
        })

    # 폴백: 데이터 없으면 기본 멘트
    if not items:
        items.append({
            "time": now_kst, "tag": "SYSTEM",
            "tagCol": "#8b949e", "tagBg": "rgba(139,148,158,0.1)",
            "text": "시장 데이터를 불러오는 중입니다. 잠시 후 새로고침 해주세요."
        })

    return jsonify(items)

# ═══════════════════════════════════════════════════════════
# /api/feargreed  (CNN Fear & Greed 스크래핑)
# ═══════════════════════════════════════════════════════════
@app.route("/api/feargreed")
def api_feargreed():
    score = None
    label = None
    prev  = None
    indicators = []

    INDICATOR_KO = {
        "market_momentum_sp500": "시장 모멘텀 (S&P500)",
        "stock_price_strength":  "주가 강도",
        "stock_price_breadth":   "주가 폭 (McClellan)",
        "put_call_options":      "풋/콜 비율",
        "market_volatility_vix": "시장 변동성 (VIX)",
        "junk_bond_demand":      "정크본드 수요",
        "safe_haven_demand":     "안전자산 수요",
    }

    def score_to_color(s):
        if s >= 75:   return "#3fb950"
        elif s >= 55: return "#6ec87a"
        elif s >= 45: return "#C9A84C"
        elif s >= 25: return "#f47068"
        else:         return "#f85149"

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers=headers, timeout=10
        )
        data = r.json()

        # 메인 점수 + history
        fg = data.get("fear_and_greed", {})
        score = round(float(fg.get("score", 0)))
        prev  = round(float(fg.get("previous_close", score)))
        label = fg.get("rating", "")

        # 7개 지표 — 최상위 레벨에 직접 존재
        for key, name_ko in INDICATOR_KO.items():
            ind_data = data.get(key, {})
            if isinstance(ind_data, dict):
                indicators.append({
                    "key":    key,
                    "name":   name_ko,
                    "score":  round(float(ind_data.get("score", 0))),
                    "rating": ind_data.get("rating", ""),
                })

    except Exception:
        pass

    # fallback
    if score is None:
        try:
            vix, _ = yf_price("^VIX")
            spy, spy_p = yf_price("SPY")
            vix_score = max(0, min(100, int((40 - (vix or 20)) / 30 * 100)))
            mom_score = 50
            if spy and spy_p and spy_p > 0:
                chg = (spy - spy_p) / spy_p * 100
                mom_score = max(0, min(100, int(50 + chg * 10)))
            score = round((vix_score + mom_score) / 2)
            prev  = score
        except Exception:
            score, prev = 50, 50

    if not label:
        if score >= 75:   label = "Extreme Greed"
        elif score >= 55: label = "Greed"
        elif score >= 45: label = "Neutral"
        elif score >= 25: label = "Fear"
        else:             label = "Extreme Fear"

    chg = score - prev
    return jsonify({
        "score":      score,
        "prev":       prev,
        "chg":        chg,
        "label":      label,
        "color":      score_to_color(score),
        "indicators": indicators,
    })

# ═══════════════════════════════════════════════════════════
# /api/ficc_history  (FICC 항목별 1W/1M 히스토리)
# ═══════════════════════════════════════════════════════════
def yf_history(ticker, multiplier=1.0):
    """5주치 종가 반환 → [d-30, d-21, d-14, d-7, d-1, today] 6포인트"""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="35d").dropna(subset=["Close"])
        closes = [round(float(v) * multiplier, 4) for v in hist["Close"].values]
        if len(closes) < 2:
            return []
        # 6개 포인트 균등 샘플링
        n = len(closes)
        idxs = [0, n//5, 2*n//5, 3*n//5, 4*n//5, n-1]
        return [closes[i] for i in idxs]
    except Exception:
        return []

@app.route("/api/ficc_history")
def api_ficc_history():
    result = {}

    # Rates
    irx_h  = yf_history("^IRX", 0.1)
    tnx_h  = yf_history("^TNX", 0.1)
    tyx_h  = yf_history("^TYX", 0.1)
    result["US 2Y"]        = irx_h
    result["US 10Y"]       = tnx_h
    result["TIPS (30Y)"]   = tyx_h
    result["2s10s Spread"] = []  # FRED 기반이라 생략

    # FX
    result["DXY"]     = yf_history("DX-Y.NYB")
    result["USD/KRW"] = yf_history("KRW=X")
    result["USD/JPY"] = yf_history("JPY=X")
    result["EUR/USD"] = yf_history("EURUSD=X")

    # Commodities
    result["WTI Crude"]    = yf_history("CL=F")
    result["Gold"]         = yf_history("GC=F")
    result["Uranium U3O8"] = []  # Yellow Cake API 히스토리 없음
    result["Copper"]       = yf_history("HG=F")

    # 1W전·1M전 가격도 함께
    def price_points(h):
        if not h or len(h) < 6:
            return {"w1": None, "m1": None, "spark": h or []}
        return {"w1": h[-2], "m1": h[0], "spark": h}

    return jsonify({k: price_points(v) for k, v in result.items()})

# ═══════════════════════════════════════════════════════════
# /api/rotation  (섹터 로테이션 데이터)
# ═══════════════════════════════════════════════════════════
SECTOR_TICKERS_ROTATION = [
    ("Tech","XLK"),("Energy","XLE"),("Semis","SOXX"),("Finance","XLF"),
    ("Health","XLV"),("Util","XLU"),("RE","IYR"),("Cons.Disc","XLY"),
    ("Cons.Stpl","XLP"),("Materials","XLB"),("Telecom","XLC"),("Aero","ITA"),
]

@app.route("/api/rotation")
def api_rotation():
    sectors = []
    for sector, ticker in SECTOR_TICKERS_ROTATION:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="35d").dropna(subset=["Close"])
            if len(hist) < 2:
                continue
            closes = hist["Close"].values
            now    = float(closes[-1])
            prev1d = float(closes[-2])
            prev1w = float(closes[max(0, len(closes)-6)])
            prev1m = float(closes[0])
            ret_1d = round((now - prev1d) / prev1d * 100, 2)
            ret_1w = round((now - prev1w) / prev1w * 100, 2)
            ret_1m = round((now - prev1m) / prev1m * 100, 2)
            sectors.append({
                "sector": sector,
                "ticker": ticker,
                "ret_1d": ret_1d,
                "ret_1w": ret_1w,
                "ret_1m": ret_1m,
            })
        except Exception:
            continue

    # 레짐 판단 — NAPM 폐지됨, T10Y2Y + IP 기반으로 판단
    yc, _ = fred_latest("T10Y2Y")
    ip, ip_prev = fred_latest("INDPRO")
    ip_mom = round((ip - ip_prev) / ip_prev * 100, 2) if (ip and ip_prev and ip_prev > 0) else None

    if yc is not None and ip_mom is not None:
        if yc > 0.5 and ip_mom > 0.1:
            cycle = "EARLY"
            cycle_reason = f"Yield Curve +{yc:.2f}% (정상) · IP 전월비 +{ip_mom:.2f}% (성장)"
        elif yc > 0 and ip_mom >= 0:
            cycle = "MID"
            cycle_reason = f"Yield Curve +{yc:.2f}% (정상) · IP 전월비 {ip_mom:.2f}%"
        elif yc < 0 or ip_mom < 0:
            cycle = "LATE"
            cycle_reason = f"Yield Curve {yc:.2f}% ({'역전' if yc < 0 else '정상'}) · IP 전월비 {ip_mom:.2f}%"
        else:
            cycle = "MID"
            cycle_reason = f"Yield Curve {yc:.2f}% · IP 전월비 {ip_mom:.2f}%"
    elif yc is not None:
        if yc > 0.5:   cycle, cycle_reason = "EARLY", f"Yield Curve +{yc:.2f}% (정상 커브)"
        elif yc > 0:   cycle, cycle_reason = "MID",   f"Yield Curve +{yc:.2f}% (완만)"
        else:          cycle, cycle_reason = "LATE",  f"Yield Curve {yc:.2f}% (역전 커브)"
    else:
        cycle, cycle_reason = "LATE", "데이터 부족 — Yield Curve 기준 LATE 적용"

    return jsonify({"sectors": sectors, "cycle": cycle, "cycle_reason": cycle_reason})

# ═══════════════════════════════════════════════════════════
# /api/all
# ═══════════════════════════════════════════════════════════
@app.route("/api/all")
def api_all():
    with app.test_request_context():
        return jsonify({
            "macro":        api_macro().get_json(),
            "ficc":         api_ficc().get_json(),
            "ficc_history": api_ficc_history().get_json(),
            "equity":       api_equity().get_json(),
            "risk":         api_risk().get_json(),
            "briefing":     api_briefing().get_json(),
            "feargreed":    api_feargreed().get_json(),
            "rotation":     api_rotation().get_json(),
        })

@app.route("/api/debug_fg")
def debug_fg():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
    r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata", headers=headers, timeout=10)
    d = r.json()
    fg = d.get("fear_and_greed", {})
    return jsonify({
        "top_keys": list(d.keys()),
        "fg_keys": list(fg.keys()),
        "sample_vix": d.get("market_volatility_vix", {}),
        "sample_momentum": d.get("market_momentum_sp500", {}),
    })

@app.route("/")
def dashboard():
    return send_file("StockAgent_Dashboard.html")

@app.route("/health")
def health():
    return "ok"

if __name__ == "__main__":
    app.run(debug=True, port=5000)
