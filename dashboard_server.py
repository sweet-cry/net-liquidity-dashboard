"""
Net Liquidity Dashboard (Railway 배포용)
========================================
환경변수:
  FRED_API_KEY     : FRED API Key (필수)
  REFRESH_INTERVAL : 갱신 주기 초 (기본 3600)
  START_DATE       : 시작일 (기본 2000-01-01)
  PORT             : Railway 자동 설정
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
REFRESH_INTERVAL = int(os.environ.get("REFRESH_INTERVAL", "3600"))
START_DATE       = os.environ.get("START_DATE", "2000-01-01")
PORT             = int(os.environ.get("PORT", "5000"))

app = Flask(__name__)
cache = {"chart_html": None, "summary": None, "table_rows": None,
         "updated_at": None, "error": None, "model_info": None}
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
    .header{background:#fff;border-bottom:2px solid #cc0000;padding:11px 24px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;}
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
    .method-box{background:#fff;border:1px solid #ddd;border-left:4px solid #cc0000;border-radius:2px;padding:16px 18px;margin-bottom:12px;font-size:12px;line-height:1.7;}
    .method-box h3{font-size:12px;font-weight:700;color:#cc0000;margin-bottom:8px;text-transform:uppercase;letter-spacing:.5px;}
    .method-box .formula{font-family:'Courier New',monospace;background:#f8f8f8;border:1px solid #eee;padding:8px 12px;border-radius:2px;margin:6px 0;font-size:12px;color:#333;}
    .method-box .desc{color:#555;margin:4px 0;}
    .method-box .warn{color:#888;font-size:11px;margin-top:8px;padding-top:8px;border-top:1px dashed #ddd;}
    .model-info{background:#f8f8f8;border:1px solid #eee;border-radius:2px;padding:8px 12px;margin-top:8px;font-family:'Courier New',monospace;font-size:11px;color:#555;}
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
  <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">
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
    <div class="mc">
      <div class="mc-lbl">S&P 500</div>
      <div class="mc-val">{{ summary.spx_raw }}</div>
      <div class="mc-sub neu">{{ summary.base_date }}</div>
    </div>
  </div>

  <div class="chart-box">{{ chart_html | safe }}</div>

  <div class="section-title">계산 방법론</div>
  <div class="method-box">
    <h3>1. Net Liquidity</h3>
    <div class="formula">NL = WALCL − TGA − RRP</div>
    <div class="desc"><b>WALCL</b>: Fed 총자산 — 많을수록 시중에 돈이 많이 풀린 상태</div>
    <div class="desc"><b>TGA 차감</b>: 재무부가 Fed에 예치한 현금 — 시장에 풀리지 않은 돈</div>
    <div class="desc"><b>RRP 차감</b>: MMF 등이 Fed에 맡긴 역레포 잔액 — 역시 시장 밖에 있는 돈</div>
    <div class="desc" style="margin-top:6px;">→ Michael Howell(CrossBorder Capital), Lyn Alden 등 매크로 분석가들이 대중화한 공식. Fed 유동성이 실제로 시장에 얼마나 풀려있는지 측정.</div>

    <h3 style="margin-top:14px;">2. NL 회귀 공정가치 (Regression FV)</h3>
    <div class="formula">SPX_FV = slope × NL + intercept</div>
    <div class="desc">2000년부터 현재까지 일간 데이터로 선형회귀 적합. NL이 높을수록 SPX 공정가치도 높아지는 관계를 모델링.</div>
    {% if model_info %}
    <div class="model-info">
      slope={{ model_info.slope }} &nbsp;|&nbsp; intercept={{ model_info.intercept }} &nbsp;|&nbsp; R²={{ model_info.r2 }} &nbsp;|&nbsp; 샘플={{ model_info.n }}개
    </div>
    {% endif %}

    <h3 style="margin-top:14px;">3. 괴리율</h3>
    <div class="formula">괴리율 = (SPX현재가 − FV) / FV × 100 (%)</div>
    <div class="desc">양수(+): SPX가 NL 기반 공정가치 대비 고평가 &nbsp;|&nbsp; 음수(−): 저평가</div>

    <div class="warn">
      ※ 주의: NL과 SPX의 상관관계(R²≈0.6~0.8)는 표본 기간에 의존하며, 인과관계가 아닌 상관관계입니다. 2008·2020 QE 이후 구조 변화가 반영되어 있어 절대적 FV보다는 <b>방향성·괴리 추세</b> 위주로 활용하는 것이 적합합니다.
    </div>
  </div>

  <div class="section-title">요약</div>
  <div class="summary-box">
    <div class="row"><span class="lbl">기준일</span><span class="val">{{ summary.base_date }}</span></div>
    <div class="row"><span class="lbl">WALCL ({{ summary.walcl_date }})</span><span class="val">{{ summary.walcl_raw }}</span></div>
    <div class="row"><span class="lbl">TGA ({{ summary.tga_date }})</span><span class="val">{{ summary.tga_raw }}</span></div>
    <div class="row"><span class="lbl">RRP ({{ summary.rrp_date }})</span><span class="val">{{ summary.rrp_raw }}</span></div>
    <div class="row"><span class="lbl">Net Liquidity</span><span class="val {{ 'pos' if summary.nl_chg_pos else 'neg' }}">{{ summary.nl_raw }} &nbsp;({{ summary.nl_chg }})</span></div>
    <hr class="divider">
    <div class="row"><span class="lbl">NL 회귀 공정가치</span><span class="val">{{ summary.fv_nl }}</span></div>
    <div class="row"><span class="lbl">SPX 현재가</span><span class="val {{ 'pos' if summary.fv_nl_cheap else 'neg' }}">{{ summary.spx_raw }} &nbsp;({{ summary.fv_nl_gap }})</span></div>
  </div>

  <div class="section-title">최근 10일 데이터</div>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th>날짜</th><th>WALCL (B)</th><th>TGA (B)</th><th>RRP (B)</th>
          <th>Net Liq (B)</th><th>DoD</th><th>SP500</th><th>NL FV</th><th>괴리율</th>
        </tr>
      </thead>
      <tbody>
        {% for row in table_rows %}
        <tr>
          <td>{{ row.date }}</td><td>{{ row.walcl }}</td><td>{{ row.tga }}</td><td>{{ row.rrp }}</td>
          <td><strong>{{ row.nl }}</strong></td>
          <td>{% if row.dod_pos is not none %}<span class="{{ 'badge-up' if row.dod_pos else 'badge-dn' }}">{{ row.dod }}</span>{% else %}—{% endif %}</td>
          <td>{{ row.spx }}</td><td>{{ row.fv_nl }}</td>
          <td>{% if row.gap is not none %}<span class="{{ 'badge-up' if row.gap_pos else 'badge-dn' }}">{{ row.gap }}</span>{% else %}—{% endif %}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

{% endif %}
  <div class="footer">
    Source: Federal Reserve Bank of St. Louis (FRED) &nbsp;|&nbsp; WALCL(주간) · WDTGAL · RRPONTSYD · SP500 &nbsp;|&nbsp; 2000–present
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


def fetch_auto(series_id, start, preferred="d"):
    for freq in [preferred, "w", "bw", "m"]:
        try:
            s = fetch_series(series_id, start, frequency=freq)
            if len(s) > 0:
                print(f"  [{series_id}] frequency={freq}")
                return s, freq
        except Exception:
            continue
    raise ValueError(f"{series_id}: 사용 가능한 frequency 없음")


def build_data():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] WALCL...")
    walcl_w = fetch_series("WALCL", START_DATE, frequency="w")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] WDTGAL...")
    tga_d, tga_freq = fetch_auto("WDTGAL", START_DATE, preferred="d")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] RRPONTSYD...")
    rrp_d, rrp_freq = fetch_auto("RRPONTSYD", START_DATE, preferred="d")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] SP500...")
    try:
        spx_d, _ = fetch_auto("SP500", START_DATE, preferred="d")
    except Exception:
        spx_d = pd.Series(dtype=float, name="SP500")

    # TGA/RRP가 주간이면 일간 인덱스 기준으로 ffill
    df = pd.DataFrame({"SP500": spx_d}).sort_index()
    df["TGA"]   = tga_d.reindex(df.index, method="ffill")
    df["RRP"]   = rrp_d.reindex(df.index, method="ffill")
    df["WALCL"] = walcl_w.reindex(df.index, method="ffill")
    df = df.dropna(subset=["TGA", "RRP", "WALCL"])
    df["NL"] = df["WALCL"] - df["TGA"] - df["RRP"]
    df["NL_DoD"] = df["NL"].diff()

    # 선형회귀
    valid = df[["NL", "SP500"]].dropna()
    model_info = None
    if len(valid) >= 10:
        x, y = valid["NL"].values, valid["SP500"].values
        slope, intercept = np.polyfit(x, y, 1)
        r2 = np.corrcoef(x, y)[0, 1] ** 2
        print(f"  회귀: slope={slope:.5f}, intercept={intercept:.1f}, R²={r2:.3f}, n={len(valid)}")
        df["FV_NL"] = slope * df["NL"] + intercept
        model_info = {
            "slope": f"{slope:.5f}",
            "intercept": f"{intercept:.1f}",
            "r2": f"{r2:.3f}",
            "n": f"{len(valid):,}",
        }
    else:
        df["FV_NL"] = np.nan

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 완료: {len(df)}개")
    return df, model_info


def fmt_val(v):
    if abs(v) >= 1_000:
        return f"{v/1_000:.2f}T"
    return f"{v:,.0f}B"


def build_summary(df):
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else None
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
        "fv_nl_gap": fv_nl_gap or "데이터 부족",
        "fv_nl_cheap": fv_nl_cheap,
    }


def build_table_rows(df):
    tail = df.tail(11).copy()
    rows = []
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
    return list(reversed(rows[-10:]))


def build_chart(df):
    recession_periods = [
        ("2001-03-01","2001-11-01"),
        ("2007-12-01","2009-06-01"),
        ("2020-02-01","2020-04-01"),
    ]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
        subplot_titles=("Net Liquidity · TGA · RRP — Daily (2000–present)",
                        "S&P 500 vs NL Regression FV — Daily (2000–present)"),
        vertical_spacing=0.10, row_heights=[0.5, 0.5])

    for s, e in recession_periods:
        for row in [1, 2]:
            fig.add_vrect(x0=s, x1=e, fillcolor="rgba(180,0,0,0.07)",
                          layer="below", line_width=0, row=row, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df["NL"], name="Net Liquidity",
        line=dict(color="#1f77b4", width=2),
        fill="tozeroy", fillcolor="rgba(31,119,180,0.10)"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["TGA"], name="TGA",
        line=dict(color="#2ca02c", width=1.5, dash="dash")), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["RRP"], name="RRP",
        line=dict(color="#ff7f0e", width=1.5, dash="dash")), row=1, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df["SP500"], name="S&P 500",
        line=dict(color="#333333", width=2)), row=2, col=1)
    if "FV_NL" in df.columns and df["FV_NL"].notna().any():
        fig.add_trace(go.Scatter(x=df.index, y=df["FV_NL"], name="NL 회귀 FV",
            line=dict(color="#1f77b4", width=1.5)), row=2, col=1)

    grid = dict(showgrid=True, gridcolor="rgba(204,0,0,0.15)", gridwidth=0.5, griddash="dot",
                linecolor="#bbb", linewidth=1, showline=True, ticks="outside", tickcolor="#bbb",
                tickfont=dict(size=10, color="#555"))
    spx_vals = df["SP500"].dropna()
    spx_min = int(spx_vals.min() * 0.9) if len(spx_vals) else 500
    spx_max = int(spx_vals.max() * 1.05) if len(spx_vals) else 7500

    fig.update_layout(
        height=680, plot_bgcolor="#e8e8e8", paper_bgcolor="#ffffff",
        font=dict(family="Arial,sans-serif", size=11, color="#333"),
        hovermode="x unified", margin=dict(t=50, b=40, l=70, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0,
                    bgcolor="rgba(255,255,255,0.85)", bordercolor="#ddd", borderwidth=1, font=dict(size=10)),
    )
    fig.update_xaxes(**grid)
    fig.update_yaxes(**grid, title_text="Billions USD", title_font=dict(size=10, color="#555"),
                     tickformat=",", ticksuffix="B", row=1, col=1)
    fig.update_yaxes(**grid, title_text="Index Level", title_font=dict(size=10, color="#555"),
                     tickformat=",", range=[spx_min, spx_max], row=2, col=1)
    return fig.to_html(include_plotlyjs="cdn", full_html=False, config={"displayModeBar": True})


def refresh_data():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 갱신 시작...")
    try:
        df, model_info = build_data()
        cache["summary"] = build_summary(df)
        cache["chart_html"] = build_chart(df)
        cache["table_rows"] = build_table_rows(df)
        cache["model_info"] = model_info
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
        error=cache["error"], refresh_interval=REFRESH_INTERVAL,
        model_info=cache["model_info"])


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
