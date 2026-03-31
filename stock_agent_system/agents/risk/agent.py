"""
Risk Agent
─────────────────────────────────────────────
IB 대응: GS Risk Management
역할: VaR / 포지션 사이징 / 손절 / 블랙스완 시나리오
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.base_agent import BaseAgent


class RiskAgent(BaseAgent):
    MAX_POSITION_PCT = 10   # 종목당 최대 10%
    HARD_STOP_PCT    = 5.0  # 하드 손절

    def __init__(self):
        super().__init__("RiskAgent")
        self._inputs = {}

    def run(self, inputs: dict = None) -> dict:
        self._inputs = inputs or {}
        return super().run()

    def fetch(self) -> dict:
        return self._inputs

    def analyze(self, data: dict) -> dict:
        signal_matrix = (
            data.get("equity", {})
                .get("signal_matrix", {})
        )
        macro_regime = data.get("macro", {}).get("regime", "Unknown")
        vix = data.get("macro", {}).get("indicators", {}).get("vix", 20)

        # Regime별 리스크 승수
        regime_mult = {
            "Goldilocks": 1.0, "Reflation": 0.8,
            "Stagflation": 0.5, "Risk-Off": 0.3,
        }.get(macro_regime, 0.7)

        positions = {}
        for ticker, sig in signal_matrix.items():
            if sig.get("final_signal") == "매수":
                size = self.MAX_POSITION_PCT * regime_mult
                # VIX 높으면 사이즈 축소
                if vix > 25: size *= 0.7
                positions[ticker] = {
                    "position_pct":  round(size, 1),
                    "hard_stop_pct": self.HARD_STOP_PCT,
                    "risk_score":    self._risk_score(sig, vix),
                }

        portfolio_risk = "고위험" if vix > 25 else "중위험" if vix > 18 else "저위험"

        return {
            "positions":      positions,
            "portfolio_risk": portfolio_risk,
            "regime":         macro_regime,
            "vix":            vix,
            "summary":        f"포트폴리오 리스크: {portfolio_risk} (VIX {vix}) | "
                              f"진입 대상: {list(positions.keys())}",
        }

    def _risk_score(self, sig: dict, vix: float) -> int:
        score = 5
        if sig.get("sentiment") == "부정": score += 2
        if vix > 25: score += 2
        if sig.get("technical") == "과매수주의": score += 1
        return min(score, 10)
