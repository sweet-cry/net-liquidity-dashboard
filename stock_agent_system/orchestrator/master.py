"""
Master Orchestrator — asyncio 병렬 방식
─────────────────────────────────────────────
실행 구조:
  Phase 1 (병렬): MacroRegime ┐
                  FICC        ├─ asyncio.gather → 동시 실행
                  Equity      ┘
  Phase 2 (순차): Risk  → 병렬 결과 받아서 계산
  Phase 3 (순차): Alert → 최종 발송

장점:
  - 가장 느린 Agent 시간만큼만 소요 (~60초 → 기존 대비 2배↑)
  - 하나 실패해도 나머지 계속 진행
  - yfinance 등 sync API는 run_in_executor로 래핑
"""
import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from agents.macro_regime.orchestrator import MacroRegimeOrchestrator
from shared.base_agent import _SafeEncoder
from agents.ficc.orchestrator import FICCOrchestrator
from agents.equity.orchestrator import EquityOrchestrator
from agents.risk.agent import RiskAgent
from agents.alert.agent import AlertAgent

LOG  = logging.getLogger("MasterOrchestrator")
ROOT = Path(__file__).parent.parent

# sync 함수를 async로 래핑하는 공용 executor
_EXECUTOR = ThreadPoolExecutor(max_workers=6)


async def _run_sync(fn, *args) -> dict:
    """동기 함수를 asyncio executor에서 실행 (블로킹 방지)"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_EXECUTOR, fn, *args)


class MasterOrchestrator:
    """
    asyncio 병렬 Master Orchestrator

    ┌─ Master Orchestrator (async)
    │
    │  ── Phase 1: 병렬 ──────────────────────────────
    ├── MacroRegime Sub-Orchestrator  ┐
    ├── FICC Sub-Orchestrator         ├─ asyncio.gather
    │   ├── FixedIncome Agent         │
    │   ├── Currency Agent            │
    │   └── Commodity Agent           │
    ├── Equity Sub-Orchestrator       ┘
    │   ├── Screener Agent
    │   ├── Technical Agent
    │   ├── Fundamental Agent
    │   └── News/Sentiment Agent
    │
    │  ── Phase 2: 순차 ──────────────────────────────
    ├── Risk Agent   (Phase 1 결과 수신)
    │
    │  ── Phase 3: 순차 ──────────────────────────────
    └── Alert Agent  (전체 결과 → KakaoTalk 발송)
    """

    def __init__(self):
        self.macro_orc   = MacroRegimeOrchestrator()
        self.ficc_orc    = FICCOrchestrator()
        self.equity_orc  = EquityOrchestrator()
        self.risk_agent  = RiskAgent()
        self.alert_agent = AlertAgent()
        self.session: dict = {}

    # ── 공개 진입점 (sync wrapper) ─────────────────────────────
    def run_daily(self) -> dict:
        """외부(스케줄러·카카오)에서 호출하는 동기 진입점"""
        return asyncio.run(self._run_daily_async())

    # ── 메인 비동기 파이프라인 ─────────────────────────────────
    async def _run_daily_async(self) -> dict:
        start = time.time()
        date  = datetime.now().strftime("%Y-%m-%d")
        LOG.info(f"=== 일일 파이프라인 시작 [{date}] ===")

        self.session = {"date": date, "results": {}, "elapsed": {}}

        # ── Phase 1: 병렬 실행 ────────────────────────────────
        import os
        signal_mode = os.getenv("SIGNAL_MODE", "weighted")
        LOG.info(f"[Phase 1] 병렬 실행... (mode={signal_mode})")
        t1 = time.time()

        if signal_mode == "regime":
            macro_r = await _run_sync(self.macro_orc.run)
            regime  = macro_r.get("regime", "Goldilocks") if not isinstance(macro_r, Exception) else "Goldilocks"
            ficc_r, equity_r = await asyncio.gather(
                _run_sync(self.ficc_orc.run),
                _run_sync(self.equity_orc.run, signal_mode, regime),
                return_exceptions=True,
            )
            ficc_r   = ficc_r   if not isinstance(ficc_r,   Exception) else {"error": str(ficc_r)}
            equity_r = equity_r if not isinstance(equity_r, Exception) else {"error": str(equity_r)}
        else:
            results = await asyncio.gather(
                _run_sync(self.macro_orc.run),
                _run_sync(self.ficc_orc.run),
                _run_sync(self.equity_orc.run, signal_mode),
                return_exceptions=True,
            )
            macro_r, ficc_r, equity_r = [
                r if not isinstance(r, Exception) else {"error": str(r)}
                for r in results
            ]

        self.session["results"].update({"macro": macro_r, "ficc": ficc_r, "equity": equity_r})
        self.session["signal_mode"] = signal_mode
        self.session["elapsed"]["phase1"] = round(time.time() - t1, 2)
        LOG.info(f"[Phase 1] 완료 ({self.session['elapsed']['phase1']}s)")

        # ── Phase 2: Risk (순차, Phase 1 결과 필요) ───────────
        LOG.info("[Phase 2] Risk Agent 실행...")
        t2 = time.time()
        risk_r = await _run_sync(
            self.risk_agent.run,
            {"macro": macro_r, "ficc": ficc_r, "equity": equity_r},
        )
        self.session["results"]["risk"] = risk_r
        self.session["elapsed"]["phase2"] = round(time.time() - t2, 2)
        LOG.info(f"[Phase 2] 완료 ({self.session['elapsed']['phase2']}s)")

        # ── Phase 3: Alert (순차, 전체 결과 필요) ─────────────
        LOG.info("[Phase 3] Alert Agent 실행...")
        t3 = time.time()
        alert_r = await _run_sync(
            self.alert_agent.run,
            self.session["results"],
        )
        self.session["results"]["alert"] = alert_r
        self.session["elapsed"]["phase3"] = round(time.time() - t3, 2)
        LOG.info(f"[Phase 3] 완료 ({self.session['elapsed']['phase3']}s)")

        # ── 세션 저장 ─────────────────────────────────────────
        self.session["elapsed"]["total"] = round(time.time() - start, 2)
        self._save_session()

        LOG.info(
            f"=== 파이프라인 완료 | "
            f"총 {self.session['elapsed']['total']}s "
            f"(P1:{self.session['elapsed']['phase1']}s / "
            f"P2:{self.session['elapsed']['phase2']}s / "
            f"P3:{self.session['elapsed']['phase3']}s) ==="
        )
        return self.session

    # ── 카카오 온디맨드 라우팅 (async) ────────────────────────
    async def route_async(self, command: str) -> str:
        """카카오 명령어 → 해당 Sub-Orchestrator 즉시 실행"""
        cmd = command.strip().upper()

        ROUTES = {
            ("매크로","MACRO","금리","CPI","FOMC","REGIME"): self.macro_orc.run,
            ("FICC","유가","WTI","금","달러","DXY","채권","국채"): self.ficc_orc.run,
            ("TSLA","LCID","RIVN","MU","SNDK","CCJ","주식","종목"): self.equity_orc.run,
            ("리스크","RISK","손절","포지션"): self.risk_agent.run,
        }

        fn = None
        for keywords, handler in ROUTES.items():
            if any(k in cmd for k in keywords):
                fn = handler
                break

        if fn is None:
            return f"인식 불가: {command}\n가능 명령어: 매크로 / 유가 / TSLA / 리스크"

        result = await _run_sync(fn)
        return json.dumps(result, ensure_ascii=False, indent=2)

    def route(self, command: str) -> str:
        """동기 래퍼 (카카오 Flask에서 호출)"""
        return asyncio.run(self.route_async(command))

    # ── 내부 ──────────────────────────────────────────────────
    def _save_session(self):
        path = ROOT / "output" / "daily" / f"session_{self.session['date']}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.session, f, ensure_ascii=False, indent=2, cls=_SafeEncoder)
        LOG.info(f"세션 저장: {path}")


# ── 진입점 ────────────────────────────────────────────────────
if __name__ == "__main__":
    orc = MasterOrchestrator()
    orc.run_daily()
