"""
Alert & Reporting Agent
─────────────────────────────────────────────
변경: 카카오 발송 제거
역할: 전체 결과 종합 → 브리핑 JSON 생성 → 파일 저장
      Flask API(/api/briefing)가 이 파일을 읽어 대시보드에 서빙
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.base_agent import BaseAgent

ROOT    = Path(__file__).parent.parent.parent
OUT_DIR = ROOT / "output"


class AlertAgent(BaseAgent):

    def __init__(self):
        super().__init__("AlertAgent")
        self._inputs = {}

    def run(self, inputs: dict = None) -> dict:
        self._inputs = inputs or {}
        return super().run()

    def fetch(self) -> dict:
        return self._inputs

    def analyze(self, data: dict) -> dict:
        now      = datetime.now()
        briefing = self._build_briefing(data, now)
        feed     = self._build_feed(data, now)
        alerts   = self._build_alerts(data)

        payload = {
            "date":       now.strftime("%Y-%m-%d"),
            "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "briefing":   briefing,
            "feed":       feed,
            "alerts":     alerts,
            "summary":    f"브리핑 생성 완료 | 알림 {len(alerts)}건",
        }

        # output/daily/briefing_YYYYMMDD.json
        path = OUT_DIR / "daily" / f"briefing_{now.strftime('%Y%m%d')}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        # output/latest_briefing.json (Flask API용 최신본)
        latest = OUT_DIR / "latest_briefing.json"
        with open(latest, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        self.logger.info(f"브리핑 저장 완료: {path}")
        return payload

    def _build_briefing(self, data: dict, now: datetime) -> str:
        macro  = data.get("macro",  {})
        ficc   = data.get("ficc",   {})
        equity = data.get("equity", {})
        risk   = data.get("risk",   {})

        regime     = macro.get("regime", "-")
        confidence = macro.get("confidence", "-")
        bias       = macro.get("asset_bias", {})
        fi         = ficc.get("fixed_income", {})
        fx         = ficc.get("currency", {})
        comm       = ficc.get("commodity", {})
        signals    = equity.get("signal_matrix", {})
        mode       = equity.get("signal_mode", "weighted")
        port_risk  = risk.get("portfolio_risk", "-")
        positions  = risk.get("positions", {})

        buy_list  = [t for t, s in signals.items() if s.get("final_signal") == "매수"]
        hold_list = [t for t, s in signals.items() if s.get("final_signal") == "관망"]

        lines = [
            f"📊 Stock Agent 일일 브리핑 [{now.strftime('%Y-%m-%d %H:%M')} KST]",
            "",
            "【매크로 국면】",
            f"  {regime} (신뢰도 {confidence}%)",
            f"  주식 {bias.get('equity','-')} / 채권 {bias.get('bond','-')} / 금 {bias.get('gold','-')} / 달러 {bias.get('fx','-')}",
            "",
            "【FICC】",
            f"  금리  : {fi.get('summary', '-')}",
            f"  FX    : {fx.get('summary', '-')}",
            f"  원자재: {comm.get('summary', '-')}",
            "",
            f"【Equity Signal Matrix】 (모드: {mode})",
            f"  매수 → {', '.join(buy_list)  if buy_list  else '없음'}",
            f"  관망 → {', '.join(hold_list) if hold_list else '없음'}",
            "",
            "【Risk】",
            f"  포트폴리오 리스크: {port_risk}",
            f"  진입 대상: {list(positions.keys()) if positions else '없음'}",
            "",
            "— Stock Agent System v1.0",
        ]
        return "\n".join(lines)

    def _build_feed(self, data: dict, now: datetime) -> list:
        feed  = []
        ts    = now.strftime("%H:%M KST")
        macro  = data.get("macro",  {})
        equity = data.get("equity", {})
        risk   = data.get("risk",   {})
        comm   = data.get("ficc",   {}).get("commodity", {})

        signals  = equity.get("signal_matrix", {})
        buy_list = [t for t, s in signals.items() if s.get("final_signal") == "매수"]
        if buy_list:
            feed.append({"type": "buy",
                         "text": f"{', '.join(buy_list)} 매수 신호 — Signal Matrix 기준 충족",
                         "time": ts})

        wti = comm.get("WTI_price", 0)
        if wti and wti > 100:
            feed.append({"type": "alert",
                         "text": f"WTI ${wti:.1f} — $100 임계값 돌파. 에너지 섹터 주목",
                         "time": ts})

        feed.append({"type": "info",
                     "text": f"Macro Regime: {macro.get('regime','-')} — {macro.get('summary','')}",
                     "time": ts})

        if risk.get("portfolio_risk") == "고위험":
            feed.append({"type": "alert",
                         "text": f"포트폴리오 고위험 — VIX {risk.get('vix','-')} 상승. 포지션 축소 검토",
                         "time": ts})
        return feed

    def _build_alerts(self, data: dict) -> list:
        alerts = []
        comm = data.get("ficc", {}).get("commodity",    {})
        fx   = data.get("ficc", {}).get("currency",     {})
        fi   = data.get("ficc", {}).get("fixed_income", {})

        checks = [
            ("WTI",   comm.get("WTI_price",  0), 100,  "WTI $100 돌파"),
            ("Gold",  comm.get("Gold_price", 0), 3000, "금 $3,000 돌파"),
            ("DXY",   fx.get("dxy",          0), 106,  "달러인덱스 106 돌파"),
            ("US10Y", fi.get("us10y",         0), 4.5,  "미국채 10Y 4.5% 돌파"),
        ]
        for name, val, threshold, msg in checks:
            if val and val > threshold:
                alerts.append({"name": name, "value": val, "message": msg})
        return alerts
