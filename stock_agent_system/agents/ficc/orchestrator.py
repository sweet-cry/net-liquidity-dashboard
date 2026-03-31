"""
FICC Sub-Orchestrator — v2
변경:
  1. CommodityAgent: 우라늄 → Yellowcake(Numerco) 스크래핑
  2. MacroRegimeAgent 연동용 DXY 실제값 반환
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.base_agent import BaseAgent


# ── Fixed Income Agent ────────────────────────────────────────
class FixedIncomeAgent(BaseAgent):
    TICKERS = {
        "us2y":  "^IRX",
        "us10y": "^TNX",
        "us30y": "^TYX",
    }

    def fetch(self) -> dict:
        try:
            import yfinance as yf
            result = {}
            for key, ticker in self.TICKERS.items():
                t = yf.Ticker(ticker)
                price = t.fast_info.get("last_price") or t.fast_info.get("lastPrice")
                result[key] = round(float(price), 3) if price else None
            result["kr_base_rate"] = 3.25
            spread = None
            if result.get("us10y") and result.get("us2y"):
                us2y_approx = result["us2y"] / 100 * 360 / 365 * 100
                spread = round(result["us10y"] - us2y_approx, 3)
            result["spread_10y2y"] = spread
            return result
        except Exception as e:
            self.logger.warning(f"yfinance 실패: {e}")
            return {"us2y": None, "us10y": None, "us30y": None,
                    "kr_base_rate": 3.25, "spread_10y2y": None}

    def analyze(self, data: dict) -> dict:
        us10y    = data.get("us10y")
        spread   = data.get("spread_10y2y")
        inverted = bool(spread < 0) if spread is not None else False
        return {
            "signal":    "주의" if inverted else "중립",
            "inversion": inverted,
            "us10y":     us10y,
            "us2y":      data.get("us2y"),
            "us30y":     data.get("us30y"),
            "spread":    spread,
            "summary":   (
                f"미국채 10Y {us10y}% | {'수익률곡선 역전 중' if inverted else '정상'}"
                if us10y else "데이터 조회 실패"
            ),
        }


# ── Currency Agent ────────────────────────────────────────────
class CurrencyAgent(BaseAgent):
    TICKERS = {
        "dxy":    "DX-Y.NYB",
        "usdkrw": "KRW=X",
        "usdjpy": "JPY=X",
        "eurusd": "EURUSD=X",
    }

    def fetch(self) -> dict:
        try:
            import yfinance as yf
            result = {}
            for key, ticker in self.TICKERS.items():
                t = yf.Ticker(ticker)
                price = t.fast_info.get("last_price") or t.fast_info.get("lastPrice")
                result[key] = round(float(price), 4) if price else None
            return result
        except Exception as e:
            self.logger.warning(f"yfinance 실패: {e}")
            return {"dxy": None, "usdkrw": None, "usdjpy": None, "eurusd": None}

    def analyze(self, data: dict) -> dict:
        dxy    = data.get("dxy")
        usdkrw = data.get("usdkrw")
        dollar_strong = bool(dxy > 103) if dxy else None
        return {
            "signal":        ("달러강세" if dollar_strong else "달러약세") if dollar_strong is not None else "조회실패",
            "dxy":           dxy,
            "usdkrw":        usdkrw,
            "usdjpy":        data.get("usdjpy"),
            "eurusd":        data.get("eurusd"),
            "dollar_strong": dollar_strong,
            "summary": (
                f"DXY {dxy} | 원달러 {usdkrw:,.1f}"
                if dxy and usdkrw else "데이터 조회 실패"
            ),
        }


# ── Commodity Agent ───────────────────────────────────────────
class CommodityAgent(BaseAgent):
    TICKERS = {
        "WTI":    "CL=F",
        "Gold":   "GC=F",
        "Silver": "SI=F",
        "NatGas": "NG=F",
    }
    YELLOWCAKE_URL = "https://www.yellowcakeplc.com/api/spotUraniumPrice.php"

    def fetch(self) -> dict:
        result = {}

        # yfinance 선물 데이터
        try:
            import yfinance as yf
            for name, ticker in self.TICKERS.items():
                t = yf.Ticker(ticker)
                price = t.fast_info.get("last_price") or t.fast_info.get("lastPrice")
                result[name] = round(float(price), 2) if price else None
        except Exception as e:
            self.logger.warning(f"yfinance 실패: {e}")
        # 우라늄 가격 — 3단계 폴백
        # 1순위: Yellowcake(Numerco 현물가 $/lb U3O8)
        # 2순위: SRUUF (Sprott Physical Uranium Trust)
        # 3순위: CCJ (Cameco 주가)
        uranium_price  = None
        uranium_source = None

        try:  # 1순위: Yellowcake
            import requests, re
            resp = requests.get(self.YELLOWCAKE_URL, timeout=5)
            resp.raise_for_status()
            m = re.search(r'US\$([\.\d]+)/lb', resp.text)
            if m:
                uranium_price  = float(m.group(1))
                uranium_source = "Numerco(Yellowcake)"
        except Exception as e:
            self.logger.warning(f"Yellowcake 실패: {e}")

        if uranium_price is None:  # 2순위: SRUUF
            try:
                import yfinance as yf
                p = yf.Ticker("SRUUF").fast_info.get("last_price")
                if p:
                    uranium_price  = round(float(p), 2)
                    uranium_source = "SRUUF(Sprott)"
            except Exception as e:
                self.logger.warning(f"SRUUF 실패: {e}")

        if uranium_price is None:  # 3순위: CCJ
            try:
                import yfinance as yf
                p = yf.Ticker("CCJ").fast_info.get("last_price")
                if p:
                    uranium_price  = round(float(p), 2)
                    uranium_source = "CCJ(fallback)"
            except Exception as e:
                self.logger.warning(f"CCJ 실패: {e}")

        result["Uranium_price"]  = uranium_price
        result["Uranium_source"] = uranium_source

        return result

    def analyze(self, data: dict) -> dict:
        wti     = data.get("WTI")
        gold    = data.get("Gold")
        uranium = data.get("Uranium_price")
        u_src   = data.get("Uranium_source", "")

        wti_signal  = ("강세" if wti  > 90 else "중립" if wti  > 70 else "약세") if wti  else "조회실패"
        gold_signal = ("강세" if gold > 2500 else "중립") if gold else "조회실패"
        u_display   = f"${uranium}/lb U3O8" if uranium else f"CCJ ${data.get('Uranium_CCJ_fallback','-')}"

        return {
            "WTI_price":    wti,
            "WTI_signal":   wti_signal,
            "Gold_price":   gold,
            "Gold_signal":  gold_signal,
            "Silver_price": data.get("Silver"),
            "NatGas_price": data.get("NatGas"),
            "Uranium_price": uranium,
            "Uranium_display": u_display,
            "Uranium_source":  u_src,
            "summary": (
                f"WTI ${wti:.1f} ({wti_signal}) | "
                f"금 ${gold:,.1f} ({gold_signal}) | "
                f"우라늄 {u_display}"
                if wti and gold else "데이터 조회 실패"
            ),
        }


# ── FICC Sub-Orchestrator ─────────────────────────────────────
class FICCOrchestrator:
    def __init__(self):
        self.fi_agent   = FixedIncomeAgent("FixedIncomeAgent")
        self.fx_agent   = CurrencyAgent("CurrencyAgent")
        self.comm_agent = CommodityAgent("CommodityAgent")

    def run(self) -> dict:
        fi   = self.fi_agent.run()
        fx   = self.fx_agent.run()
        comm = self.comm_agent.run()

        for agent in [self.fi_agent, self.fx_agent, self.comm_agent]:
            agent.save()

        return {
            "fixed_income": fi,
            "currency":     fx,
            "commodity":    comm,
            "ficc_summary": (
                f"금리: {fi.get('summary','')} | "
                f"FX: {fx.get('summary','')} | "
                f"원자재: {comm.get('summary','')}"
            ),
        }
