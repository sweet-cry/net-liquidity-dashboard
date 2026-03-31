"""
로컬 PC 실행 테스트
─────────────────────────────────────────────
실행: python test_live.py
요구: pip install yfinance fredapi pandas
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

def test_ficc():
    print("\n=== FICC (실시간) ===")
    from agents.ficc.orchestrator import FICCOrchestrator
    r = FICCOrchestrator().run()
    print(f"  금리  : {r['fixed_income'].get('summary')}")
    print(f"  FX    : {r['currency'].get('summary')}")
    print(f"  원자재: {r['commodity'].get('summary')}")

def test_macro():
    print("\n=== Macro Regime (실시간) ===")
    from agents.macro_regime.orchestrator import MacroRegimeOrchestrator
    r = MacroRegimeOrchestrator().run()
    print(f"  Regime: {r.get('regime')} (신뢰도 {r.get('confidence')}%)")
    print(f"  VIX   : {r['indicators'].get('vix')}")
    print(f"  CPI   : {r['indicators'].get('cpi_yoy')}%")

def test_equity():
    print("\n=== Equity Signal Matrix (실시간) ===")
    from agents.equity.orchestrator import EquityOrchestrator
    r = EquityOrchestrator().run(mode="weighted")
    for ticker, s in r['signal_matrix'].items():
        print(f"  {ticker:5s} [{s['sector']:4s}] "
              f"${s.get('price') or '-':>8} | "
              f"RSI:{s.get('rsi') or '-':>5} | "
              f"{s['final_signal']}")

def test_full_pipeline():
    print("\n=== 전체 파이프라인 ===")
    from orchestrator.master import MasterOrchestrator
    import time
    start = time.time()
    session = MasterOrchestrator().run_daily()
    elapsed = round(time.time() - start, 1)
    print(f"  총 소요시간: {elapsed}s")
    print(f"  브리핑:\n{session['results']['alert']['briefing']}")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--target", default="all",
                   choices=["ficc","macro","equity","all"])
    args = p.parse_args()

    if args.target == "ficc":    test_ficc()
    elif args.target == "macro": test_macro()
    elif args.target == "equity":test_equity()
    else:
        test_ficc()
        test_macro()
        test_equity()
        test_full_pipeline()


def test_flask():
    """Flask API 로컬 테스트 — 별도 터미널에서 먼저 python app.py 실행 필요"""
    import requests
    BASE = "http://localhost:5000"
    endpoints = ["/health", "/api/macro", "/api/ficc", "/api/briefing"]
    for ep in endpoints:
        try:
            r = requests.get(BASE + ep, timeout=5)
            print(f"  {ep}: {r.status_code} — {list(r.json().keys())[:3]}")
        except Exception as e:
            print(f"  {ep}: 실패 ({e})")
