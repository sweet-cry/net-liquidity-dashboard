"""
Net Liquidity 로컬 웹서버 (2000년~ 초장기 FRED 스타일)
=======================================================
필요 패키지: pip install flask requests pandas plotly numpy

실행:
  python dashboard_server.py --key YOUR_FRED_API_KEY

브라우저: http://localhost:5000
"""

import argparse
import threading
import time
import requests as req
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from flask import Flask, render_template_string
from datetime import datetime, timedelta

app = Flask(__name__)

API_KEY = ""
FEPS = 270.0
FPE = 21.0
REFRESH_INTERVAL = 3600
START_DATE = "2000-01-01"

cache = {
    "chart_html": None,
    "summary": None,
    "updated_at": None,
    "error": None,
}

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Net Liquidity Dashboard</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: Arial, 'Segoe UI', sans-serif; background: #f0f0f0; color: #1a1a1a; }
    .header { background: #fff; border-bottom: 2px solid #cc0000; padding: 11px 24px; display: flex; align-items: center; justify-content: space-between; }
    .header h1 { font-size: 15px; font-weight: 700; color: #333; }
    .badge { display: inline-block; font-size: 10px; background: #cc0000; color: #fff; border-radius: 2px; padding: 1px 6px; margin-left: 8px; font-weight: 700; }
    .meta { font-size: 11px; color: #666; }
    .refresh-btn { font-size: 11px; padding: 5px 12px; border: 1px solid #cc0000; border-radius: 2px; background: transparent; cursor: pointer; color: #cc0000; }
    .refresh-btn:hover { background: #fff0f0; }
    .container { max-width: 1280px; margin: 0 auto; padding: 16px 20px; }
    .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(155px, 1fr)); gap: 10px; margin-bottom: 16px; }
    .mc { background: #fff; border-radius: 2px; padding: 12px 14px; border: 1px solid #ddd; border-top: 3px solid #cc0000; }
    .mc-lbl { font-size: 10px; color: #777; margin-bottom: 4px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }
    .mc-val { font-size: 19px; font-weight: 700; color: #111; font-family: 'Courier New', monospace; }
    .mc-sub { font-size: 11px; margin-top: 3px; }
    .pos { color: #2ca02c; } .neg { color: #d62728; } .neu { color: #888; }
    .chart-box { background: #fff; border: 1px solid #ddd; border-radius: 2px; padding: 4px; margin-bottom: 12px; }
    .error { background: #fff0f0; border: 1px solid #cc0000; border-radius: 2px; padding: 14px; color: #cc0000; margin-bottom: 12px; font-size: 13px; }
    .loading { text-align: center; padding: 60px; color: #888; font-size: 13px; }
    .footer { font-size: 10px; color: #aaa; text-align: center; padding: 10px; border-top: 1px solid #ddd; margin-top: 4px; }
  </style>
  <script>
    let cd = {{ refresh_interval }};
    function tick() {
      cd--;
      const el = document.getElementById('cd');
      if (el) el.textContent = Math.floor(cd/60) + 'min ' + String(cd%60).padStart(2,'0') + 's 후 자동갱신';
      if (cd <= 0) location.reload();
      else setTimeout(tick, 1000);
    }
    window.onload = tick;
    function manualRefresh() {
      document.getElementById('cd').textContent = '갱신 중...';
      fetch('/refresh').then(() => setTimeout(() => location.reload(), 2500));
    }
  </script>
</head>
<body>
<div class="header">
  <h1>Federal Reserve Net Liquidity <span class="badge">LIVE</span></h1>
  <div style="display:flex;align-items:center;gap:16px;">
    <span class="meta" id="cd"></span>
    <span class="meta">Updated: {{ updated_at }}</span>
    <button class="refresh-btn" onclick="manualRefresh()">Refresh</button>
  </div>
</div>

<div class="container">
  {% if error %}
  <div class="error">Error: {{ error }}</div>
  {% elif not summary %}
  <div class="loading">Loading data from FRED...</div>
  {% else %}

  <div class="metrics">
    <div class="mc">
      <div class="mc-lbl">Net Liquidity</div>
      <div class="mc-val">{{ summary.nl }}</div>
      <div class="mc-sub {{ 'pos' if summary.nl_wow_pos else 'neg' }}">{{ summary.nl_wow }}</div>
    </div>
    <div class="mc">
      <div class="mc-lbl">NL Regression FV</div>
      <div class="mc-val">{{ summary.fv_nl }}</div>
      <div class="mc-sub {{ 'pos' if summary.fv_nl_cheap else ('neg' if summary.fv_nl_cheap is not none else 'neu') }}">{{ summary.fv_nl_gap }}</div>
    </div>
    <div class="mc">
      <div class="mc-lbl">P/E × EPS FV</div>
      <div class="mc-val">{{ summary.fv_pe }}</div>
      <div class="mc-sub {{ 'pos' if summary.fv_pe_cheap else ('neg' if summary.fv_pe_cheap is not none else 'neu') }}">{{ summary.fv_pe_gap }}</div>
    </div>
    <div class="mc">
      <div class="mc-lbl">WALCL</div>
      <div class="mc-val">{{ summary.walcl }}</div>
      <div class="mc-sub neu">Fed Total Assets</div>
    </div>
    <div class="mc">
      <div class="mc-lbl">TGA</div>
      <div class="mc-val">{{ summary.tga }}</div>
      <div class="mc-sub neu">Treasury Cash</div>
    </div>
    <div class="mc">
      <div class="mc-lbl">RRP</div>
      <div class="mc-val">{{ summary.rrp }}</div>
      <div class="mc-sub neu">Reverse Repo</div>
    </div>
  </div>

  <div class="chart-box">{{ chart_html | safe }}</div>

  {% endif %}
  <div class="footer">
    Source: Federal Reserve Bank of St. Louis (FRED) &nbsp;|&nbsp; WALCL · WDTGAL · RRPONTSYD · SP500 &nbsp;|&nbsp; 2000–present
  </div>
</div>
</body>
</html>
"""


def fetch_series(series_id, start, frequency="m"):
    params = dict(series_id=series_id, api_key=API_KEY, file_type="json",
                  observation_start=start, frequency=frequency)
    r = req.get(FRED_BASE, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    if "error_message" in data:
        raise ValueError(f"{series_id}: {data['error_message']}")
    obs = [(o["date"], float(o["value"])) for o in data["observations"] if o["value"] != "."]
    if not obs:
        raise ValueError(f"{series_id}: 데이터 없음")
    s = pd.Series(dict(obs), name=series_id)
    s.index = pd.to_datetime(s.index)
    return s


def fetch_auto(series_id, start):
    for freq in ["m", "w", "d"]:
        try:
            s = fetch_series(series_id, start, freq)
            if len(s) > 0:
                if freq == "d":
                    s = s.resample("MS").last().dropna()
                elif freq == "w":
                    s = s.resample("MS").last().dropna()
                return s
        except Exception:
            continue
    raise ValueError(f"{series_id}: 모든 frequency 실패")


def build_data():
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] WALCL 로딩...")
    walcl = fetch_auto("WALCL", START_DATE)
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] WDTGAL 로딩...")
    tga = fetch_auto("WDTGAL", START_DATE)
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] RRPONTSYD 로딩...")
    rrp = fetch_auto("RRPONTSYD", START_DATE)
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] SP500 로딩...")
    try:
        spx = fetch_auto("SP500", START_DATE)
    except Exception:
        spx = pd.Series(dtype=float, name="SP500")

    df = pd.DataFrame({"WALCL": walcl, "TGA": tga, "RRP": rrp, "SP500": spx}).sort_index()
    df[["WALCL", "TGA", "RRP"]] = df[["WALCL", "TGA", "RRP"]].ffill()
    df = df.dropna(subset=["WALCL", "TGA", "RRP"])
    df["NL"] = df["WALCL"] - df["TGA"] - df["RRP"]
    df["NL_WoW"] = df["NL"].diff()

    valid = df[["NL", "SP500"]].dropna()
    if len(valid) >= 10:
        x, y = valid["NL"].values, valid["SP500"].values
        slope, intercept = np.polyfit(x, y, 1)
        r2 = np.corrcoef(x, y)[0, 1] ** 2
        print(f"  회귀: SPX = {slope:.4f}×NL + {intercept:.1f}  R²={r2:.3f}")
        df["FV_NL"] = slope * df["NL"] + intercept
    else:
        df["FV_NL"] = np.nan

    print(f"  완료: {len(df)}개 포인트 ({df.index[0].date()} ~ {df.index[-1].date()})")
    return df


def fmt_val(v):
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:.2f}T"
    if abs(v) >= 1_000:
        return f"{v/1_000:.2f}T"
    return f"{v:,.0f}B"


def build_summary(df):
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else None
    fv_pe = FEPS * FPE
    spx = latest["SP500"] if not pd.isna(latest["SP500"]) else None
    fv_nl = latest["FV_NL"] if "FV_NL" in latest.index and not pd.isna(latest["FV_NL"]) else None

    wow = latest["NL"] - prev["NL"] if prev is not None else 0
    nl_wow_str = f"{'▲' if wow >= 0 else '▼'} {fmt_val(abs(wow))} MoM"

    fv_nl_gap = fv_nl_cheap = None
    if fv_nl and spx:
        gap = (spx - fv_nl) / fv_nl * 100
        fv_nl_gap = f"SPX {'+' if gap>0 else ''}{gap:.1f}% {'고평가' if gap>0 else '저평가'}"
        fv_nl_cheap = gap < 0

    fv_pe_gap = fv_pe_cheap = None
    if spx:
        gap2 = (spx - fv_pe) / fv_pe * 100
        fv_pe_gap = f"SPX {'+' if gap2>0 else ''}{gap2:.1f}% {'고평가' if gap2>0 else '저평가'}"
        fv_pe_cheap = gap2 < 0

    return {
        "nl": fmt_val(latest["NL"]),
        "nl_wow": nl_wow_str,
        "nl_wow_pos": wow >= 0,
        "walcl": fmt_val(latest["WALCL"]),
        "tga": fmt_val(latest["TGA"]),
        "rrp": fmt_val(latest["RRP"]),
        "fv_nl": f"{fv_nl:,.0f}" if fv_nl else "—",
        "fv_nl_gap": fv_nl_gap or "데이터 부족",
        "fv_nl_cheap": fv_nl_cheap,
        "fv_pe": f"{fv_pe:,.0f}",
        "fv_pe_gap": fv_pe_gap or "SPX 없음",
        "fv_pe_cheap": fv_pe_cheap,
    }


def t_fmt(v):
    if v >= 1000:
        return f"{v/1000:.1f}T"
    return f"{int(v)}B"


def build_chart(df):
    fv_pe = FEPS * FPE

    recession_periods = [
        ("2001-03-01", "2001-11-01"),
        ("2007-12-01", "2009-06-01"),
        ("2020-02-01", "2020-04-01"),
    ]

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=("Net Liquidity Components (2000–present)", "S&P 500 vs Fair Value (2000–present)"),
        vertical_spacing=0.10,
        row_heights=[0.5, 0.5],
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]],
    )

    for start_r, end_r in recession_periods:
        for row in [1, 2]:
            fig.add_vrect(
                x0=start_r, x1=end_r,
                fillcolor="rgba(180,0,0,0.07)",
                layer="below", line_width=0,
                row=row, col=1,
            )

    fig.add_trace(go.Scatter(
        x=df.index, y=df["NL"], name="Net Liquidity",
        line=dict(color="#1f77b4", width=2.5),
        fill="tozeroy", fillcolor="rgba(31,119,180,0.10)",
    ), row=1, col=1, secondary_y=False)

    fig.add_trace(go.Scatter(
        x=df.index, y=df["TGA"], name="TGA",
        line=dict(color="#2ca02c", width=1.5, dash="dash"),
    ), row=1, col=1, secondary_y=False)

    fig.add_trace(go.Scatter(
        x=df.index, y=df["RRP"], name="RRP",
        line=dict(color="#ff7f0e", width=1.5, dash="dash"),
    ), row=1, col=1, secondary_y=False)

    fig.add_trace(go.Scatter(
        x=df.index, y=df["WALCL"], name="WALCL (우축)",
        line=dict(color="#d62728", width=1.5, dash="dot"),
    ), row=1, col=1, secondary_y=True)

    fig.add_trace(go.Scatter(
        x=df.index, y=df["SP500"], name="S&P 500",
        line=dict(color="#333333", width=2),
    ), row=2, col=1)

    if "FV_NL" in df.columns and df["FV_NL"].notna().any():
        fig.add_trace(go.Scatter(
            x=df.index, y=df["FV_NL"], name="NL 회귀 FV",
            line=dict(color="#1f77b4", width=1.5),
        ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=df.index, y=[fv_pe] * len(df),
        name=f"P/E×EPS FV ({fv_pe:,.0f})",
        line=dict(color="#d62728", width=1.5, dash="dash"),
    ), row=2, col=1)

    grid_style = dict(showgrid=True, gridcolor="rgba(204,0,0,0.15)",
                      gridwidth=0.5, griddash="dot",
                      linecolor="#bbb", linewidth=1, showline=True,
                      ticks="outside", tickcolor="#bbb",
                      tickfont=dict(size=10, color="#555"))

    spx_vals = df["SP500"].dropna()
    spx_min = int(spx_vals.min() * 0.9) if len(spx_vals) else 500
    spx_max = int(spx_vals.max() * 1.05) if len(spx_vals) else 7500

    fig.update_layout(
        height=680,
        plot_bgcolor="#e8e8e8",
        paper_bgcolor="#ffffff",
        font=dict(family="Arial, sans-serif", size=11, color="#333"),
        hovermode="x unified",
        margin=dict(t=50, b=40, l=70, r=70),
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.01,
            xanchor="left", x=0,
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#ddd", borderwidth=1,
            font=dict(size=10),
        ),
    )

    fig.update_xaxes(**grid_style)

    fig.update_yaxes(
        **grid_style,
        title_text="NL · TGA · RRP (Billions)",
        title_font=dict(size=10, color="#555"),
        tickformat=",",
        ticksuffix="B",
        row=1, col=1, secondary_y=False,
    )
    fig.update_yaxes(
        title_text="WALCL",
        title_font=dict(size=10, color="#d62728"),
        tickfont=dict(size=10, color="#d62728"),
        tickformat=",",
        ticksuffix="B",
        showgrid=False,
        linecolor="#d62728",
        row=1, col=1, secondary_y=True,
    )
    fig.update_yaxes(
        **grid_style,
        title_text="Index Level",
        title_font=dict(size=10, color="#555"),
        tickformat=",",
        range=[spx_min, spx_max],
        row=2, col=1,
    )

    return fig.to_html(include_plotlyjs="cdn", full_html=False, config={"displayModeBar": True})


def refresh_data():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 데이터 갱신 시작...")
    try:
        df = build_data()
        cache["summary"] = build_summary(df)
        cache["chart_html"] = build_chart(df)
        cache["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cache["error"] = None
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 갱신 완료\n")
    except Exception as e:
        cache["error"] = str(e)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 오류: {e}\n")


def background_refresh():
    while True:
        time.sleep(REFRESH_INTERVAL)
        refresh_data()


@app.route("/")
def index():
    return render_template_string(
        HTML_TEMPLATE,
        chart_html=cache["chart_html"],
        summary=cache["summary"],
        updated_at=cache["updated_at"] or "—",
        error=cache["error"],
        refresh_interval=REFRESH_INTERVAL,
    )


@app.route("/refresh")
def manual_refresh():
    threading.Thread(target=refresh_data, daemon=True).start()
    return "ok"


def main():
    global API_KEY, FEPS, FPE, REFRESH_INTERVAL, START_DATE
    parser = argparse.ArgumentParser(description="Net Liquidity 대시보드 (2000~)")
    parser.add_argument("--key",     required=True,  help="FRED API Key")
    parser.add_argument("--feps",    type=float, default=270,  help="Forward EPS, 기본=270")
    parser.add_argument("--fpe",     type=float, default=21,   help="Forward P/E, 기본=21")
    parser.add_argument("--port",    type=int,   default=5000, help="포트, 기본=5000")
    parser.add_argument("--refresh", type=int,   default=3600, help="갱신 주기(초), 기본=3600")
    parser.add_argument("--start",   default="2000-01-01",     help="시작일, 기본=2000-01-01")
    args = parser.parse_args()

    API_KEY = args.key
    FEPS = args.feps
    FPE = args.fpe
    REFRESH_INTERVAL = args.refresh
    START_DATE = args.start

    print(f"\n  Net Liquidity Dashboard  ({START_DATE} ~ 현재)")
    print(f"  Forward EPS={FEPS}, P/E={FPE} → FV={FEPS*FPE:,.0f}")
    print(f"  갱신 주기: {REFRESH_INTERVAL//60}분")
    print(f"\n  초기 데이터 로딩 중 (2000년부터 전체 조회 — 10~20초 소요)...")
    refresh_data()

    threading.Thread(target=background_refresh, daemon=True).start()

    print(f"  브라우저: http://localhost:{args.port}")
    print(f"  종료: Ctrl+C\n")
    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
