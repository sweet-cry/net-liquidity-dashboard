"""
Flask API 서버
─────────────────────────────────────────────
엔드포인트:
  GET /api/macro      → Macro Regime 데이터
  GET /api/ficc       → FICC 데이터
  GET /api/equity     → Equity Signal Matrix
  GET /api/risk       → Risk 포지션
  GET /api/briefing   → 일일 브리핑 피드
  GET /api/all        → 전체 최신 세션
  POST /api/run       → 파이프라인 수동 실행
  GET /health         → 서버 상태
"""
import json
import os
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS

# ── 경로 설정 ──────────────────────────────────────────────────
ROOT    = Path(__file__).parent
OUT_DIR = ROOT / "output"

app = Flask(__name__)
CORS(app)  # React 대시보드에서 호출 허용

# ── 헬퍼 ──────────────────────────────────────────────────────
def load_latest(filename: str) -> dict:
    """output/latest_*.json 또는 output/daily/*_오늘.json 읽기"""
    path = OUT_DIR / filename
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"error": f"{filename} 없음 — 파이프라인을 먼저 실행하세요"}


def load_agent(agent_name: str) -> dict:
    """output/daily/AgentName_YYYYMMDD.json 읽기"""
    today = datetime.now().strftime("%Y%m%d")
    path  = OUT_DIR / "daily" / f"{agent_name}_{today}.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"error": f"{agent_name} 데이터 없음 — 파이프라인을 먼저 실행하세요"}


# ── 엔드포인트 ─────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "time":   datetime.now().strftime("%Y-%m-%d %H:%M:%S KST"),
        "version": "v1.0",
    })


@app.route("/api/macro")
def api_macro():
    return jsonify(load_agent("MacroRegimeAgent"))


@app.route("/api/ficc")
def api_ficc():
    fi   = load_agent("FixedIncomeAgent")
    fx   = load_agent("CurrencyAgent")
    comm = load_agent("CommodityAgent")
    return jsonify({
        "fixed_income": fi,
        "currency":     fx,
        "commodity":    comm,
        "updated_at":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/api/equity")
def api_equity():
    screen = load_agent("ScreenerAgent")
    tech   = load_agent("TechnicalAgent")
    fund   = load_agent("FundamentalAgent")
    news   = load_agent("NewsSentimentAgent")
    return jsonify({
        "screener":    screen,
        "technical":   tech,
        "fundamental": fund,
        "news":        news,
        "updated_at":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/api/risk")
def api_risk():
    return jsonify(load_agent("RiskAgent"))


@app.route("/api/briefing")
def api_briefing():
    return jsonify(load_latest("latest_briefing.json"))


@app.route("/api/all")
def api_all():
    """전체 최신 세션 — 대시보드 초기 로드용"""
    today = datetime.now().strftime("%Y-%m-%d")
    path  = OUT_DIR / "daily" / f"session_{today}.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify({"error": "오늘 세션 없음 — /api/run 으로 실행하세요"})


@app.route("/api/run", methods=["POST"])
def api_run():
    """파이프라인 수동 실행 (백그라운드)"""
    def _run():
        try:
            from orchestrator.master import MasterOrchestrator
            MasterOrchestrator().run_daily()
        except Exception as e:
            app.logger.error(f"파이프라인 오류: {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({
        "status":  "started",
        "message": "파이프라인 백그라운드 실행 시작",
        "time":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


# ── 스케줄러 (APScheduler) ─────────────────────────────────────
def start_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from orchestrator.master import MasterOrchestrator

        scheduler = BackgroundScheduler(timezone="Asia/Seoul")
        scheduler.add_job(
            MasterOrchestrator().run_daily,
            CronTrigger(hour=9, minute=0),   # 매일 09:00 KST
            id="daily_pipeline",
        )
        scheduler.start()
        app.logger.info("스케줄러 시작 — 매일 09:00 KST 자동 실행")
    except Exception as e:
        app.logger.warning(f"스케줄러 시작 실패: {e}")


# ── 실행 ──────────────────────────────────────────────────────
if __name__ == "__main__":
    start_scheduler()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
