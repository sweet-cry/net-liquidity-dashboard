"""
Macro Regime Agent — v2
변경:
  1. ASSET_BIAS fx → 실제 DXY 기반 동적 판단
  2. Stagflation 신뢰도 로직 개선
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.base_agent import BaseAgent

FRED_KEY = "3d022b35a44eabf7bb45dbdd9a1cfa01"


class MacroRegimeAgent(BaseAgent):
    REGIMES = {
        (True,  True):  "Reflation",
        (True,  False): "Goldilocks",
        (False, True):  "Stagflation",
        (False, False): "Risk-Off",
    }

    # fx는 동적으로 계산 — 여기선 나머지만 고정
    ASSET_BIAS_BASE = {
        "Reflation":  {"equity":"중립",  "bond":"축소", "commodity":"확대", "gold":"강세"},
        "Goldilocks": {"equity":"확대",  "bond":"중립", "commodity":"중립", "gold":"중립"},
        "Stagflation":{"equity":"축소",  "bond":"축소", "commodity":"확대", "gold":"강세"},
        "Risk-Off":   {"equity":"축소",  "bond":"확대", "commodity":"축소", "gold":"강세"},
    }

    def fetch(self) -> dict:
        result = {}

        # yfinance: VIX, DXY, US10Y
        try:
            import yfinance as yf
            for key, ticker in [("vix","^VIX"), ("dxy","DX-Y.NYB"), ("us10y","^TNX")]:
                t = yf.Ticker(ticker)
                price = t.fast_info.get("last_price") or t.fast_info.get("lastPrice")
                result[key] = round(float(price), 2) if price else None
        except Exception as e:
            self.logger.warning(f"yfinance 실패: {e}")

        # FRED: CPI, GDP, 실업률
        try:
            import fredapi
            fred = fredapi.Fred(api_key=FRED_KEY)

            cpi = fred.get_series("CPIAUCSL", limit=13)
            if len(cpi) >= 13:
                result["cpi_yoy"] = round(((cpi.iloc[-1] / cpi.iloc[-13]) - 1) * 100, 2)

            gdp = fred.get_series("A191RL1Q225SBEA", limit=2)
            if len(gdp) >= 1:
                result["gdp_qoq"] = round(float(gdp.iloc[-1]), 2)

            unemp = fred.get_series("UNRATE", limit=2)
            if len(unemp) >= 1:
                result["unemployment"] = round(float(unemp.iloc[-1]), 1)

        except Exception as e:
            self.logger.warning(f"FRED 실패: {e}")

        # 폴백 기본값
        result.setdefault("vix",         20.0)
        result.setdefault("cpi_yoy",      3.2)
        result.setdefault("gdp_qoq",      2.1)
        result.setdefault("ism_pmi",     51.3)
        result.setdefault("unemployment", 4.1)
        return result

    def analyze(self, data: dict) -> dict:
        growth_up  = bool(
            data.get("gdp_qoq", 0) > 2.0 and
            data.get("ism_pmi",  0) > 50
        )
        inflate_up = bool(data.get("cpi_yoy", 0) > 3.0)

        regime = self.REGIMES[(growth_up, inflate_up)]
        bias   = dict(self.ASSET_BIAS_BASE[regime])  # 복사

        # ── DXY 실제값 기반 달러 방향성 동적 반영 ──────────────
        dxy = data.get("dxy")
        if dxy is not None:
            bias["fx"] = "달러강세" if dxy > 103 else "달러약세"
        else:
            # DXY 조회 실패 시 Regime 기본값
            defaults = {
                "Reflation": "달러약세", "Goldilocks": "달러약세",
                "Stagflation": "달러강세", "Risk-Off": "달러강세",
            }
            bias["fx"] = defaults[regime]

        confidence = self._calc_confidence(data, regime)

        return {
            "regime":      regime,
            "confidence":  confidence,
            "growth_up":   growth_up,
            "inflate_up":  inflate_up,
            "asset_bias":  bias,
            "indicators":  data,
            "summary": (
                f"{regime} 국면 (신뢰도 {confidence}%) — "
                f"주식 {bias['equity']} / 금 {bias['gold']} / "
                f"달러 {bias['fx']} (DXY {dxy})"
            ),
        }

    def _calc_confidence(self, d: dict, regime: str) -> int:
        score = 50
        gdp = d.get("gdp_qoq", 2.0)
        cpi = d.get("cpi_yoy", 3.0)
        vix = d.get("vix", 20)

        # 수치가 경계값에서 멀수록 신뢰도 상승
        if abs(gdp - 2.0) > 1.5: score += 20
        elif abs(gdp - 2.0) > 0.8: score += 10

        if abs(cpi - 3.0) > 1.5: score += 20
        elif abs(cpi - 3.0) > 0.8: score += 10

        # Stagflation은 VIX 높을수록 신뢰도 상승
        if regime == "Stagflation":
            if vix > 25: score += 10
            if vix > 30: score += 5
        else:
            if vix > 30: score -= 15  # 불확실성 패널티
            elif vix > 25: score -= 8

        return min(max(score, 30), 95)


class MacroRegimeOrchestrator:
    def __init__(self):
        self.agent = MacroRegimeAgent("MacroRegimeAgent")

    def run(self) -> dict:
        result = self.agent.run()
        self.agent.save()
        return result
