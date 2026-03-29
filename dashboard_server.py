"""
Net Liquidity Dashboard (Railway 배포용)
========================================
환경변수:
  FRED_API_KEY     : FRED API Key (필수)
  FEPS             : Forward EPS (기본 270)
  FPE              : Forward P/E (기본 21)
  REFRESH_INTERVAL : 갱신 주기 초 (기본 3600)
  START_DATE       : 시작일 (기본 2000-01-01)
  PORT             : Railway 자동 설정

각 시리즈 업데이트 주기:
  WALCL      : 주간 (매주 목요일)
  WDTGAL     : 일간
  RRPONTSYD  : 일간
  SP500      : 일간
"""

import os
import threading
import time
import requests as req
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from flask import Flask, render_template_string
from datetime import datetime

API_KEY          = os.environ.get("FRED_API_KEY", "")
FEPS             = float(os.environ.get("FEPS", "270"))
FPE              = float(os.environ.get("FPE", "21"))
REFRESH_INTERVAL = int(os.environ.get("REFRESH_INTERVAL", "3600"))
START_DATE       = os.environ.get("START_DATE", "2000-01-01")
PORT             = int(os.environ.get("PORT", "5000"))

app = Flask(__name__)
cache = {"chart_html": None, "summary": None, "table_rows": None, "updated_at": None, "error": None}
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Net Liquidity Dashboard</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0;}
    body{font-family:Arial,'Segoe UI',sans-serif;background:#f0f0f0;color:#1a1a1a;}
    .header{background:#fff;border-bottom:2px solid #cc0000;padding:11px 24px;display:flex;align-items:center;justify-content:space-between;}
    .header h1{font-size:15px;font-weight:700;color:#333;}
    .badge{display:inline-block;font-size:10px;background:#cc0000;color:#fff;border-radius:2px;padding:1px 6px;margin-left:8px;font-weight:700;}
    .meta{font-size:11px;color:#666;}
    .refresh-btn{font-size:11px;padding:5px 12px;border:1px solid #cc0000;border-radius:2px;background:transparent;cursor:pointer;color:#cc0000;}
    .refresh-btn:hover{background:#fff0f0;}
    .container{max-width:1280px;margin:0 auto;padding:16px 20px;}
    .metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:10px;margin-bottom:16px;}
    .mc{background:#fff;border-radius:2px;padding:12px 14px;border:1px solid #ddd;border-top:3px solid #cc0000;}
    .mc-lbl{font-size:10px;color:#777;margin-bottom:4px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;}
    .mc-val{font-size:19px;font-weight:700;color:#111;font-family:'Courier New',monospace;}
    .mc-sub{font-size:11px;margin-top:3px;}
    .pos{color:#2ca02c;}.neg{color:#d62728;}.neu{color:#888;}
    .chart-box{background:#fff;border:1px solid #ddd;border-radius:2px;padding:4px;margin-bottom:12px;}
    .section-title{font-size:11px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;padding-left:2px;}
    .tbl-wrap{background:#fff;border:1px solid #ddd;border-radius:2px;overflow-x:auto;margin-bottom:12px;}
    table{width:100%;border-collapse:collapse;font-size:12px;font-family:'Courier New',monospace;}
    thead tr{background:#cc0000;color:#fff;}
    thead th{padding:8px 12px;text-align:right;font-weight:700;font-size:11px;white-space:nowrap;}
    thead th:first-child{text-align:left;}
    tbody tr:nth-child(even){background:#f9f9f9;}
    tbody tr:hover{background:#fff3f3;}
    tbody td{padding:7px 12px;text-align:right;border-bottom:1px solid #eee;white-space:nowrap;}
    tbody td:first-child{text-align:left;color:#555;}
    .badge-up{background:#e8f5e9;color:#2ca02c;padding:1px 5px;border-radius:2px;font-size:11px;}
    .badge-dn{background:#fff0f0;color:#d62728;padding:1px 5px;border-radius:2px;font-size:11px;}
    .summary-box{background:#fff;border:1px solid #ddd;border-top:3px solid #cc0000;border-radius:2px;padding:14px 18px;margin-bottom:12px;font-family:'Courier New',monospace;font-size:12px;}
    .summary-box .row{display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid #f0f0f0;}
    .summary-box .row:last-child{border-bottom:none;}
    .summary-box .lbl{color:#666;}
    .summary-box .val{font-weight:700;color:#111;}
    .divider{border:none;border-top:2px solid #cc0000;margin:4px 0 10px;}
    .freq-note{font-size:10px;color:#999;margin-bottom:12px;padding-left:2px;}
    .error{background:#fff0f0;border:1px solid #cc0000;border-radius:2px;padding:14px;color:#cc0000;margin-bottom:12px;font-size:13px;}
    .loading{text-align:center;padding:80px;color:#888;font-size:14px;}
    .loading p{margin-top:10px;font-size:12px;}
    .footer{font-size:10px;color:#aaa;text-align:center;padding:10px;border-top:1px solid #ddd;margin-top:4px;}
  </style>
  <script>
    let cd={{ refresh_interval }};
    function tick(){
      cd--;
      const el=document.getElementById('cd');
      if(el) el.textContent=Math.floor(cd/60)+'min '+String(cd%60).padStart(2,'0')+'s 후 자동갱신';
      if(cd<=0) location.reload();
      else setTimeout(tick,1000);
    }
    window.onload=function(){
      tick();
      {% if not summary and not error %}setTimeout(()=>location.reload(),10000);{% endif %}
    };
    function manualRefresh(){
      document.getElementById('cd').textContent='갱신 중...';
      fetch('/refresh').then(()=>setTimeout(()=>location.reload(),3000));
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
  <div class="loading">
    <div>FRED 데이터 로딩 중...</div>
    <p>2000년부터 전체 데이터 조회 중입니다. 잠시 후 자동으로 새로고침됩니다.</p>
  </div>
{% else %}

  <div class="metrics">
    <div class="mc">
      <div class="mc-lbl">Net Liquidity</div>
      <div class="mc-val">{{ summary.nl }}</div>
      <div class="mc-sub {{ 'pos' if summary.nl_chg_pos else 'neg' }}">{{ summary.nl_chg }}</div>
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
      <div class="mc-lbl">WALCL <span style="font-weight:400;color:#bbb;">주간</span></div>
      <div class="mc-val">{{ summary.walcl }}</div>
      <div class="mc-sub neu">{{ summary.walcl_date }}</div>
    </div>
    <div class="mc">
      <div class="mc-lbl">TGA <span style="font-weight:400;color:#bbb;">일간</span></div>
      <div class="mc-val">{{ summary.tga }}</div>
      <div class="mc-sub neu">{{ summary.tga_date }}</div>
    </div>
    <div class="mc">
      <div class="mc-lbl">RRP <span style="font-weight:400;color:#bbb;">일간</span></div>
      <div class="mc-val">{{ summary.rrp }}</div>
      <div class="mc-sub neu">{{ summary.rrp_date }}</div>
    </div>
  </div>

  <div class="chart-box">{{ chart_html | safe }}</div>

  <div class="section-title">요약</div>
  <div class="summary-box">
    <div class="row"><span class="lbl">기준일 (NL)</span><span class="val">{{ summary.base_date }}</span></div>
    <div class="row"><span class="lbl">WALCL ({{ summary.walcl_date }})</span><span class="val">{{ summary.walcl_raw }}</span></div>
    <div class="row"><span class="lbl">TGA ({{ summary.tga_date }})</span><span class="val">{{ summary.tga_raw }}</span></div>
    <div class="row"><span class="lbl">RRP ({{ summary.rrp_date }})</span><span class="val">{{ summary.rrp_raw }}</span></div>
    <div class="row"><span class="lbl">Net Liquidity</span><span class="val {{ 'pos' if summary.nl_chg_pos else 'neg' }}">{{ summary.nl_raw }} &nbsp;({{ summary.nl_chg }})</span></div>
    <hr class="divider">
    <div class="row"><span class="lbl">NL 회귀 공정가치</span><span class="val">{{ summary.fv_nl }}</span></div>
    <div class="row"><span class="lbl">SPX 현재가 (NL 기준)</span><span class="val {{ 'pos' if summary.fv_nl_cheap else 'neg' }}">{{ summary.spx_raw }} &nbsp;({{ summary.fv_nl_gap }})</span></div>
    <div class="row"><span class="lbl">P/E×EPS 공정가치</span><span class="val">{{ summary.fv_pe }}</span></div>
    <div class="row"><span class="lbl">SPX 현재가 (P/E 기준)</span><span class="val {{ 'pos' if summary.fv_pe_cheap else 'neg' }}">{{ summary.spx_raw }} &nbsp;({{ summary.fv_pe_gap }})</span></div>
  </div>

  <div class="section-title">최근 30일 데이터</div>
  <div class="freq-note">WALCL: 주간 | TGA·RRP·SP500: 일간 | NL = WALCL(최근값 유지) - TGA - RRP</div>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th>날짜</th>
          <th>WALCL (B)</th>
          <th>TGA (B)</th>
          <th>RRP (B)</th>
          <th>Net Liq (B)</th>
          <th>DoD</th>
          <th>SP500</th>
          <th>NL FV</th>
          <th>괴리율</th>
        </tr>
      </thead>
      <tbody>
        {% for row in table_rows %}
        <tr>
          <td>{{ row.date }}</td>
          <td>{{ row.walcl }}</td>
          <td>{{ row.tga }}</td>
          <td>{{ row.rrp }}</td>
          <td><strong>{{ row.nl }}</strong></td>
          <td>{% if row.dod_pos is not none %}<span class="{{ 'badge-up' if row.dod_pos else 'badge-dn' }}">{{ row.dod }}</span>{% else %}—{% endif %}</td>
          <td>{{ row.spx }}</td>
          <td>{{ row.fv_nl }}</td>
          <td>{% if row.gap is not none %}<span class="{{ 'badge-up' if row.gap_pos else 'badge-dn' }}">{{ row.gap }}</span>{% else %}—{% endif %}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

{% endif %}
  <div class="footer">
    Source: Federal Reserve Bank of St. Louis (FRED) &nbsp;|&nbsp; WALCL(주간) · WDTGAL(일간) · RRPONTSYD(일간) · SP500(일간) &nbsp;|&nbsp; 2000–present
  </div>
</div>
</body>
</html>
"""


def fetch_series(series_id, start, frequency="d"):
    params = dict(series_id=series_id, api_key=API_KEY, file_type="json",
                  observation_start=start, frequency=frequency)
    r = req.get(FRED_BASE, params=params, timeout=30)
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


def build_data():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] WALCL (주간)...")
    walcl = fetch_series("WALCL", START_DATE, frequency="w")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] WDTGAL (일간)...")
    tga = fetch_series("WDTGAL", START_DATE, frequency="d")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] RRPONTSYD (일간)...")
    rrp = fetch_series("RRPONTSYD", START_DATE, frequency="d")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] SP500 (일간)...")
    try:
        spx = fetch_series("SP500", START_DATE, frequency="d")
    except Exception:
        spx = pd.Series(dtype=float, name="SP500")

    # 일간 기준 DataFrame, WALCL은 forward fill (주간이므로)
    df = pd.DataFrame({"TGA": tga, "RRP": rrp, "SP500": spx}).sort_index()
    walcl_daily = walcl.reindex(df.index, method="ffill")
    df["WALCL"] = walcl_daily
    df = df.dropna(subset=["TGA", "RRP", "WALCL"])
    df["NL"] = df["WALCL"] - df["TGA"] - df["RRP"]
    df["NL_DoD"] = df["NL"].diff()

    # 차트용 월간 리샘플 (2000년~ 장기차트)
    df_monthly = df.resample("MS").last().dropna(subset=["WALCL", "TGA", "RRP"])
    df_monthly["NL"] = df_monthly["WALCL"] - df_monthly["TGA"] - df_monthly["RRP"]

    # 회귀는 월간으로
    valid = df_monthly[["NL", "SP500"]].dropna()
    if len(valid) >= 10:
        x, y = valid["NL"].values, valid["SP500"].values
        slope, intercept = np.polyfit(x, y, 1)
        r2 = np.corrcoef(x, y)[0, 1] ** 2
        print(f"  회귀 R²={r2:.3f}")
        df_monthly["FV_NL"] = slope * df_monthly["NL"] + intercept
        df["FV_NL"] = slope * df["NL"] + intercept
    else:
        df_monthly["FV_NL"] = np.nan
        df["FV_NL"] = np.nan

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 완료: 일간 {len(df)}개 / 월간 {len(df_monthly)}개")
    return df, df_monthly


def fmt_val(v):
    if abs(v) >= 1_000:
        return f"{v/1_000:.2f}T"
    return f"{v:,.0f}B"


def build_summary(df):
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else None
    fv_pe = FEPS * FPE
    spx = latest["SP500"] if not pd.isna(latest["SP500"]) else None
    fv_nl = latest["FV_NL"] if "FV_NL" in latest.index and not pd.isna(latest["FV_NL"]) else None
    chg = latest["NL"] - prev["NL"] if prev is not None else 0

    walcl_date = df["WALCL"].last_valid_index()
    tga_date   = df["TGA"].last_valid_index()
    rrp_date   = df["RRP"].last_valid_index()

    fv_nl_gap = fv_nl_cheap = None
    if fv_nl and spx:
        gap = (spx - fv_nl) / fv_nl * 100
        fv_nl_gap = f"{'+' if gap>0 else ''}{gap:.1f}% {'고평가' if gap>0 else '저평가'}"
        fv_nl_cheap = gap < 0

    fv_pe_gap = fv_pe_cheap = None
    if spx:
        gap2 = (spx - fv_pe) / fv_pe * 100
        fv_pe_gap = f"{'+' if gap2>0 else ''}{gap2:.1f}% {'고평가' if gap2>0 else '저평가'}"
        fv_pe_cheap = gap2 < 0

    return {
        "base_date": df.index[-1].strftime("%Y-%m-%d"),
        "nl": fmt_val(latest["NL"]), "nl_raw": f"{latest['NL']:,.0f}B",
        "nl_chg": f"{'▲' if chg>=0 else '▼'} {fmt_val(abs(chg))} DoD", "nl_chg_pos": chg >= 0,
        "walcl": fmt_val(latest["WALCL"]), "walcl_raw": f"{latest['WALCL']:,.0f}B",
        "walcl_date": walcl_date.strftime("%m-%d") if walcl_date else "—",
        "tga": fmt_val(latest["TGA"]), "tga_raw": f"{latest['TGA']:,.0f}B",
        "tga_date": tga_date.strftime("%m-%d") if tga_date else "—",
        "rrp": fmt_val(latest["RRP"]), "rrp_raw": f"{latest['RRP']:,.0f}B",
        "rrp_date": rrp_date.strftime("%m-%d") if rrp_date else "—",
        "spx_raw": f"{spx:,.0f}" if spx else "—",
        "fv_nl": f"{fv_nl:,.0f}" if fv_nl else "—",
        "fv_nl_gap": fv_nl_gap or "데이터 부족", "fv_nl_cheap": fv_nl_cheap,
        "fv_pe": f"{fv_pe:,.0f}", "fv_pe_gap": fv_pe_gap or "SPX 없음", "fv_pe_cheap": fv_pe_cheap,
    }


def build_table_rows(df):
    rows = []
    tail = df.tail(30).copy()
    for i, (date, row) in enumerate(tail.iterrows()):
        prev_nl = tail.iloc[i-1]["NL"] if i > 0 else None
        dod = row["NL"] - prev_nl if prev_nl is not None else None
        spx = row["SP500"] if not pd.isna(row["SP500"]) else None
        fv_nl = row["FV_NL"] if "FV_NL" in row.index and not pd.isna(row["FV_NL"]) else None
        gap = gap_pos = None
        if spx and fv_nl:
            g = (spx - fv_nl) / fv_nl * 100
            gap = f"{'+' if g>0 else ''}{g:.1f}%"
            gap_pos = g < 0
        rows.append({
            "date": date.strftime("%Y-%m-%d"),
            "walcl": f"{row['WALCL']:,.0f}",
            "tga": f"{row['TGA']:,.0f}",
            "rrp": f"{row['RRP']:,.0f}",
            "nl": f"{row['NL']:,.0f}",
            "dod": f"{'▲' if dod>=0 else '▼'}{abs(dod):,.0f}" if dod is not None else "—",
            "dod_pos": dod >= 0 if dod is not None else None,
            "spx": f"{spx:,.0f}" if spx else "—",
            "fv_nl": f"{fv_nl:,.0f}" if fv_nl else "—",
            "gap": gap, "gap_pos": gap_pos,
        })
    return list(reversed(rows))


def build_chart(df_monthly):
    fv_pe = FEPS * FPE
    recession_periods = [("2001-03-01","2001-11-01"),("2007-12-01","2009-06-01"),("2020-02-01","2020-04-01")]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
        subplot_titles=("Net Liquidity Components (2000–present)", "S&P 500 vs Fair Value (2000–present)"),
        vertical_spacing=0.10, row_heights=[0.5, 0.5],
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]])

    for s, e in recession_periods:
        for row in [1, 2]:
            fig.add_vrect(x0=s, x1=e, fillcolor="rgba(180,0,0,0.07)", layer="below", line_width=0, row=row, col=1)

    fig.add_trace(go.Scatter(x=df_monthly.index, y=df_monthly["NL"], name="Net Liquidity",
        line=dict(color="#1f77b4", width=2.5), fill="tozeroy", fillcolor="rgba(31,119,180,0.10)"),
        row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=df_monthly.index, y=df_monthly["TGA"], name="TGA",
        line=dict(color="#2ca02c", width=1.5, dash="dash")), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=df_monthly.index, y=df_monthly["RRP"], name="RRP",
        line=dict(color="#ff7f0e", width=1.5, dash="dash")), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=df_monthly.index, y=df_monthly["WALCL"], name="WALCL (우축)",
        line=dict(color="#d62728", width=1.5, dash="dot")), row=1, col=1, secondary_y=True)
    fig.add_trace(go.Scatter(x=df_monthly.index, y=df_monthly["SP500"], name="S&P 500",
        line=dict(color="#333333", width=2)), row=2, col=1)
    if "FV_NL" in df_monthly.columns and df_monthly["FV_NL"].notna().any():
        fig.add_trace(go.Scatter(x=df_monthly.index, y=df_monthly["FV_NL"], name="NL 회귀 FV",
            line=dict(color="#1f77b4", width=1.5)), row=2, col=1)
    fig.add_trace(go.Scatter(x=df_monthly.index, y=[fv_pe]*len(df_monthly), name=f"P/E×EPS FV ({fv_pe:,.0f})",
        line=dict(color="#d62728", width=1.5, dash="dash")), row=2, col=1)

    grid = dict(showgrid=True, gridcolor="rgba(204,0,0,0.15)", gridwidth=0.5, griddash="dot",
                linecolor="#bbb", linewidth=1, showline=True, ticks="outside", tickcolor="#bbb",
                tickfont=dict(size=10, color="#555"))
    spx_vals = df_monthly["SP500"].dropna()
    spx_min = int(spx_vals.min() * 0.9) if len(spx_vals) else 500
    spx_max = int(spx_vals.max() * 1.05) if len(spx_vals) else 7500

    fig.update_layout(height=680, plot_bgcolor="#e8e8e8", paper_bgcolor="#ffffff",
        font=dict(family="Arial,sans-serif", size=11, color="#333"), hovermode="x unified",
        margin=dict(t=50, b=40, l=70, r=70),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0,
                    bgcolor="rgba(255,255,255,0.85)", bordercolor="#ddd", borderwidth=1, font=dict(size=10)))
    fig.update_xaxes(**grid)
    fig.update_yaxes(**grid, title_text="NL·TGA·RRP (B)", title_font=dict(size=10, color="#555"),
                     tickformat=",", ticksuffix="B", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="WALCL", title_font=dict(size=10, color="#d62728"),
                     tickfont=dict(size=10, color="#d62728"), tickformat=",", ticksuffix="B",
                     showgrid=False, linecolor="#d62728", row=1, col=1, secondary_y=True)
    fig.update_yaxes(**grid, title_text="Index Level", title_font=dict(size=10, color="#555"),
                     tickformat=",", range=[spx_min, spx_max], row=2, col=1)

    return fig.to_html(include_plotlyjs="cdn", full_html=False, config={"displayModeBar": True})


def refresh_data():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 갱신 시작...")
    try:
        df, df_monthly = build_data()
        cache["summary"] = build_summary(df)
        cache["chart_html"] = build_chart(df_monthly)
        cache["table_rows"] = build_table_rows(df)
        cache["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cache["error"] = None
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 갱신 완료\n")
    except Exception as e:
        cache["error"] = str(e)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 오류: {e}\n")


def background_loop():
    refresh_data()
    while True:
        time.sleep(REFRESH_INTERVAL)
        refresh_data()


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE,
        chart_html=cache["chart_html"], summary=cache["summary"],
        table_rows=cache["table_rows"] or [],
        updated_at=cache["updated_at"] or "—",
        error=cache["error"], refresh_interval=REFRESH_INTERVAL)


@app.route("/refresh")
def manual_refresh():
    threading.Thread(target=refresh_data, daemon=True).start()
    return "ok"


@app.route("/health")
def health():
    return "ok"


threading.Thread(target=background_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
