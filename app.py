import streamlit as st
import streamlit.components.v1 as components
import requests
import pandas as pd
import numpy as np
import json
import re
import calendar
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

st.set_page_config(page_title="코인 레이더", page_icon="📡", layout="centered")

st.markdown("""
<style>
    .block-container { padding: 1rem 0.8rem 3rem 0.8rem; max-width: 620px; }
    header, footer { visibility: hidden; }
    [data-stale="true"] {
        opacity: 1 !important;
        transition: none !important;
    }
    [data-testid="stStatusWidget"] {
        visibility: hidden !important;
    }
    .metric-card {
        background-color: #161B22; border: 1px solid #30363D;
        border-radius: 12px; padding: 12px 14px; margin-bottom: 10px;
    }
    .coin-card {
        background-color: #161B22; border: 1px solid #30363D;
        border-left: 4px solid #00D084; border-radius: 10px;
        padding: 14px; margin-bottom: 12px;
    }
    .coin-card-short { border-left-color: #FF4B4B; }
    .coin-card-neutral { border-left-color: #8B949E; }
    .badge-long {
        background-color: rgba(0, 208, 132, 0.15); color: #00D084;
        padding: 3px 8px; border-radius: 6px; font-weight: bold; font-size: 0.78rem;
        display: inline-block;
    }
    .badge-short {
        background-color: rgba(255, 75, 75, 0.15); color: #FF4B4B;
        padding: 3px 8px; border-radius: 6px; font-weight: bold; font-size: 0.78rem;
        display: inline-block;
    }
    .badge-neutral {
        background-color: rgba(139, 148, 158, 0.15); color: #C9D1D9;
        padding: 3px 8px; border-radius: 6px; font-weight: bold; font-size: 0.78rem;
        display: inline-block;
    }
    .reason-box {
        background-color: #0D1117; border: 1px solid #21262D;
        border-radius: 8px; padding: 10px 12px;
        margin-top: 8px; font-size: 0.84rem; line-height: 1.58; color: #C9D1D9;
    }
    .lev-box {
        background-color: rgba(88, 166, 255, 0.1); border: 1px solid rgba(88, 166, 255, 0.3);
        border-radius: 8px; padding: 8px 10px; margin-top: 8px;
        font-size: 0.83rem; color: #79C0FF;
    }
    .news-card {
        background-color: #161B22; border: 1px solid #30363D;
        border-radius: 10px; padding: 12px 14px; margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

KST = timezone(timedelta(hours=9))

def safe_get_json(url, headers=None, timeout=4):
    try:
        return requests.get(url, headers=headers, timeout=timeout).json()
    except Exception:
        return None

# ================= 1. 병렬 시장 요약 & 매크로 데이터 수집 =================
@st.cache_data(ttl=120)
def get_market_overview():
    urls = {
        "btc": "https://data-api.binance.vision/api/v3/ticker/24hr?symbol=BTCUSDT",
        "fund": "https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP",
        "fng": "https://api.alternative.me/fng/",
        "dom": "https://api.coingecko.com/api/v3/global"
    }
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {k: ex.submit(safe_get_json, u) for k, u in urls.items()}
        res = {k: f.result() for k, f in futures.items()}

    btc_price_num, btc_chg_num = 0.0, 0.0
    if res["btc"] and "lastPrice" in res["btc"]:
        btc_price_num = float(res["btc"]["lastPrice"])
        btc_chg_num = float(res["btc"]["priceChangePercent"])

    funding_rate, funding_num = "N/A", 0.0
    if res["fund"] and res["fund"].get("data"):
        funding_num = float(res["fund"]["data"][0]["fundingRate"]) * 100
        funding_rate = f"{funding_num:.4f}%"

    fng_val, fng_class = 50, "N/A"
    if res["fng"] and res["fng"].get("data"):
        fng_val = int(res["fng"]["data"][0]["value"])
        fng_class = res["fng"]["data"][0]["value_classification"]

    btc_dom = "N/A"
    if res["dom"] and res["dom"].get("data"):
        btc_dom = f"{res['dom']['data']['market_cap_percentage']['btc']:.1f}%"

    return {
        "fng_val": fng_val, "fng_class": fng_class, "btc_dom": btc_dom,
        "btc_price_num": btc_price_num, "btc_chg_num": btc_chg_num,
        "funding_rate": funding_rate, "funding_num": funding_num
    }

def render_realtime_top_board(ov):
    init_price = f"${ov['btc_price_num']:,.1f}" if ov["btc_price_num"] > 0 else "연결 중..."
    init_chg = f"{ov['btc_chg_num']:+.2f}%"
    init_col = "#00D084" if ov["btc_chg_num"] >= 0 else "#FF4B4B"

    html = f"""
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; font-family:sans-serif;">
      <div style="background:#161B22; border:1px solid #30363D; border-radius:12px; padding:12px 14px;">
        <div style="font-size:12px; color:#8B949E; display:flex; justify-content:space-between;">
          <span>BTC 현물 실시간</span>
          <span style="color:#00D084; font-weight:bold;">● LIVE</span>
        </div>
        <div style="margin-top:4px;">
          <span id="btc-live-price" style="font-size:18px; font-weight:bold; color:#F0F6FC;">{init_price}</span>
          <span id="btc-live-chg" style="font-size:12px; font-weight:bold; color:{init_col}; margin-left:4px;">({init_chg})</span>
        </div>
        <div style="font-size:12px; color:#58A6FF; margin-top:4px;">선물 펀딩비: {ov['funding_rate']}</div>
      </div>

      <div style="background:#161B22; border:1px solid #30363D; border-radius:12px; padding:12px 14px;">
        <div style="font-size:12px; color:#8B949E;">공포·탐욕(일일) / 도미넌스</div>
        <div style="font-size:18px; font-weight:bold; color:#F0F6FC; margin-top:4px;">
          {ov['fng_val']} <span style="font-size:12px; font-weight:normal; color:#C9D1D9;">({ov['fng_class']})</span>
        </div>
        <div style="font-size:12px; color:#D2A8FF; margin-top:4px;">도미넌스: {ov['btc_dom']}</div>
      </div>
    </div>
    <script>
      const priceEl = document.getElementById('btc-live-price');
      const chgEl = document.getElementById('btc-live-chg');
      let lastPrice = {ov['btc_price_num']};
      function connectWS() {{
        const ws = new WebSocket('wss://stream.binance.com:9443/ws/btcusdt@ticker');
        ws.onmessage = (event) => {{
          const d = JSON.parse(event.data);
          const p = parseFloat(d.c);
          const chg = parseFloat(d.P);
          priceEl.textContent = '$' + p.toLocaleString('en-US', {{minimumFractionDigits: 1, maximumFractionDigits: 1}});
          priceEl.style.color = p >= lastPrice ? '#00D084' : '#FF4B4B';
          setTimeout(() => {{ priceEl.style.color = '#F0F6FC'; }}, 350);
          lastPrice = p;
          chgEl.textContent = '(' + (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%)';
          chgEl.style.color = chg >= 0 ? '#00D084' : '#FF4B4B';
        }};
        ws.onclose = () => setTimeout(connectWS, 3000);
      }}
      connectWS();
    </script>
    """
    components.html(html, height=96)

@st.cache_data(ttl=120)
def get_macro_indices():
    indices = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    targets = [
        ("🇺🇸 나스닥 (NASDAQ)", "^IXIC", ""),
        ("🇺🇸 S&P 500", "^GSPC", ""),
        ("🥇 국제 금 (Gold)", "GC=F", "$"),
        ("💵 원/달러 환율", "KRW=X", "₩")
    ]
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {
            name: (prefix, ex.submit(safe_get_json, f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}?interval=1d&range=5d", headers))
            for name, tk, prefix in targets
        }
        for name, (prefix, fut) in futs.items():
            res = fut.result()
            try:
                meta = res["chart"]["result"][0]["meta"]
                cur = float(meta["regularMarketPrice"])
                prev = float(meta["chartPreviousClose"])
                chg = ((cur - prev) / prev) * 100
                indices[name] = {"price": f"{prefix}{cur:,.2f}", "chg": chg}
            except Exception:
                indices[name] = {"price": "N/A", "chg": 0.0}
    return indices

@st.cache_data(ttl=120)
def fetch_spot_klines(symbol, interval, limit=140):
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    data = requests.get(url, timeout=4).json()
    df = pd.DataFrame(data, columns=[
        "time", "open", "high", "low", "close", "volume",
        "close_time", "qav", "num_trades", "taker_base_vol", "taker_quote_vol", "ignore"
    ])
    df["ts"] = (df["time"].astype(np.int64) // 1000) + (9 * 3600)
    for col in ["open", "high", "low", "close", "volume", "taker_base_vol"]:
        df[col] = df[col].astype(float)
    return df

def calc_indicators(df):
    df = df.copy()
    df["ema7"] = df["close"].ewm(span=7, adjust=False).mean()
    df["ema25"] = df["close"].ewm(span=25, adjust=False).mean()
    df["ema99"] = df["close"].ewm(span=99, adjust=False).mean()
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df["rsi"] = 100 - (100 / (1 + (gain / loss)))
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["hist"] = df["macd"] - df["signal"]
    tr = pd.concat([
        df["high"] - df["low"],
        np.abs(df["high"] - df["close"].shift()),
        np.abs(df["low"] - df["close"].shift())
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    df["buy_vol"] = df["taker_base_vol"]
    df["sell_vol"] = df["volume"] - df["taker_base_vol"]
    df["delta"] = df["buy_vol"] - df["sell_vol"]
    df["cvd"] = df["delta"].cumsum()
    return df

@st.cache_data(ttl=55)
def get_spot_orderbook_heatmap(symbol="BTCUSDT"):
    url = f"https://data-api.binance.vision/api/v3/depth?symbol={symbol}&limit=500"
    depth = requests.get(url, timeout=4).json()
    bids = pd.DataFrame(depth["bids"], columns=["price", "qty"]).astype(float)
    asks = pd.DataFrame(depth["asks"], columns=["price", "qty"]).astype(float)
    bids["notional"] = bids["price"] * bids["qty"]
    asks["notional"] = asks["price"] * asks["qty"]

    bids["bin"] = np.floor(bids["price"] / 100) * 100
    asks["bin"] = np.ceil(asks["price"] / 100) * 100
    bid_grp = bids.groupby("bin")["notional"].sum().reset_index()
    bid_grp["side"] = "BID"
    ask_grp = asks.groupby("bin")["notional"].sum().reset_index()
    ask_grp["side"] = "ASK"

    combined = pd.concat([ask_grp.head(6), bid_grp.tail(6)]).sort_values("bin", ascending=False)
    top_bid_price = float(bid_grp.loc[bid_grp["notional"].idxmax(), "bin"])
    top_bid_vol = float(bid_grp["notional"].max())
    top_ask_price = float(ask_grp.loc[ask_grp["notional"].idxmax(), "bin"])
    top_ask_vol = float(ask_grp["notional"].max())
    return combined, top_bid_price, top_bid_vol, top_ask_price, top_ask_vol

# ================= 2. 현물 엘리어트 파동(꼬리 규칙) & 피보나치 확장 예측 =================
def fmt_p(val):
    return f"${val:,.4f}" if val < 10 else f"${val:,.1f}"

def analyze_spot_wave_and_fib(df, tf_name):
    sub = df.tail(120).copy().reset_index(drop=True)
    last_close = float(sub["close"].iloc[-1])
    last_low = float(sub["low"].iloc[-1])
    rsi_val = float(sub["rsi"].iloc[-1]) if not np.isnan(sub["rsi"].iloc[-1]) else 50.0

    n = len(sub)
    q1, q2, q3 = sub.iloc[:n//4], sub.iloc[n//4:n//2], sub.iloc[n//2:3*n//4]
    q4 = sub.iloc[3*n//4:]

    w0_low = float(q1["low"].min())
    w1_high = float(q2["high"].max())
    w2_low = float(q2["low"].min())
    w3_high = float(q3["high"].max())
    w4_low = float(q4["low"].min())

    wave1_len = max(w1_high - w0_low, (w3_high - w2_low) * 0.618)
    anchor_low = min(w4_low, last_low)
    fib_ext_100 = anchor_low + wave1_len * 1.0
    fib_ext_1618 = anchor_low + wave1_len * 1.618

    drop_len = max(w3_high - w4_low, wave1_len * 0.618)
    fib_down_100 = w3_high - drop_len * 1.0

    swing_range = max(w3_high - w0_low, 1e-9)
    fib_ret_382 = w3_high - swing_range * 0.382
    fib_ret_618 = w3_high - swing_range * 0.618

    up_100_pct = (fib_ext_100 - last_close) / last_close * 100
    up_1618_pct = (fib_ext_1618 - last_close) / last_close * 100
    dn_100_pct = (fib_down_100 - last_close) / last_close * 100

    wick_violated = w4_low <= w1_high

    if not wick_violated and last_close > w1_high:
        badge = '<span class="badge-long">🟢 메인: 4파 눌림목 유효 → 5파 상승 여력</span>'
        main_scen = (
            f"현물 차트 기준 최근 저점 꼬리(<b>{fmt_p(w4_low)}</b>)가 1파 고점 꼬리(<b>{fmt_p(w1_high)}</b>)를 침범하지 않고 지켜냈습니다. "
            f"1차 피보나치 확장 목표는 <b>{fmt_p(fib_ext_100)} ({up_100_pct:+.1f}%)</b>, "
            f"강한 5파 연장 시 1.618 확장 목표는 <b>{fmt_p(fib_ext_1618)} ({up_1618_pct:+.1f}%)</b>입니다."
        )
        alt_scen = (
            f"현물 캔들 꼬리가 1파 고점 <b>{fmt_p(w1_high)}</b> 아래로 내려가면 기존 4파 상승 카운팅은 즉시 <b>무효화</b>되며, "
            f"대형 ABC 하락 파동(1차 하방 목표 <b>{fmt_p(fib_down_100)}</b>)으로 전환해야 합니다."
        )
    else:
        badge = '<span class="badge-short">🔴 1파 고점 꼬리 침범 → ABC 조정·하락 전환</span>'
        main_scen = (
            f"현물 저점 꼬리(<b>{fmt_p(w4_low)}</b>)가 직전 1파 고점(<b>{fmt_p(w1_high)}</b>)을 침범해 일반 상승 파동(1-2-3-4-5)은 무효화되었습니다. "
            f"현재는 ABC 하락 조정 파동이 우세하며, 하방 피보나치 1.0 목표는 <b>{fmt_p(fib_down_100)} ({dn_100_pct:+.1f}%)</b> 구간입니다."
        )
        alt_scen = (
            f"만약 <b>{fmt_p(fib_ret_618)}</b> 지지선을 방어하고 직전 고점 <b>{fmt_p(w3_high)}</b>을 돌파 안착한다면, "
            f"쐐기형(다이아고날) 파동으로 재해석되어 <b>{fmt_p(fib_ext_100)} ({up_100_pct:+.1f}%)</b>까지 반등 시나리오가 다시 열립니다."
        )

    chart_lines = [
        {"price": w1_high, "color": "#FF4B4B", "width": 2, "style": 2, "title": "⚠️ 파동무효화(1파고점)"},
        {"price": fib_ext_100, "color": "#00D084", "width": 1, "style": 1, "title": "🎯 Fib 1.0 목표"},
        {"price": fib_ext_1618, "color": "#58A6FF", "width": 1, "style": 1, "title": "🎯 Fib 1.618 확장"},
        {"price": fib_ret_618, "color": "#FFA657", "width": 1, "style": 3, "title": "되돌림 0.618"}
    ]

    html_desc = (
        f"{badge} <span style='font-size:0.76rem; color:#8B949E;'>· 현물(Spot) 기준 · RSI {rsi_val:.1f}</span>"
        f"<div style='margin-top:6px;'><b style='color:#7EE787;'>[🟢 메인 시나리오 · 피보나치 예측]</b><br>{main_scen}</div>"
        f"<div style='margin-top:6px;'><b style='color:#FF7B72;'>[🔴 대안 시나리오 · 무효화 기준]</b><br>{alt_scen}</div>"
    )
    return html_desc, chart_lines, w1_high, fib_ext_100, fib_ext_1618, fib_ret_618, fib_ret_382

# ================= 3. 트레이딩뷰 모바일 캔들 & CVD 차트 렌더러 =================
def render_tv_candle_chart(df, chart_id, price_lines=None, show_ema=True, show_waves=True, height=340):
    sub = df.copy().reset_index(drop=True)
    candles = [
        {"time": int(r["ts"]), "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"])}
        for _, r in sub.iterrows()
    ]
    ema7_data = [{"time": int(r["ts"]), "value": float(r["ema7"])} for _, r in sub.iterrows() if not np.isnan(r["ema7"])]
    ema25_data = [{"time": int(r["ts"]), "value": float(r["ema25"])} for _, r in sub.iterrows() if not np.isnan(r["ema25"])]
    ema99_data = [{"time": int(r["ts"]), "value": float(r["ema99"])} for _, r in sub.iterrows() if not np.isnan(r["ema99"])]

    last_price = float(sub["close"].iloc[-1])
    if last_price < 1:
        prec, min_move = 4, 0.0001
    elif last_price < 50:
        prec, min_move = 3, 0.001
    else:
        prec, min_move = 2, 0.01

    markers = []
    if show_waves and len(sub) >= 24:
        step = max(6, len(sub) // 7)
        pivots = []
        for i in range(0, len(sub), step):
            chunk = sub.iloc[i:i+step]
            if len(pivots) % 2 == 0:
                idx = chunk["low"].idxmin()
                pivots.append((int(sub.loc[idx, "ts"]), "belowBar", "#E3B341", "arrowUp"))
            else:
                idx = chunk["high"].idxmax()
                pivots.append((int(sub.loc[idx, "ts"]), "aboveBar", "#E3B341", "arrowDown"))
        wave_labels = ["1파", "2파", "3파", "4파", "5파", "A파", "B파", "C파"][:len(pivots)]
        for (ts_val, pos, col, shp), lbl in zip(pivots, wave_labels):
            markers.append({"time": ts_val, "position": pos, "color": col, "shape": shp, "text": lbl})

    lines_json = json.dumps(price_lines or [])
    ema_flag = "true" if show_ema else "false"
    html_code = f"""
    <div id="{chart_id}" style="width: 100%; height: {height}px; background: #0D1117; border-radius: 10px; overflow: hidden;"></div>
    <script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
    <script>
      const container = document.getElementById('{chart_id}');
      const initW = container.clientWidth || window.innerWidth || 560;
      const chart = LightweightCharts.createChart(container, {{
        width: initW,
        height: {height},
        layout: {{ background: {{ color: '#0D1117' }}, textColor: '#C9D1D9' }},
        grid: {{ vertLines: {{ color: '#1F242C' }}, horzLines: {{ color: '#1F242C' }} }},
        crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
        rightPriceScale: {{ borderColor: '#30363D' }},
        timeScale: {{ borderColor: '#30363D', timeVisible: true, secondsVisible: false }},
        handleScroll: {{ mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false }},
        handleScale: {{ axisPressedMouseMove: true, mouseWheel: true, pinch: true }}
      }});
      const candleSeries = chart.addCandlestickSeries({{
        upColor: '#00D084', downColor: '#FF4B4B', borderVisible: false,
        wickUpColor: '#00D084', wickDownColor: '#FF4B4B',
        priceFormat: {{ type: 'price', precision: {prec}, minMove: {min_move} }}
      }});
      candleSeries.setData({json.dumps(candles)});
      const markers = {json.dumps(markers)};
      if (markers.length > 0) candleSeries.setMarkers(markers);

      if ({ema_flag}) {{
        const s7 = chart.addLineSeries({{ color: '#58A6FF', lineWidth: 1, title: 'EMA7', priceFormat: {{ type: 'price', precision: {prec}, minMove: {min_move} }} }});
        s7.setData({json.dumps(ema7_data)});
        const s25 = chart.addLineSeries({{ color: '#F2CC60', lineWidth: 1.5, title: 'EMA25', priceFormat: {{ type: 'price', precision: {prec}, minMove: {min_move} }} }});
        s25.setData({json.dumps(ema25_data)});
        const s99 = chart.addLineSeries({{ color: '#FF7B72', lineWidth: 1.5, title: 'EMA99', priceFormat: {{ type: 'price', precision: {prec}, minMove: {min_move} }} }});
        s99.setData({json.dumps(ema99_data)});
      }}

      const priceLines = {lines_json};
      priceLines.forEach(pl => {{
        candleSeries.createPriceLine({{
          price: pl.price, color: pl.color, lineWidth: pl.width || 1,
          lineStyle: pl.style || 2, axisLabelVisible: true, title: pl.title
        }});
      }});
      chart.timeScale().fitContent();

      const ro = new ResizeObserver(entries => {{
        for (let entry of entries) {{
          const w = entry.contentRect.width;
          if (w > 10) {{
            chart.resize(w, {height});
            chart.timeScale().fitContent();
          }}
        }}
      }});
      ro.observe(container);
    </script>
    """
    components.html(html_code, height=height + 6)

def render_tv_cvd_chart(df, chart_id="tv_cvd_chart", height=220):
    sub = df.tail(90).copy().reset_index(drop=True)
    cvd_data = [{"time": int(r["ts"]), "value": float(r["cvd"])} for _, r in sub.iterrows()]
    html_code = f"""
    <div id="{chart_id}" style="width: 100%; height: {height}px; background: #0D1117; border-radius: 10px; overflow: hidden;"></div>
    <script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
    <script>
      const container = document.getElementById('{chart_id}');
      const initW = container.clientWidth || window.innerWidth || 560;
      const chart = LightweightCharts.createChart(container, {{
        width: initW,
        height: {height},
        layout: {{ background: {{ color: '#0D1117' }}, textColor: '#C9D1D9' }},
        grid: {{ vertLines: {{ color: '#1F242C' }}, horzLines: {{ color: '#1F242C' }} }},
        rightPriceScale: {{ borderColor: '#30363D' }},
        timeScale: {{ borderColor: '#30363D', timeVisible: true, secondsVisible: false }},
        handleScroll: {{ mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false }},
        handleScale: {{ axisPressedMouseMove: true, mouseWheel: true, pinch: true }}
      }});
      const areaSeries = chart.addAreaSeries({{
        lineColor: '#00D084', topColor: 'rgba(0, 208, 132, 0.35)', bottomColor: 'rgba(0, 208, 132, 0.02)', lineWidth: 2
      }});
      areaSeries.setData({json.dumps(cvd_data)});
      chart.timeScale().fitContent();

      const ro = new ResizeObserver(entries => {{
        for (let entry of entries) {{
          const w = entry.contentRect.width;
          if (w > 10) {{
            chart.resize(w, {height});
            chart.timeScale().fitContent();
          }}
        }}
      }});
      ro.observe(container);
    </script>
    """
    components.html(html_code, height=height + 6)

# ================= 4. 무청산 안전 레버리지 & 병렬 고속 스캔 =================
def calc_safe_leverage(entry, sl, margin, beta=1.0, is_btc=False):
    sl_pct = abs(entry - sl) / entry * 100
    if sl_pct <= 0.1:
        sl_pct = 1.0
    effective_risk = sl_pct * 2.0 * max(1.0, beta)
    max_safe = 100.0 / effective_risk

    if margin <= 100:
        scale = 0.90
    elif margin <= 500:
        scale = 0.65
    else:
        scale = 0.45

    cap = 25 if is_btc else 15
    rec_lev = int(max(1, min(cap, round(max_safe * scale))))
    return rec_lev, sl_pct

def analyze_single_alt(sym, btc_ret, btc_dir):
    try:
        df_1d = calc_indicators(fetch_spot_klines(sym, "1d", 110))
        df_4h = calc_indicators(fetch_spot_klines(sym, "4h", 110))
        a1d, a4h, pa4h = df_1d.iloc[-1], df_4h.iloc[-1], df_4h.iloc[-2]
        price, atr = float(a4h["close"]), float(a4h["atr"])

        _, _, w1_inv, fib100, fib1618, fib_618, fib_382 = analyze_spot_wave_and_fib(df_4h, "4시간봉")

        alt_ret = df_4h["close"].pct_change().tail(60)
        corr = float(btc_ret.corr(alt_ret))
        if np.isnan(corr):
            corr = 0.5
        beta = float(alt_ret.std() / (btc_ret.std() + 1e-9))

        reasons, direction, score = [], None, 0

        if a1d["close"] > a1d["ema25"] and a4h["ema7"] > a4h["ema25"] and 42 <= a4h["rsi"] <= 68:
            score += 3
            reasons.append(f"• <b>현물 추세 정배열:</b> 일봉·4시간봉 EMA 정배열 및 RSI({a4h['rsi']:.1f}) 건강한 상승 흐름입니다.")
            if fib100 > price:
                up_pct = (fib100 - price) / price * 100
                reasons.append(f"• <b>피보나치 확장 예측:</b> 1차 목표 <b>${fib100:,.4f} (+{up_pct:.1f}%)</b> / 1.618 확장 <b>${fib1618:,.4f}</b>")
            if abs(price - fib_618) / price < 0.04 or price > fib_382:
                score += 1
                reasons.append(f"• <b>피보나치 지지 & 파동:</b> 되돌림 지지(${fib_618:,.4f}) 상단 유지 (무효화 선: ${w1_inv:,.4f}).")
            if a4h["hist"] > 0 and a4h["hist"] > pa4h["hist"]:
                score += 1
                reasons.append("• <b>MACD 매수 수급:</b> 히스토그램 상승 모멘텀이 강해지고 있습니다.")
            if corr >= 0.70 and btc_dir == "SHORT":
                score -= 2
            elif corr < 0.35:
                score += 1
                reasons.append(f"• <b>독자 행보(디커플링 {corr*100:.0f}%):</b> 비트코인 영향 없이 자체 수급으로 상승 중입니다.")
            if score >= 4:
                direction = "LONG"

        elif a1d["close"] < a1d["ema25"] and a4h["ema7"] < a4h["ema25"] and 32 <= a4h["rsi"] <= 58:
            score += 3
            reasons.append(f"• <b>현물 하락 역배열:</b> 일봉·4시간봉 EMA 저항 아래에서 RSI({a4h['rsi']:.1f}) 추가 하락 여력이 있습니다.")
            if a4h["hist"] < 0 and a4h["hist"] < pa4h["hist"]:
                score += 1
                reasons.append("• <b>MACD 매도 압력:</b> 반등 실패 후 음봉 모멘텀이 다시 확대되고 있습니다.")
            if corr >= 0.70 and btc_dir == "LONG":
                score -= 2
            elif corr < 0.35:
                score += 1
                reasons.append(f"• <b>독자 약세(디커플링 {corr*100:.0f}%):</b> 시장 반등과 무관하게 개별 매도세가 강합니다.")
            if score >= 4:
                direction = "SHORT"

        if direction:
            if direction == "LONG":
                sl = max(w1_inv * 0.996, price - (1.5 * atr)) if w1_inv < price else price - (1.5 * atr)
                tp = fib100 if fib100 > price * 1.015 else price + (2.5 * atr)
            else:
                sl = price + (1.5 * atr)
                tp = price - (2.5 * atr)

            return {
                "symbol": sym, "raw_symbol": sym, "is_btc": False,
                "direction": direction, "price": price, "sl": sl, "tp": tp,
                "score": score, "reasons": "<br>".join(reasons), "df_4h": df_4h,
                "fib_618": fib_618, "fib_382": fib_382, "fib_100": fib100, "fib_1618": fib1618, "w1_inv": w1_inv,
                "rsi": float(a4h["rsi"]), "corr": corr, "beta": beta
            }
    except Exception:
        return None
    return None

@st.cache_data(ttl=300)
def scan_all_markets(overview):
    btc_4h = calc_indicators(fetch_spot_klines("BTCUSDT", "4h", 140))
    c4h = btc_4h.iloc[-1]
    btc_price = float(c4h["close"])
    btc_atr = float(c4h["atr"])

    _, _, w1_inv_b, fib100_b, fib1618_b, fib_618_b, fib_382_b = analyze_spot_wave_and_fib(btc_4h, "4시간봉")

    long_score, short_score = 0, 0
    btc_reasons = []

    fng = overview["fng_val"]
    fund = overview["funding_num"]
    cvd_up = btc_4h["cvd"].iloc[-1] > btc_4h["cvd"].iloc[-6]

    if fng <= 20:
        long_score += 1.5
        btc_reasons.append(f"• <b>공포·탐욕 지수({fng}):</b> 극단적 공포 구간으로 투매 소진 후 기술적 반등 확률이 높습니다.")
    elif fng >= 75:
        short_score += 1.5
        btc_reasons.append(f"• <b>공포·탐욕 지수({fng}):</b> 극단적 탐욕 과열로 롱 물량 청산 빔 주의 구간입니다.")

    if fund < 0:
        long_score += 1
        btc_reasons.append(f"• <b>펀딩비({overview['funding_rate']}):</b> 음수(-) 펀딩비로 숏 스퀴즈 여력이 포착됩니다.")
    elif fund > 0.03:
        short_score += 1
        btc_reasons.append(f"• <b>펀딩비({overview['funding_rate']}):</b> 양수(+) 과열로 롱 포지션 유지 비용 부담이 큽니다.")

    if cvd_up:
        long_score += 1
        btc_reasons.append("• <b>현물 CVD 수급:</b> 최근 24시간 시장가 매수 델타가 우세합니다.")
    else:
        short_score += 1
        btc_reasons.append("• <b>현물 CVD 수급:</b> 최근 24시간 시장가 매도 출회 압력이 우세합니다.")

    if c4h["close"] > c4h["ema25"]:
        long_score += 1.5
        btc_reasons.append("• <b>현물 4시간봉 추세:</b> EMA 25 상단 지지를 받으며 상승 파동을 이어가고 있습니다.")
    else:
        short_score += 1.5
        btc_reasons.append("• <b>현물 4시간봉 추세:</b> EMA 25 저항 아래에서 조정 파동이 진행 중입니다.")

    if abs(long_score - short_score) < 1.0:
        btc_dir = "SIDEWAYS"
        btc_sl = btc_price - (1.2 * btc_atr)
        btc_tp = fib100_b if fib100_b > btc_price else btc_price + (1.5 * btc_atr)
        btc_reasons.append(f"• <b>대안 시나리오:</b> 1파 고점 꼬리(<b>${w1_inv_b:,.1f}</b>) 이탈 여부에 따라 방향성이 확정됩니다.")
    elif long_score > short_score:
        btc_dir = "LONG"
        btc_sl = max(w1_inv_b * 0.997, btc_price - (1.5 * btc_atr)) if w1_inv_b < btc_price else btc_price - (1.5 * btc_atr)
        btc_tp = fib100_b if fib100_b > btc_price else btc_price + (2.5 * btc_atr)
        btc_reasons.append(f"• <b>피보나치 목표 & 무효화:</b> 1차 확장 <b>${fib100_b:,.1f}</b> (1.618: <b>${fib1618_b:,.1f}</b>) / 무효화 선 <b>${w1_inv_b:,.1f}</b>")
    else:
        btc_dir = "SHORT"
        btc_sl = btc_price + (1.5 * btc_atr)
        btc_tp = btc_price - (2.5 * btc_atr)
        btc_reasons.append(f"• <b>하방 타점 근거:</b> 1파 고점 꼬리(<b>${w1_inv_b:,.1f}</b>) 아래에서 조정 파동이 이어지고 있습니다.")

    btc_pick = {
        "symbol": "BTCUSDT (기준 대장주)", "raw_symbol": "BTCUSDT", "is_btc": True,
        "direction": btc_dir, "price": btc_price, "sl": btc_sl, "tp": btc_tp,
        "reasons": "<br>".join(btc_reasons), "df_4h": btc_4h,
        "fib_618": fib_618_b, "fib_382": fib_382_b, "fib_100": fib100_b, "fib_1618": fib1618_b, "w1_inv": w1_inv_b,
        "rsi": float(c4h["rsi"]), "corr": 1.0, "beta": 1.0
    }

    tickers = requests.get("https://data-api.binance.vision/api/v3/ticker/24hr", timeout=5).json()
    usdt_pairs = [
        t for t in tickers
        if t["symbol"].endswith("USDT")
        and t["symbol"] != "BTCUSDT"
        and not any(x in t["symbol"] for x in ["UPUSDT", "DOWNUSDT", "USDC", "FDUSD", "TUSD", "USDP"])
    ]
    top100 = sorted(usdt_pairs, key=lambda x: float(x["quoteVolume"]), reverse=True)[:100]
    candidates = [t["symbol"] for t in sorted(top100, key=lambda x: abs(float(x["priceChangePercent"])), reverse=True)[:22]]

    btc_ret = btc_4h["close"].pct_change().tail(60)
    with ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(lambda s: analyze_single_alt(s, btc_ret, btc_dir), candidates))

    alt_picks = [r for r in results if r is not None]
    top_alts = sorted(alt_picks, key=lambda x: x["score"], reverse=True)[:5]
    return btc_pick, top_alts

# ================= 5. 실시간 경제 일정(발표치 판독) & 금·환율·속보 =================
def parse_metric_num(val_str):
    if not val_str:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", str(val_str))
    try:
        return float(cleaned)
    except Exception:
        return None

def evaluate_econ_release(raw_title, ko_title, actual_str, forecast_str, default_desc):
    if not actual_str or str(actual_str).strip() == "":
        return (
            '<span class="badge-neutral">⏳ 발표 대기 중</span>',
            f"예상치(<b>{forecast_str}</b>) 기준으로 발표 시점에 실시간 자동 판독됩니다. · {default_desc}"
        )

    act_val = parse_metric_num(actual_str)
    fc_val = parse_metric_num(forecast_str)
    t_low = raw_title.lower()

    inflation_keys = ["cpi", "pce", "ppi", "federal funds", "inflation"]
    unemp_keys = ["unemployment", "claims"]

    if act_val is not None and fc_val is not None:
        if act_val == fc_val:
            return (
                '<span class="badge-neutral">⚪ 예상치 부합 (중립)</span>',
                f"실제 발표(<b>{actual_str}</b>)가 시장 예상치(<b>{forecast_str}</b>)와 정확히 일치했습니다. 대형 충격 없이 기존 추세를 이어갈 가능성이 높습니다."
            )
        if any(k in t_low for k in inflation_keys):
            if act_val < fc_val:
                return (
                    '<span class="badge-long">🟢 코인 호재 (인플레·금리 압력 완화)</span>',
                    f"실제 발표(<b>{actual_str}</b>)가 예상치(<b>{forecast_str}</b>)보다 낮게 나왔습니다. 물가 둔화로 연준 금리 인하 기대감이 커지며 비트코인 매수 우세 요인입니다."
                )
            else:
                return (
                    '<span class="badge-short">🔴 코인 악재 (물가 상회 · 긴축 경계)</span>',
                    f"실제 발표(<b>{actual_str}</b>)가 예상치(<b>{forecast_str}</b>)를 웃돌았습니다. 금리 인하 지연 우려와 달러 강세 자극으로 단기 하방 압력을 주의하세요."
                )
        elif any(k in t_low for k in unemp_keys):
            if act_val > fc_val:
                return (
                    '<span class="badge-long">🟢 단기 호재 (고용 둔화 → 금리 인하 기대)</span>',
                    f"실제 발표(<b>{actual_str}</b>)가 예상치(<b>{forecast_str}</b>)보다 높게 나와 고용 열기가 식고 있음을 시사합니다. 연준 완화 기대감으로 단기 긍정적입니다."
                )
            else:
                return (
                    '<span class="badge-short">🔴 단기 악재 (고용 과열 → 긴축 유지 우려)</span>',
                    f"실제 발표(<b>{actual_str}</b>)가 예상(<b>{forecast_str}</b>)보다 견조해 연준이 금리 인하를 서두르지 않을 명분이 커졌습니다."
                )
        else:
            if act_val > fc_val:
                return (
                    '<span class="badge-neutral">🟡 예상치 상회 발표 완료</span>',
                    f"실제 <b>{actual_str}</b> 발표 (예상 <b>{forecast_str}</b> 상회). 경기 침체 우려는 덜었으나 국채 금리·달러 반등 여부를 함께 체크하세요."
                )
            else:
                return (
                    '<span class="badge-neutral">🟡 예상치 하회 발표 완료</span>',
                    f"실제 <b>{actual_str}</b> 발표 (예상 <b>{forecast_str}</b> 하회). 경기 둔화 신호로 금리 하향 안정에는 우호적이나 급격한 침체 경계감이 공존합니다."
                )

    return (
        '<span class="badge-long">✅ 발표 완료</span>',
        f"실제 발표치 <b>{actual_str}</b> 확인 (예상: {forecast_str}). · {default_desc}"
    )

@st.cache_data(ttl=25)
def get_korean_econ_calendar():
    trans_map = {
        "CPI": ("소비자물가지수 (CPI)", "예상치 하회 시 금리 인하 기대감으로 코인 강한 호재"),
        "Core CPI": ("근원 소비자물가지수 (Core CPI)", "에너지·식품 제외 핵심 물가. 낮게 나올수록 위험자산에 유리"),
        "Non-Farm Employment Change": ("비농업 고용지수 (NFP)", "적당한 고용 둔화는 금리 인하 기대감으로 호재, 과열은 악재"),
        "Unemployment Rate": ("미국 실업률", "실업률 상승 시 연준 완화 기대감 자극"),
        "Federal Funds Rate": ("연준(FOMC) 기준금리 결정", "금리 인하 및 완화적 스탠스 확인 시 유동성 공급 호재"),
        "FOMC Statement": ("FOMC 성명서 발표", "향후 금리 경로 힌트에 따라 변동성 최고조 구간"),
        "PPI": ("생산자물가지수 (PPI)", "도매 물가 지표. 예상 하회 시 인플레이션 완화 신호"),
        "Core PCE Price Index": ("근원 개인소비지출 물가 (PCE)", "연준 최우선 물가 지표. 둔화 확인 시 반등 요인"),
        "Retail Sales": ("미국 소매판매 지수", "미국 소비 경기 척도. 완만한 둔화가 금리에 우호적"),
        "GDP": ("미국 국내총생산 (GDP) 성장률", "미국 경제 성장 속도 지표"),
        "Unemployment Claims": ("주간 신규 실업수당 청구건수", "매주 목요일 발표. 청구건수 증가 시 금리 인하 기대(소폭 호재)")
    }
    events = []
    try:
        res = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=4).json()
        for ev in res:
            if ev.get("country") == "USD" and ev.get("impact") in ["High", "Medium"]:
                raw_title = ev.get("title", "")
                ko_title, impact_desc = raw_title, "발표 수치와 예상치 괴리에 따라 단기 변동성 확대 주의"
                for k, (kt, desc) in trans_map.items():
                    if k.lower() in raw_title.lower():
                        ko_title, impact_desc = kt, desc
                        break
                dt_str = ev.get("date", "")
                try:
                    dt_kst = datetime.fromisoformat(dt_str).astimezone(KST).strftime("%m/%d (%a) %H:%M")
                except Exception:
                    dt_kst = dt_str[:16]

                actual_val = ev.get("actual") or ""
                forecast_val = ev.get("forecast") or "-"
                prev_val = ev.get("previous") or "-"
                rel_badge, rel_desc = evaluate_econ_release(raw_title, ko_title, actual_val, forecast_val, impact_desc)

                events.append({
                    "time": dt_kst,
                    "importance": "🔴 중요" if ev.get("impact") == "High" else "🟡 보통",
                    "title": ko_title,
                    "actual": actual_val if actual_val else "발표 전",
                    "forecast": forecast_val,
                    "previous": prev_val,
                    "rel_badge": rel_badge,
                    "rel_desc": rel_desc
                })
    except Exception:
        pass
    return events

def analyze_news_sentiment(title, cat):
    bull_kw = ["인하", "둔화", "완화", "승인", "유입", "순매수", "급등", "돌파", "반등", "채택", "호재", "강세", "매집", "사상 최고"]
    bear_kw = ["인상", "긴축", "매파", "급락", "폭락", "유출", "순매도", "해킹", "규제", "소송", "제재", "악재", "약세", "파산", "청산", "전쟁", "공습"]
    if "금" in cat:
        if any(w in title for w in ["급등", "사상 최고", "매집", "인하", "완화"]):
            return "🟢 유동성·금 강세 신호", "badge-long", "금리 인하 및 통화가치 하락 헤지 수요로 금과 비트코인 동반 유동성 유입이 기대됩니다."
        if any(w in title for w in ["전쟁", "공습", "위기", "긴축", "급락"]):
            return "🔴 지정학·긴축 경계", "badge-short", "위기 회피로 자금이 금·달러로만 쏠릴 경우 코인 단기 수급은 위축될 수 있습니다."
    if any(w in title for w in bull_kw):
        return "🟢 호재 (상승 요인)", "badge-long", "유동성 완화 또는 매수 수급 유입을 자극하는 긍정적 재료입니다."
    if any(w in title for w in bear_kw):
        return "🔴 악재 (하락 요인)", "badge-short", "위험자산 회피 심리 또는 매도 압력을 키울 수 있는 경계 재료입니다."
    return "⚪ 중립 (시장 관망)", "badge-neutral", "방향성 확정 전 추가 데이터와 시장 반응을 확인할 필요가 있습니다."

@st.cache_data(ttl=150)
def fetch_coinness_style_news():
    feeds = [
        ("🇺🇸 미국 거시·증시", "https://news.google.com/rss/search?q=미국+증시+연준+금리+when:2d&hl=ko&gl=KR&ceid=KR:ko"),
        ("🥇 국제 금·환율 속보", "https://news.google.com/rss/search?q=국제+금값+금시세+환율+when:2d&hl=ko&gl=KR&ceid=KR:ko"),
        ("🪙 국내 비트코인 속보", "https://news.google.com/rss/search?q=비트코인+가상자산+시세+when:2d&hl=ko&gl=KR&ceid=KR:ko")
    ]
    headers = {"User-Agent": "Mozilla/5.0"}

    def load_feed(cat_url):
        cat, url = cat_url
        out = []
        try:
            xml_text = requests.get(url, headers=headers, timeout=4).text
            root = ET.fromstring(xml_text)
            for item in root.findall("./channel/item")[:5]:
                title = item.findtext("title", "").split(" - ")[0]
                link = item.findtext("link", "")
                pub = item.findtext("pubDate", "")
                try:
                    dt_obj = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc).astimezone(KST)
                    time_txt = dt_obj.strftime("%m/%d %H:%M")
                except Exception:
                    time_txt = "최신"
                badge_txt, badge_cls, analysis = analyze_news_sentiment(title, cat)
                out.append({
                    "cat": cat, "time": time_txt, "title": title, "link": link,
                    "badge_txt": badge_txt, "badge_cls": badge_cls, "analysis": analysis
                })
        except Exception:
            pass
        return out

    with ThreadPoolExecutor(max_workers=3) as ex:
        res_lists = list(ex.map(load_feed, feeds))
    return [item for sub in res_lists for item in sub]

# ================= 6. 보유 종목 1초 실시간 웹소켓 & 캘린더 렌더러 =================
def render_live_positions_ws(pos_list):
    cards_html = ""
    for idx, p in enumerate(pos_list):
        sym = str(p["종목"])
        is_long = "롱" in str(p["포지션"])
        border_col = "#00D084" if is_long else "#FF4B4B"
        badge_bg = "rgba(0, 208, 132, 0.15)" if is_long else "rgba(255, 75, 75, 0.15)"
        badge_col = "#00D084" if is_long else "#FF4B4B"

        entry_p = float(p["진입가"])
        init_mark = float(p["종료가"])
        margin = float(p["증거금"])
        lev = int(float(p["레버리지"]))
        memo_parts = str(p.get("메모", "0|0")).split("|")
        qty = float(memo_parts[0]) if len(memo_parts) > 0 and memo_parts[0] else (margin * lev / entry_p if entry_p > 0 else 0)
        liq_p = float(memo_parts[1]) if len(memo_parts) > 1 and memo_parts[1] else 0.0

        init_pnl = (init_mark - entry_p) * qty if is_long else (entry_p - init_mark) * qty
        init_roi = (init_pnl / margin) * 100 if margin > 0 else 0.0
        pnl_col = "#00D084" if init_pnl >= 0 else "#FF4B4B"
        prec = 4 if entry_p < 10 else 2

        cards_html += f"""
        <div style="background:#161B22; border:1px solid #30363D; border-left:4px solid {border_col}; border-radius:10px; padding:14px; margin-bottom:10px; font-family:sans-serif;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span style="font-size:16px; font-weight:bold; color:#FFFFFF;">{sym} ({lev}배)</span>
            <span style="background:{badge_bg}; color:{badge_col}; padding:3px 8px; border-radius:6px; font-weight:bold; font-size:12px;">{p['포지션']} · ● LIVE</span>
          </div>
          <div style="margin-top:8px; font-size:13px; color:#C9D1D9;">
            진입가: <b>${entry_p:,.{prec}f}</b> &nbsp;|&nbsp;
            현재가: <b id="mark-{idx}" style="color:#FFFFFF;">${init_mark:,.{prec}f}</b> &nbsp;|&nbsp;
            증거금: <b>${margin:,.2f}</b>
          </div>
          <div id="pnl-{idx}" style="margin-top:6px; font-size:15px; font-weight:bold; color:{pnl_col};">
            실시간 손익: ${init_pnl:+,.2f} ({init_roi:+.2f}%)
          </div>
          <div style="font-size:12px; color:#8B949E; margin-top:4px;">
            수량: {qty:g} · 예상 청산가: ${liq_p:,.{prec}f}
          </div>
        </div>
        """

    js_items = []
    for idx, p in enumerate(pos_list):
        entry_p = float(p["진입가"])
        margin = float(p["증거금"])
        lev = int(float(p["레버리지"]))
        memo_parts = str(p.get("메모", "0|0")).split("|")
        qty = float(memo_parts[0]) if len(memo_parts) > 0 and memo_parts[0] else (margin * lev / entry_p if entry_p > 0 else 0)
        js_items.append({
            "idx": idx,
            "stream": f"{str(p['종목']).lower()}@markPrice@1s",
            "isLong": "롱" in str(p["포지션"]),
            "entry": entry_p,
            "qty": qty,
            "margin": margin,
            "prec": 4 if entry_p < 10 else 2
        })

    html_all = f"""
    {cards_html}
    <script>
      const items = {json.dumps(js_items)};
      const streams = items.map(x => x.stream).join('/');
      function startPosWS() {{
        const ws = new WebSocket('wss://fstream.binance.com/stream?streams=' + streams);
        ws.onmessage = (ev) => {{
          const msg = JSON.parse(ev.data);
          if (!msg.data || !msg.data.p) return;
          const mark = parseFloat(msg.data.p);
          items.forEach(it => {{
            if (msg.stream === it.stream) {{
              const pnl = it.isLong ? (mark - it.entry) * it.qty : (it.entry - mark) * it.qty;
              const roi = it.margin > 0 ? (pnl / it.margin) * 100 : 0;
              const markEl = document.getElementById('mark-' + it.idx);
              const pnlEl = document.getElementById('pnl-' + it.idx);
              if (markEl) markEl.textContent = '$' + mark.toLocaleString('en-US', {{minimumFractionDigits: it.prec, maximumFractionDigits: it.prec}});
              if (pnlEl) {{
                pnlEl.textContent = '실시간 손익: ' + (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2) + ' (' + (roi >= 0 ? '+' : '') + roi.toFixed(2) + '%)';
                pnlEl.style.color = pnl >= 0 ? '#00D084' : '#FF4B4B';
              }}
            }}
          }});
        }};
        ws.onclose = () => setTimeout(startPosWS, 3000);
      }}
      if (items.length > 0) startPosWS();
    </script>
    """
    components.html(html_all, height=len(pos_list) * 124 + 8)

def render_pnl_calendar(df_closed, year, month):
    cal = calendar.Calendar(firstweekday=6)
    month_days = cal.monthdayscalendar(year, month)

    daily_map = {}
    if not df_closed.empty and "일시" in df_closed.columns:
        temp = df_closed.copy()
        temp["date_only"] = temp["일시"].astype(str).str.slice(0, 10)
        prefix = f"{year:04d}-{month:02d}-"
        m_df = temp[temp["date_only"].str.startswith(prefix)]
        for d_str, grp in m_df.groupby("date_only"):
            day_num = int(d_str.split("-")[2])
            daily_map[day_num] = (float(grp["수익금"].sum()), len(grp))

    weekdays = ["일", "월", "화", "수", "목", "금", "토"]
    th_html = "".join([f"<th style='padding:6px; font-size:12px; color:#8B949E; text-align:center;'>{w}</th>" for w in weekdays])

    rows_html = ""
    for week in month_days:
        tds = ""
        for d in week:
            if d == 0:
                tds += "<td style='background:#0D1117; border:1px solid #21262D; height:58px;'></td>"
            else:
                if d in daily_map:
                    pnl_val, cnt = daily_map[d]
                    bg = "rgba(0, 208, 132, 0.14)" if pnl_val >= 0 else "rgba(255, 75, 75, 0.14)"
                    col = "#00D084" if pnl_val >= 0 else "#FF4B4B"
                    pnl_txt = f"{pnl_val:+.1f}$"
                    sub_txt = f"<div style='font-size:11px; font-weight:bold; color:{col}; margin-top:2px;'>{pnl_txt}</div><div style='font-size:10px; color:#8B949E;'>{cnt}건</div>"
                else:
                    bg = "#161B22"
                    sub_txt = "<div style='font-size:10px; color:#30363D; margin-top:6px;'>-</div>"
                tds += f"<td style='background:{bg}; border:1px solid #30363D; vertical-align:top; padding:4px; width:14.2%; height:58px; text-align:center;'><div style='font-size:11px; color:#C9D1D9; text-align:left;'>{d}</div>{sub_txt}</td>"
        rows_html += f"<tr>{tds}</tr>"

    cal_html = f"""
    <table style="width:100%; border-collapse:collapse; table-layout:fixed; border-radius:8px; overflow:hidden; margin-bottom:10px;">
      <thead><tr style="background:#161B22;">{th_html}</tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    """
    st.markdown(cal_html, unsafe_allow_html=True)

# ================= 7. 실시간 자동 갱신 섹션(@st.fragment) =================
@st.fragment(run_every="120s")
def live_top_header_section():
    ov = get_market_overview()
    render_realtime_top_board(ov)

@st.fragment(run_every="60s")
def live_cvd_and_firechart_section():
    st.markdown("#### 📈 BTC 현물 누적 거래량 델타 (CVD · 1분 자동 갱신)")
    try:
        btc_4h_df = calc_indicators(fetch_spot_klines("BTCUSDT", "4h", 120))
        render_tv_cvd_chart(btc_4h_df, "tv_btc_cvd", height=220)

        price_up = btc_4h_df["close"].iloc[-1] > btc_4h_df["close"].iloc[-6]
        cvd_up = btc_4h_df["cvd"].iloc[-1] > btc_4h_df["cvd"].iloc[-6]

        if price_up and cvd_up:
            cvd_badge = '<span class="badge-long">🟢 호재 (실매수 유입 동반 상승)</span>'
            cvd_desc = "현물 가격이 오르는 동안 실제 시장가 매수 체결(CVD)도 같이 늘어나고 있습니다. 현물 매수세가 뒷받침되는 건강한 상승입니다."
        elif (not price_up) and cvd_up:
            cvd_badge = '<span class="badge-long">🟢 반등 신호 (저점 매도 물량 흡수)</span>'
            cvd_desc = "가격은 눌렸지만 CVD는 오히려 버티거나 올라가고 있습니다. 현물 시장에서 매도 물량을 받아내고 있어 단기 반등 확률이 높습니다."
        elif price_up and (not cvd_up):
            cvd_badge = '<span class="badge-short">🔴 악재 경계 (수급 없는 가짜 반등 주의)</span>'
            cvd_desc = "가격만 살짝 올랐을 뿐 실제 시장가 매수세는 빠져나가고 있습니다. 저항선 부근에서 다시 밀릴 위험이 크니 롱 추격을 자제하세요."
        else:
            cvd_badge = '<span class="badge-short">🔴 악재 (매도 출회 우세 · 하방 압력)</span>'
            cvd_desc = "가격 하락과 함께 시장가 매도 물량이 계속 쏟아지고 있습니다. CVD 바닥 다지기 확인 전까지는 롱 진입을 보류하세요."

        st.markdown(f'<div class="reason-box">{cvd_badge}<div style="margin-top:5px;">{cvd_desc}</div></div>', unsafe_allow_html=True)
    except Exception:
        st.warning("CVD 수급 차트를 불러오는 중입니다.")

    st.markdown("#### 🔥 현물 파이어차트 (실시간 호가창 유동성 매물벽)")
    try:
        heatmap_df, top_bid_p, top_bid_v, top_ask_p, top_ask_v = get_spot_orderbook_heatmap("BTCUSDT")
        max_notional = heatmap_df["notional"].max() + 1e-9
        rows_html = ""
        for _, r in heatmap_df.iterrows():
            pct = min(100, int((r["notional"] / max_notional) * 100))
            is_ask = r["side"] == "ASK"
            bar_col = "#FF4B4B" if is_ask else "#00D084"
            side_lbl = "매도벽" if is_ask else "매수벽"
            rows_html += f'<div style="display:flex;align-items:center;margin-bottom:5px;font-size:0.78rem;"><div style="width:76px;color:#C9D1D9;font-weight:bold;">${r["bin"]:,.0f}</div><div style="flex:1;background:#0D1117;border-radius:4px;height:14px;overflow:hidden;margin:0 8px;"><div style="width:{pct}%;background:{bar_col};height:100%;"></div></div><div style="width:88px;text-align:right;color:{bar_col};">{side_lbl} ${r["notional"]/1e6:.1f}M</div></div>'

        st.markdown(f'<div class="metric-card" style="padding:12px;">{rows_html}</div>', unsafe_allow_html=True)

        ratio = top_bid_v / (top_ask_v + 1e-9)
        if ratio >= 1.25:
            fire_badge = '<span class="badge-long">🟢 하방 지지 우세 (매수 방어벽 두터움)</span>'
            fire_desc = f"하단 <b>${top_bid_p:,.0f}</b> 부근의 현물 매수 대기 물량이 상단 매도벽(<b>${top_ask_p:,.0f}</b>)보다 약 <b>{ratio:.1f}배</b> 두껍게 깔려 있습니다."
        elif ratio <= 0.8:
            fire_badge = '<span class="badge-short">🔴 상방 저항 우세 (매도 저항벽 두터움)</span>'
            fire_desc = f"상단 <b>${top_ask_p:,.0f}</b> 부근에 매도 물량이 하단 지지벽(<b>${top_bid_p:,.0f}</b>)보다 두껍게 쌓여 있습니다. 도달 시 저항 압력이 큽니다."
        else:
            fire_badge = '<span class="badge-neutral">⚪ 매수·매도벽 균형 (박스권 대치)</span>'
            fire_desc = f"상단 저항벽(<b>${top_ask_p:,.0f}</b>)과 하단 지지벽(<b>${top_bid_p:,.0f}</b>) 규모가 비슷해 두 매물벽 사이에서 횡보할 가능성이 높습니다."

        st.markdown(f'<div class="reason-box">{fire_badge}<div style="margin-top:5px;">{fire_desc}</div></div>', unsafe_allow_html=True)
    except Exception:
        st.warning("호가창 유동성 히트맵을 불러오는 중입니다.")

@st.fragment(run_every="300s")
def live_recommendations_section():
    ov = get_market_overview()
    user_margin = st.number_input("💰 내 이번 진입 증거금 ($)", min_value=10.0, value=100.0, step=10.0)
    st.caption(f"⚡ 현물 차트 기준 고속 병렬 스캔 · 최근 갱신: {datetime.now(KST).strftime('%H:%M:%S')} (5분마다 자동 반영)")

    btc_pick, alt_picks = scan_all_markets(ov)
    all_picks = [btc_pick] + alt_picks

    for idx, p in enumerate(all_picks):
        is_long = p["direction"] == "LONG"
        is_short = p["direction"] == "SHORT"
        card_cls = "coin-card" if is_long else ("coin-card coin-card-short" if is_short else "coin-card coin-card-neutral")
        badge_cls = "badge-long" if is_long else ("badge-short" if is_short else "badge-neutral")
        label_txt = "롱 (매수) 추천" if is_long else ("숏 (매도) 추천" if is_short else "횡보 관망")

        rec_lev, sl_pct = calc_safe_leverage(p["price"], p["sl"], user_margin, p["beta"], p["is_btc"])
        liq_price = p["price"] * (1 - (0.9 / rec_lev)) if is_long else p["price"] * (1 + (0.9 / rec_lev))

        corr_txt = "기준 대장주" if p["is_btc"] else (
            f"독자 행보 (디커플링 {p['corr']*100:.0f}%)" if p["corr"] < 0.35 else f"BTC 동조화 {p['corr']*100:.0f}% (변동성 {p['beta']:.1f}배)"
        )

        st.markdown(f"""
        <div class="{card_cls}">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:1.08rem; font-weight:bold; color:#FFFFFF;">{p['symbol']}</span>
                <span class="{badge_cls}">{label_txt}</span>
            </div>
            <div style="font-size:0.78rem; color:#8B949E; margin-top:3px;">🔗 {corr_txt} · 현물 RSI(4H): {p['rsi']:.1f}</div>
            <div style="margin-top:8px; font-size:0.85rem; color:#8B949E;">
                진입가: <b style="color:#F0F6FC;">${p['price']:,.4f}</b> &nbsp;|&nbsp;
                손절가: <b style="color:#FF7B72;">${p['sl']:,.4f}</b> &nbsp;|&nbsp;
                목표가: <b style="color:#7EE787;">${p['tp']:,.4f}</b>
            </div>
            <div style="font-size:0.74rem; color:#8B949E; margin-top:2px;">※ 현물(Spot) 차트 기준 타점 · 선물 진입 시 호가 괴리만 확인</div>
            <div class="lev-box">
                🛡️ <b>증거금 ${user_margin:,.0f} 기준 무청산 추천 배율: {rec_lev}배</b>
                (예상 청산가: <b>${liq_price:,.4f}</b> · 손절폭 -{sl_pct:.1f}% 방어)
            </div>
            <div class="reason-box">
                <div style="font-weight:bold; color:#58A6FF; margin-bottom:4px;">💡 현물 파동 & 피보나치 추천 근거</div>
                {p['reasons']}
            </div>
        </div>""", unsafe_allow_html=True)

        with st.expander(f"🕯️ {p['raw_symbol']} 현물 캔들 차트 작도 보기 (두 손가락 확대·축소)"):
            chart_lines = [
                {"price": p["price"], "color": "#FFFFFF", "width": 1, "style": 0, "title": "진입가"},
                {"price": p["sl"], "color": "#FF4B4B", "width": 2, "style": 2, "title": "손절가"},
                {"price": p["tp"], "color": "#00D084", "width": 2, "style": 2, "title": "🎯 목표가"},
                {"price": p["w1_inv"], "color": "#FF7B72", "width": 1, "style": 2, "title": "⚠️ 1파고점(무효화)"},
                {"price": p["fib_1618"], "color": "#58A6FF", "width": 1, "style": 1, "title": "🎯 Fib 1.618"}
            ]
            render_tv_candle_chart(p["df_4h"].tail(90), f"tv_pick_{idx}", price_lines=chart_lines, show_ema=True, show_waves=True, height=340)

@st.fragment(run_every="60s")
def live_econ_calendar_section():
    st.markdown(f"#### 📅 이번 주 미국 주요 경제지표 실시간 발표 (1분 자동 감시 · {datetime.now(KST).strftime('%H:%M:%S')})")
    st.caption("발표 시간이 되면 실제치(Actual)와 예상치 비교 후 호재·악재 설명이 실시간으로 반영됩니다.")
    events = get_korean_econ_calendar()
    if not events:
        st.info("이번 주 예정된 주요 미국 경제지표 일정을 불러오는 중입니다.")
    else:
        for ev in events:
            act_col = "#00D084" if ev["actual"] != "발표 전" else "#8B949E"
            st.markdown(f"""
            <div class="news-card">
                <div style="display:flex; justify-content:space-between; font-size:0.78rem; color:#8B949E;">
                    <span>{ev['importance']} &nbsp;|&nbsp; {ev['time']} (KST)</span>
                    <span>실제: <b style="color:{act_col};">{ev['actual']}</b> / 예상: <b style="color:#F0F6FC;">{ev['forecast']}</b> / 이전: {ev['previous']}</span>
                </div>
                <div style="font-size:0.98rem; font-weight:bold; color:#F0F6FC; margin:5px 0;">{ev['title']}</div>
                <div class="reason-box" style="margin-top:6px; padding:8px 10px; font-size:0.82rem;">
                    {ev['rel_badge']}<br>
                    <div style="margin-top:4px;">{ev['rel_desc']}</div>
                </div>
            </div>""", unsafe_allow_html=True)

@st.fragment(run_every="150s")
def live_news_section():
    st.markdown("#### 🌎 글로벌 증시 · 금 · 환율 실시간 시세")
    macro = get_macro_indices()
    items = list(macro.items())
    for row_items in [items[:2], items[2:]]:
        cols = st.columns(2)
        for col, (name, info) in zip(cols, row_items):
            c_col = "#00D084" if info["chg"] >= 0 else "#FF4B4B"
            col.markdown(f"""
            <div class="metric-card">
                <div style="font-size:0.78rem; color:#8B949E;">{name}</div>
                <div style="font-size:1.05rem; font-weight:bold; color:#F0F6FC;">{info['price']}</div>
                <div style="font-size:0.82rem; color:{c_col};">{info['chg']:+.2f}%</div>
            </div>""", unsafe_allow_html=True)

    st.markdown(f"#### ⚡ 실시간 경제 · 금 · 코인 속보 (자동 업데이트 · {datetime.now(KST).strftime('%H:%M:%S')})")
    news_list = fetch_coinness_style_news()
    if not news_list:
        st.info("최신 속보를 불러오는 중입니다.")
    else:
        for n in news_list:
            st.markdown(f"""
            <div class="news-card">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:5px;">
                    <span style="font-size:0.76rem; color:#8B949E;">{n['cat']} · {n['time']}</span>
                    <span class="{n['badge_cls']}">{n['badge_txt']}</span>
                </div>
                <div style="font-size:0.95rem; font-weight:bold; color:#F0F6FC; line-height:1.4;">
                    <a href="{n['link']}" target="_blank" style="color:#F0F6FC; text-decoration:none;">{n['title']} ↗</a>
                </div>
                <div class="reason-box" style="margin-top:6px; padding:7px 9px; font-size:0.81rem;">
                    💡 <b>시장 영향:</b> {n['analysis']}
                </div>
            </div>""", unsafe_allow_html=True)

@st.fragment(run_every="60s")
def live_trade_journal_section():
    sheet_url = st.secrets.get("SHEET_URL", "")
    if not sheet_url:
        st.warning("Streamlit Secrets에 SHEET_URL이 설정되지 않았습니다.")
        return

    wallet_bal, avail_bal, used_margin = 0.0, 0.0, 0.0
    cur_open_list = []
    df_closed = pd.DataFrame()

    try:
        rows = requests.get(sheet_url, timeout=8).json()
        if len(rows) > 1:
            df_all = pd.DataFrame(rows[1:], columns=rows[0])
            tag_col = df_all["근거태그"].astype(str)
            memo_col = df_all["메모"].astype(str)

            # 1) 총 증거금(지갑 잔고) 스냅샷 추출
            bal_mask = tag_col.str.startswith("BAL_SNAPSHOT|")
            df_bal = df_all[bal_mask]
            if not df_bal.empty:
                last_b = df_bal.iloc[-1]
                wallet_bal = float(pd.to_numeric(last_b["증거금"], errors="coerce") or 0)
                avail_bal = float(pd.to_numeric(last_b["진입가"], errors="coerce") or 0)
                used_margin = float(pd.to_numeric(last_b["종료가"], errors="coerce") or 0)

            # 2) 현재 보유 포지션 스냅샷 추출
            open_mask = tag_col.str.startswith("OPEN_SNAPSHOT|") | memo_col.str.startswith("OPEN_SNAPSHOT|")
            df_open = df_all[tag_col.str.startswith("OPEN_SNAPSHOT|")].copy()
            if not df_open.empty:
                latest_batch = df_open["근거태그"].iloc[-1]
                cur_open = df_open[(df_open["근거태그"] == latest_batch) & (df_open["종목"] != "NONE")]
                cur_open_list = cur_open.to_dict("records")

            # 3) 실제 종료된 매매 기록만 분리
            exclude_mask = bal_mask | open_mask | (df_all["종목"].isin(["WALLET", "NONE"]))
            df_closed = df_all[~exclude_mask].copy()
            if not df_closed.empty:
                df_closed["수익금"] = pd.to_numeric(df_closed["수익금"], errors="coerce").fillna(0)
                df_closed["수익률"] = pd.to_numeric(df_closed["수익률"], errors="coerce").fillna(0)
    except Exception as e:
        st.warning(f"구글 시트 데이터 동기화 중입니다: {e}")

    # --- [영역 A] 선물 계좌 총 증거금(시드) ---
    st.markdown("#### 💰 내 바이낸스 선물 증거금 총액")
    c1, c2, c3 = st.columns(3)
    c1.metric("총 지갑 잔고(시드)", f"${wallet_bal:,.2f}")
    c2.metric("포지션 투입 증거금", f"${used_margin:,.2f}")
    c3.metric("주문 가능 잔고", f"${avail_bal:,.2f}")

    # --- [영역 B] 현재 보유 중인 실시간 포지션 (1초 웹소켓) ---
    st.markdown("#### 🟢 현재 보유 중인 실시간 포지션 (1초 실시간)")
    if cur_open_list:
        render_live_positions_ws(cur_open_list)
    else:
        st.caption("현재 보유 중인 선물 포지션이 없습니다. 바이낸스에서 새로 진입하면 15초 내 자동 등록됩니다.")

    st.markdown("---")

    # --- [영역 C] 월별 손익 캘린더 & 종료된 매매 기록 ---
    st.markdown("#### 📅 월별 손익 캘린더 & 종료된 매매 기록")
    now_kst = datetime.now(KST)
    cal_c1, cal_c2 = st.columns(2)
    sel_year = cal_c1.selectbox("연도", [now_kst.year - 1, now_kst.year, now_kst.year + 1], index=1)
    sel_month = cal_c2.selectbox("월", list(range(1, 13)), index=now_kst.month - 1)

    render_pnl_calendar(df_closed, sel_year, sel_month)

    if df_closed.empty:
        st.caption("아직 종료된 매매 기록이 없습니다. 보유 포지션을 익절·손절로 종료하면 캘린더와 아래 표에 자동 기록됩니다.")
    else:
        total_pnl = df_closed["수익금"].sum()
        wins = (df_closed["수익금"] > 0).sum()
        total_trades = len(df_closed)
        win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0

        m1, m2, m3 = st.columns(3)
        m1.metric("종료 매매", f"{total_trades}건")
        m2.metric("전체 승률", f"{win_rate:.1f}%", f"{wins}승 {total_trades-wins}패")
        m3.metric("누적 실현손익", f"${total_pnl:+,.2f}")

        date_options = ["전체 내역 보기"] + sorted(df_closed["일시"].astype(str).str.slice(0, 10).unique().tolist(), reverse=True)
        sel_day = st.selectbox("🔍 날짜별 상세 필터", date_options)
        view_df = df_closed if sel_day == "전체 내역 보기" else df_closed[df_closed["일시"].astype(str).str.startswith(sel_day)]

        display_cols = ["일시", "종목", "포지션", "증거금", "레버리지", "진입가", "종료가", "수익금", "수익률", "메모"]
        valid_cols = [c for c in display_cols if c in view_df.columns]
        st.dataframe(view_df[valid_cols].iloc[::-1], use_container_width=True, hide_index=True)

    st.markdown("---")

    # --- [영역 D] 복리 시뮬레이터 & 계좌 보호 대책 ---
    st.markdown("#### 📈 복리 시뮬레이터 & 계좌 방어 대책")
    default_seed = max(10.0, round(wallet_bal, 2)) if wallet_bal > 0 else 100.0
    s1, s2, s3 = st.columns(3)
    seed_input = s1.number_input("시작 시드 ($)", min_value=10.0, value=default_seed, step=10.0)
    daily_pct = s2.number_input("목표 일 수익률 (%)", min_value=0.5, max_value=30.0, value=3.0, step=0.5)
    sim_days = s3.number_input("운용 일수 (일)", min_value=5, max_value=180, value=30, step=5)

    final_seed = seed_input * ((1 + daily_pct / 100) ** sim_days)
    net_gain = final_seed - seed_input
    mult = final_seed / seed_input

    r1, r2 = st.columns(2)
    r1.metric(f"{sim_days}일 후 복리 예상 잔고", f"${final_seed:,.2f}", f"+${net_gain:,.2f} ({mult:.1f}배)")
    r2.metric("1회 권장 최대 투입금 (시드 20%)", f"${seed_input * 0.20:,.2f}", f"일일 손절 한도 -${seed_input * 0.05:,.2f}")

    st.markdown(f"""
    <div class="reason-box">
        <div style="font-weight:bold; color:#FFA657; margin-bottom:6px;">🛡️ 복리 계좌 파산 방지 3대 실전 대책 (현재 시드 ${seed_input:,.2f} 기준)</div>
        • <b>1. 1회 진입 비중 상한 (최대 20% = ${seed_input * 0.20:,.2f}):</b> 복리는 시드가 커질수록 한 번의 청산 타격이 큽니다. 전체 시드의 20% 이하로만 진입하고 물타기 여유분 80%를 현금으로 남겨두세요.<br>
        • <b>2. 일일 손실 서킷 브레이커 (-5% = -${seed_input * 0.05:,.2f}):</b> 하루 누적 손실이 시드의 5%에 도달하면 복구 매매(뇌동매매)를 멈추고 그날 차트를 끄는 규칙을 지켜야 복리 곡선이 유지됩니다.<br>
        • <b>3. 원금 회수 스키밍 (목표: ${seed_input * 1.5:,.2f} 도달 시):</b> 잔고가 현재 시드 대비 +50%(<b>${seed_input * 1.5:,.2f}</b>)에 도달할 때마다 수익의 절반(<b>${seed_input * 0.25:,.2f}</b>)을 현물 지갑으로 출금해 '무손실 안전 계좌'로 전환하세요.
    </div>
    """, unsafe_allow_html=True)

# ================= 8. 메인 화면 렌더링 =================
st.markdown("### 📡 코인 선물 레이더")
st.caption("BTC 시세와 보유 포지션은 1초마다 실시간 반영되며, 화면 깜빡임 없이 자동 갱신됩니다.")

live_top_header_section()

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 시장 브리핑", "🎯 추천 종목", "📅 경제 일정", "📰 경제·속보", "📝 매매일지"])

with tab1:
    halving_date = datetime(2024, 4, 20, tzinfo=KST)
    days_passed = (datetime.now(KST) - halving_date).days
    progress = min(days_passed / 1460, 1.0)
    st.markdown(f"""
    <div class="metric-card">
        <div style="font-weight:bold; color:#F0F6FC; margin-bottom:4px;">⏳ 비트코인 반감기 & 거시 싸이클</div>
        <div style="font-size:0.86rem; color:#FFA657;">4차 반감기 후 <b>{days_passed}일 경과</b></div>
        <div class="reason-box">
            <span class="badge-neutral">⚪ 거시 싸이클 해석</span><br>
            반감기 이후 12~18개월 사이 대형 고점을 형성한 뒤 약 1년간 거시 조정 파동이 진행됩니다. 청산 빔 왜곡이 없는 <b>현물(Spot) 차트 기준 파동·피보나치 목표가</b>를 먼저 확인하세요.
        </div>
    </div>""", unsafe_allow_html=True)
    st.progress(progress)

    st.markdown("#### 🕯️ 비트코인 현물(Spot) 엘리어트 파동 & 피보나치 예측")
    tf_configs = [
        ("1M", 120, "월봉(1M) 현물", "tv_btc_1m"),
        ("1w", 140, "주봉(1W) 현물", "tv_btc_1w"),
        ("1d", 140, "일봉(1D) 현물", "tv_btc_1d"),
        ("4h", 140, "4시간봉(4H) 현물", "tv_btc_4h")
    ]
    with ThreadPoolExecutor(max_workers=4) as ex:
        tf_dfs = list(ex.map(lambda cfg: fetch_spot_klines("BTCUSDT", cfg[0], cfg[1]), tf_configs))

    tf_tabs = st.tabs(["월봉 (거시)", "주봉 (중장기)", "일봉 (스윙)", "4시간봉 (단기)"])
    for t_tab, (interval, lim, label, cid), raw_df in zip(tf_tabs, tf_configs, tf_dfs):
        with t_tab:
            try:
                df_tf = calc_indicators(raw_df)
                html_desc, chart_lines, _, _, _, _, _ = analyze_spot_wave_and_fib(df_tf, label)
                render_tv_candle_chart(df_tf, cid, price_lines=chart_lines, show_ema=True, show_waves=True, height=340)
                st.markdown(f'<div class="reason-box">{html_desc}</div>', unsafe_allow_html=True)
            except Exception:
                st.warning(f"{label} 데이터를 불러오는 중입니다.")

    live_cvd_and_firechart_section()

with tab2:
    live_recommendations_section()

with tab3:
    live_econ_calendar_section()

with tab4:
    live_news_section()

with tab5:
    live_trade_journal_section()
