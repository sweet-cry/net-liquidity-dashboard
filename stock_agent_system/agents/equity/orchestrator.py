"""
Equity Sub-Orchestrator
─────────────────────────────────────────────
IB 대응: GS Equity Research Desk
모든 fetch() → yfinance 실제 데이터
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.base_agent import BaseAgent

UNIVERSE = ["TSLA", "LCID", "RIVN", "MU", "SNDK", "CCJ", "UEC", "XOM", "CVX"]

SECTOR_MAP = {
    "TSLA": "EV", "LCID": "EV", "RIVN": "EV",
    "MU": "반도체", "SNDK": "반도체",
    "CCJ": "우라늄", "UEC": "우라늄",
    "XOM": "에너지", "CVX": "에너지",
}


# ── Screener Agent ────────────────────────────────────────────
class ScreenerAgent(BaseAgent):
    FILTERS = {"min_volume": 500_000, "max_rsi": 78, "min_rsi": 20}

    def fetch(self) -> dict:
        try:
            import yfinance as yf
            data = {}
            for ticker in UNIVERSE:
                t = yf.Ticker(ticker)
                fi = t.fast_info
                vol   = fi.get("three_month_average_volume") or fi.get("threeMonthAverageVolume") or 0
                price = fi.get("last_price") or fi.get("lastPrice") or 0
                data[ticker] = {"volume": int(vol), "price": round(float(price), 2)}
            return data
        except Exception as e:
            self.logger.warning(f"Screener yfinance 실패: {e}")
            return {t: {"volume": 1_000_000, "price": 0} for t in UNIVERSE}

    def analyze(self, data: dict) -> dict:
        passed = [
            t for t, d in data.items()
            if d.get("volume", 0) >= self.FILTERS["min_volume"]
        ]
        return {
            "watchlist":       passed,
            "prices":          {t: d.get("price") for t, d in data.items()},
            "total_screened":  len(UNIVERSE),
            "passed":          len(passed),
            "summary":         f"스크리닝 통과: {len(passed)}/{len(UNIVERSE)} — {passed}",
        }


# ── Technical Agent ───────────────────────────────────────────
class TechnicalAgent(BaseAgent):
    def fetch(self) -> dict:
        try:
            import yfinance as yf
            import pandas as pd
            result = {}
            for ticker in UNIVERSE:
                hist = yf.Ticker(ticker).history(period="6mo")
                if hist.empty:
                    continue
                close = hist["Close"]
                # RSI
                delta = close.diff()
                gain  = delta.clip(lower=0).rolling(14).mean()
                loss  = (-delta.clip(upper=0)).rolling(14).mean()
                rs    = gain / loss
                rsi   = round(float(100 - (100 / (1 + rs.iloc[-1]))), 1)
                # MACD
                ema12 = close.ewm(span=12).mean()
                ema26 = close.ewm(span=26).mean()
                macd  = ema12 - ema26
                signal_line = macd.ewm(span=9).mean()
                macd_cross = "양전환" if (macd.iloc[-1] > signal_line.iloc[-1] and
                                         macd.iloc[-2] <= signal_line.iloc[-2]) else \
                             "음전환" if (macd.iloc[-1] < signal_line.iloc[-1] and
                                         macd.iloc[-2] >= signal_line.iloc[-2]) else "중립"
                # 볼린저밴드
                ma20  = close.rolling(20).mean()
                std20 = close.rolling(20).std()
                upper = ma20 + 2 * std20
                lower = ma20 - 2 * std20
                price = close.iloc[-1]
                if price >= upper.iloc[-1]:   bb = "상단"
                elif price <= lower.iloc[-1]: bb = "하단"
                elif price >= ma20.iloc[-1]:  bb = "중상단"
                else:                          bb = "중하단"
                # 52주 고저
                high52 = round(float(close.rolling(252).max().iloc[-1]), 2)
                low52  = round(float(close.rolling(252).min().iloc[-1]), 2)
                pct_from_high = round((price - high52) / high52 * 100, 1)

                result[ticker] = {
                    "price": round(float(price), 2),
                    "rsi":   rsi,
                    "macd":  macd_cross,
                    "bb":    bb,
                    "high52": high52,
                    "low52":  low52,
                    "pct_from_high": pct_from_high,
                }
            return result
        except Exception as e:
            self.logger.warning(f"Technical yfinance 실패: {e}")
            return {}

    def analyze(self, data: dict) -> dict:
        signals = {}
        for ticker, d in data.items():
            rsi  = d.get("rsi", 50)
            bb   = d.get("bb",  "중단")
            macd = d.get("macd","중립")
            if rsi < 35 and bb in ["하단", "중하단"]:   sig = "매수검토"
            elif rsi > 70:                              sig = "과매수주의"
            elif macd == "양전환":                       sig = "모멘텀상승"
            elif macd == "음전환":                       sig = "모멘텀하락"
            else:                                        sig = "관망"
            signals[ticker] = {"signal": sig, **d}
        return {
            "signals": signals,
            "summary": " | ".join(f"{t}:{v['signal']}" for t, v in signals.items()),
        }


# ── Fundamental Agent ─────────────────────────────────────────
class FundamentalAgent(BaseAgent):
    def fetch(self) -> dict:
        try:
            import yfinance as yf
            result = {}
            for ticker in UNIVERSE:
                info = yf.Ticker(ticker).info
                result[ticker] = {
                    "per":          info.get("trailingPE"),
                    "pbr":          info.get("priceToBook"),
                    "eps_growth":   info.get("earningsGrowth"),
                    "revenue_growth": info.get("revenueGrowth"),
                    "market_cap":   info.get("marketCap"),
                    "target_price": info.get("targetMeanPrice"),
                    "recommendation": info.get("recommendationMean"),  # 1=강매수~5=매도
                }
            return result
        except Exception as e:
            self.logger.warning(f"Fundamental yfinance 실패: {e}")
            return {}

    def analyze(self, data: dict) -> dict:
        ratings = {}
        for ticker, d in data.items():
            score = 0
            eps_g = d.get("eps_growth")
            rec   = d.get("recommendation")
            rev_g = d.get("revenue_growth")
            if eps_g and eps_g > 0.15:  score += 2
            if rev_g and rev_g > 0.10:  score += 1
            if rec   and rec  < 2.5:    score += 1   # 애널 컨센서스 매수
            ratings[ticker] = {
                "score":       score,
                "rating":      "비중확대" if score >= 3 else "중립" if score >= 1 else "비중축소",
                "target_price": d.get("target_price"),
                **d,
            }
        return {
            "ratings": ratings,
            "summary": " | ".join(f"{t}:{v['rating']}" for t, v in ratings.items()),
        }


# ── News/Sentiment Agent ──────────────────────────────────────
class NewsSentimentAgent(BaseAgent):
    def fetch(self) -> dict:
        try:
            import yfinance as yf
            result = {}
            for ticker in UNIVERSE:
                news = yf.Ticker(ticker).news or []
                result[ticker] = [
                    {"title": n.get("title", ""), "publisher": n.get("publisher", "")}
                    for n in news[:3]
                ]
            return result
        except Exception as e:
            self.logger.warning(f"News yfinance 실패: {e}")
            return {}

    def analyze(self, data: dict) -> dict:
        """
        yfinance 뉴스는 감성점수 미제공
        → 키워드 기반 간이 분류 (Claude API 연동 전까지)
        """
        POS = ["beat", "surge", "rally", "record", "growth", "upgrade",
               "buy", "strong", "profit", "deal", "partnership"]
        NEG = ["miss", "fall", "drop", "cut", "layoff", "loss", "downgrade",
               "sell", "weak", "fine", "lawsuit", "recall"]

        summary = {}
        for ticker, articles in data.items():
            score = 0
            for a in articles:
                title_lower = a.get("title", "").lower()
                score += sum(1 for w in POS if w in title_lower)
                score -= sum(1 for w in NEG if w in title_lower)
            label = "긍정" if score > 0 else "부정" if score < 0 else "중립"
            summary[ticker] = {
                "sentiment_score": score,
                "label":           label,
                "news_count":      len(articles),
                "headlines":       [a["title"] for a in articles],
            }
        return {
            "sentiment": summary,
            "summary":   " | ".join(
                f"{t}:{v['label']}({v['sentiment_score']})"
                for t, v in summary.items()
            ),
        }


# ── Equity Sub-Orchestrator ───────────────────────────────────
class EquityOrchestrator:
    def __init__(self):
        self.screener    = ScreenerAgent("ScreenerAgent")
        self.technical   = TechnicalAgent("TechnicalAgent")
        self.fundamental = FundamentalAgent("FundamentalAgent")
        self.news        = NewsSentimentAgent("NewsSentimentAgent")

    def run(self, mode: str = "weighted", regime: str = "Goldilocks") -> dict:
        screen = self.screener.run()
        tech   = self.technical.run()
        fund   = self.fundamental.run()
        news   = self.news.run()

        for agent in [self.screener, self.technical, self.fundamental, self.news]:
            agent.save()

        matrix = self._build_signal_matrix(screen, tech, fund, news,
                                            mode=mode, regime=regime)
        return {
            "screener":      screen,
            "technical":     tech,
            "fundamental":   fund,
            "news":          news,
            "signal_matrix": matrix,
            "signal_mode":   mode,
            "regime":        regime,
        }

    def _build_signal_matrix(self, screen, tech, fund, news,
                              mode="weighted", regime="Goldilocks") -> dict:
        watchlist = screen.get("watchlist", UNIVERSE)
        tech_sigs = tech.get("signals", {})
        fund_rats = fund.get("ratings", {})
        news_sent = news.get("sentiment", {})
        prices    = screen.get("prices", {})

        matrix = {}
        for ticker in watchlist:
            t_sig = tech_sigs.get(ticker, {}).get("signal", "관망")
            f_rat = fund_rats.get(ticker, {}).get("rating", "중립")
            n_lbl = news_sent.get(ticker,  {}).get("label",  "중립")
            t_score = 1 if t_sig in ["매수검토", "모멘텀상승"] else 0
            f_score = 1 if f_rat == "비중확대" else 0
            n_score = 1 if n_lbl == "긍정" else 0

            if mode == "simple":
                final, score, weights = self._mode_simple(t_score, f_score, n_score)
            elif mode == "regime":
                final, score, weights = self._mode_regime(t_score, f_score, n_score, regime)
            else:
                final, score, weights = self._mode_weighted(t_score, f_score, n_score)

            tech_d = tech_sigs.get(ticker, {})
            fund_d = fund_rats.get(ticker, {})
            matrix[ticker] = {
                "final_signal":   final,
                "score":          round(score, 3),
                "weights":        weights,
                "sector":         SECTOR_MAP.get(ticker, "-"),
                "price":          prices.get(ticker),
                "target_price":   fund_d.get("target_price"),
                "rsi":            tech_d.get("rsi"),
                "pct_from_high":  tech_d.get("pct_from_high"),
                "high52":         tech_d.get("high52"),
                "low52":          tech_d.get("low52"),
                "technical":      t_sig,
                "fundamental":    f_rat,
                "sentiment":      n_lbl,
                "headlines":      news_sent.get(ticker, {}).get("headlines", []),
                "mode":           mode,
            }
        return matrix

    @staticmethod
    def _mode_simple(t, f, n):
        weights = {"tech": 33, "fund": 33, "news": 34}
        total   = t + f + n
        final   = "매수" if total >= 2 else "관망" if total == 1 else "매도"
        return final, total / 3, weights

    @staticmethod
    def _mode_weighted(t, f, n, wt=0.40, wf=0.40, wn=0.20):
        weights = {"tech": int(wt*100), "fund": int(wf*100), "news": int(wn*100)}
        score   = t * wt + f * wf + n * wn
        final   = "매수" if score >= 0.6 else "관망" if score >= 0.3 else "매도"
        return final, score, weights

    @staticmethod
    def _mode_regime(t, f, n, regime):
        W = {
            "Goldilocks":  (0.30, 0.50, 0.20),
            "Reflation":   (0.40, 0.30, 0.30),
            "Stagflation": (0.20, 0.20, 0.60),
            "Risk-Off":    (0.50, 0.30, 0.20),
        }
        wt, wf, wn = W.get(regime, (0.40, 0.40, 0.20))
        weights = {"tech": int(wt*100), "fund": int(wf*100), "news": int(wn*100)}
        score   = t * wt + f * wf + n * wn
        # Stagflation: 매수 기준 높이고(0.5→0.55) 관망 기준도 올림(0.3→0.35)
        # → 불확실성 높은 국면에서 더 보수적 판단
        if regime == "Stagflation":
            final = "매수" if score >= 0.55 else "관망" if score >= 0.35 else "매도"
        else:
            final = "매수" if score >= 0.6  else "관망" if score >= 0.3  else "매도"
        return final, score, weights
