import streamlit as st
import streamlit.components.v1 as components
import requests
import pandas as pd
import numpy as np
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

st.set_page_config(page_title="코인 레이더", page_icon="📡", layout="centered")

st.markdown("""
<style>
    .block-container { padding: 1rem 0.8rem 3rem 0.8rem; max-width: 620px; }
    header, footer { visibility: hidden; }
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
        padding: 3px 8px; border-radius: 6px; font-weight: bold; font-size: 0.8rem;
    }
    .badge-short {
        background-color: rgba(255, 75, 75, 0.15); color: #FF4B4B;
        padding: 3px 8px; border-radius: 6px; font-weight: bold; font-size: 0.8rem;
    }
    .badge-neutral {
        background-color: rgba(139, 148, 158, 0.15); color: #C9D1D9;
        padding: 3px 8px; border-radius: 6px; font-weight: bold; font-size: 0.8rem;
    }
    .reason-box {
        background-color: #0D1117; border-radius: 8px; padding: 10px;
        margin-top: 8px; font-size: 0.85rem; line-height: 1.55; color: #C9D1D9;
    }
    .lev-box {
        background-color: rgba(88, 166, 255, 0.1); border: 1px solid rgba(88, 166, 255, 0.3);
        border-radius: 8px; padding: 8px 10px; margin-top: 8px;
        font-size: 0.84rem; color: #79C0FF;
    }
    .news-card {
        background-color: #161B22; border: 1px solid #30363D;
        border-radius: 10px; padding: 12px 14px; margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

KST = timezone(timedelta(hours=9))

# ================= 1. 시장 요약 & 외부 데이터 수집 =================
@st.cache_data(ttl=180)
def get_market_overview():
    fng_val, fng_class, btc_dom = 50, "N/A", "N/A"
    btc_price, btc_chg, btc_chg_num = "N/A", "", 0.0
    funding_rate, funding_num = "N/A", 0.0

    try:
        res = requests.get("https://data-api.binance.vision/api/v3/ticker/24hr?symbol=BTCUSDT", timeout=5).json()
        price_num = float(res["lastPrice"])
        btc_chg_num = float(res["priceChangePercent"])
        btc_price = f"${price_num:,.1f}"
        btc_chg = f"({btc_chg_num:+.2f}%)"
    except Exception:
        pass

    try:
        res = requests.get("https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP", timeout=5).json()
        funding_num = float(res["data"][0]["fundingRate"]) * 100
        funding_rate = f"{funding_num:.4f}%"
    except Exception:
        pass

    try:
        res = requests.get("https://api.alternative.me/fng/", timeout=5).json()
        fng_val = int(res["data"][0]["value"])
        fng_class = res["data"][0]["value_classification"]
    except Exception:
        pass

    try:
        res = requests.get("https://api.coingecko.com/api/v3/global", timeout=5).json()
        btc_dom = f"{res['data']['market_cap_percentage']['btc']:.1f}%"
    except Exception:
        pass

    return {
        "fng_val": fng_val, "fng_class": fng_class, "btc_dom": btc_dom,
        "btc_price": btc_price, "btc_chg": btc_chg, "btc_chg_num": btc_chg_num,
        "funding_rate": funding_rate, "funding_num": funding_num
    }

@st.cache_data(ttl=300)
def get_us_indices():
    indices = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    for name, ticker in [("나스닥 (NASDAQ)", "^IXIC"), ("S&P 500", "^GSPC")]:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
            res = requests.get(url, headers=headers, timeout=5).json()
            meta = res["chart"]["result"][0]["meta"]
            cur = float(meta["regularMarketPrice"])
            prev = float(meta["chartPreviousClose"])
            chg = ((cur - prev) / prev) * 100
            indices[name] = {"price": f"{cur:,.2f}", "chg": chg}
        except Exception:
            indices[name] = {"price": "N/A", "chg": 0.0}
    return indices

def fetch_klines(symbol, interval, limit=110):
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    data = requests.get(url, timeout=5).json()
    df = pd.DataFrame(data, columns=[
        "time", "open", "high", "low", "close", "volume",
        "close_time", "qav", "num_trades", "taker_base_vol", "taker_quote_vol", "ignore"
    ])
    df["ts"] = (df["time"].astype(np.int64) // 1000) + (9 * 3600)
    for col in ["open", "high", "low", "close", "volume", "taker_base_vol"]:
        df[col] = df[col].astype(float)
    return df

def calc_indicators(df):
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

@st.cache_data(ttl=300)
def get_orderbook_walls(symbol="BTCUSDT"):
    url = f"https://data-api.binance.vision/api/v3/depth?symbol={symbol}&limit=500"
    depth = requests.get(url, timeout=5).json()
    bids = pd.DataFrame(depth["bids"], columns=["price", "qty"]).astype(float)
    asks = pd.DataFrame(depth["asks"], columns=["price", "qty"]).astype(float)
    bids["notional"] = bids["price"] * bids["qty"]
    asks["notional"] = asks["price"] * asks["qty"]
    top_bid = bids.groupby(np.round(bids["price"] / 250) * 250)["notional"].sum().idxmax()
    top_ask = asks.groupby(np.round(asks["price"] / 250) * 250)["notional"].sum().idxmax()
    return float(top_bid), float(top_ask)

# ================= 2. 트레이딩뷰 모바일 캔들 차트 렌더러 =================
def render_tv_candle_chart(df, chart_id, price_lines=None, show_ema=True, show_waves=True, height=340):
    sub = df.tail(75).copy().reset_index(drop=True)
    candles = [
        {"time": int(r["ts"]), "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"])}
        for _, r in sub.iterrows()
    ]
    ema7_data = [{"time": int(r["ts"]), "value": float(r["ema7"])} for _, r in sub.iterrows() if not np.isnan(r["ema7"])]
    ema25_data = [{"time": int(r["ts"]), "value": float(r["ema25"])} for _, r in sub.iterrows() if not np.isnan(r["ema25"])]
    ema99_data = [{"time": int(r["ts"]), "value": float(r["ema99"])} for _, r in sub.iterrows() if not np.isnan(r["ema99"])]

    markers = []
    if show_waves and len(sub) >= 30:
        step = 11
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
    <div id="{chart_id}" style="width: 100%; height: {height}px; border-radius: 10px; overflow: hidden;"></div>
    <script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
    <script>
      const container = document.getElementById('{chart_id}');
      const chart = LightweightCharts.createChart(container, {{
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
        wickUpColor: '#00D084', wickDownColor: '#FF4B4B'
      }});
      candleSeries.setData({json.dumps(candles)});
      const markers = {json.dumps(markers)};
      if (markers.length > 0) candleSeries.setMarkers(markers);

      if ({ema_flag}) {{
        const s7 = chart.addLineSeries({{ color: '#58A6FF', lineWidth: 1, title: 'EMA7' }});
        s7.setData({json.dumps(ema7_data)});
        const s25 = chart.addLineSeries({{ color: '#F2CC60', lineWidth: 1.5, title: 'EMA25' }});
        s25.setData({json.dumps(ema25_data)});
        const s99 = chart.addLineSeries({{ color: '#FF7B72', lineWidth: 1.5, title: 'EMA99' }});
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
    </script>
    """
    components.html(html_code, height=height + 6)

# ================= 3. 무청산 안전 레버리지 & BTC 종합 스캔 =================
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

@st.cache_data(ttl=480)
def scan_all_markets(overview):
    btc_4h = calc_indicators(fetch_klines("BTCUSDT", "4h", 110))
    c4h = btc_4h.iloc[-1]
    btc_price = float(c4h["close"])
    btc_atr = float(c4h["atr"])

    recent_btc = btc_4h.tail(60)
    hi_b, lo_b = float(recent_btc["high"].max()), float(recent_btc["low"].min())
    fib_618_b = hi_b - (hi_b - lo_b) * 0.618
    fib_382_b = hi_b - (hi_b - lo_b) * 0.382

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
        btc_reasons.append(f"• <b>펀딩비({overview['funding_rate']}):</b> 음수(-) 펀딩비로 숏 포지션 쏠림(숏 스퀴즈 여력)이 포착됩니다.")
    elif fund > 0.03:
        short_score += 1
        btc_reasons.append(f"• <b>펀딩비({overview['funding_rate']}):</b> 양수(+) 과열로 롱 포지션 유지 비용 부담이 큽니다.")

    if cvd_up:
        long_score += 1
        btc_reasons.append("• <b>CVD 수급:</b> 최근 24시간 시장가 매수 델타가 우세합니다.")
    else:
        short_score += 1
        btc_reasons.append("• <b>CVD 수급:</b> 최근 24시간 시장가 매도 출회 압력이 우세합니다.")

    if c4h["close"] > c4h["ema25"]:
        long_score += 1.5
        btc_reasons.append("• <b>4시간봉 이평선 & 파동:</b> EMA 25 상단 지지를 받으며 단기 상승 파동을 이어가고 있습니다.")
    else:
        short_score += 1.5
        btc_reasons.append("• <b>4시간봉 이평선 & 파동:</b> EMA 25 저항 아래에서 조정 파동(하방 압력)이 진행 중입니다.")

    if c4h["rsi"] < 35:
        long_score += 1.5
        btc_reasons.append(f"• <b>RSI({c4h['rsi']:.1f}):</b> 과매도권 진입으로 분할 반등 타점이 유효합니다.")
    elif c4h["rsi"] > 68:
        short_score += 1.5
        btc_reasons.append(f"• <b>RSI({c4h['rsi']:.1f}):</b> 과매수권 근접으로 단기 저항 눌림 가능성이 높습니다.")

    if abs(long_score - short_score) < 1.0:
        btc_dir = "SIDEWAYS"
        btc_sl = btc_price - (1.2 * btc_atr)
        btc_tp = btc_price + (1.2 * btc_atr)
        btc_reasons.append("• <b>종합 판단:</b> 상·하방 힘이 팽팽한 박스권 횡보 구간입니다. 돌파 확인 전까지 관망을 권장합니다.")
    elif long_score > short_score:
        btc_dir = "LONG"
        btc_sl = btc_price - (1.5 * btc_atr)
        btc_tp = btc_price + (2.5 * btc_atr)
    else:
        btc_dir = "SHORT"
        btc_sl = btc_price + (1.5 * btc_atr)
        btc_tp = btc_price - (2.5 * btc_atr)

    btc_pick = {
        "symbol": "BTCUSDT (기준 대장주)", "raw_symbol": "BTCUSDT", "is_btc": True,
        "direction": btc_dir, "price": btc_price, "sl": btc_sl, "tp": btc_tp,
        "reasons": "<br>".join(btc_reasons), "df_4h": btc_4h,
        "fib_618": fib_618_b, "fib_382": fib_382_b, "rsi": float(c4h["rsi"]),
        "corr": 1.0, "beta": 1.0
    }

    tickers = requests.get("https://data-api.binance.vision/api/v3/ticker/24hr", timeout=5).json()
    usdt_pairs = [
        t for t in tickers
        if t["symbol"].endswith("USDT")
        and t["symbol"] != "BTCUSDT"
        and not any(x in t["symbol"] for x in ["UPUSDT", "DOWNUSDT", "USDC", "FDUSD", "TUSD", "USDP"])
    ]
    top100 = sorted(usdt_pairs, key=lambda x: float(x["quoteVolume"]), reverse=True)[:100]
    candidates = sorted(top100, key=lambda x: abs(float(x["priceChangePercent"])), reverse=True)[:35]

    btc_ret = btc_4h["close"].pct_change().tail(60)
    alt_picks = []

    for item in candidates:
        sym = item["symbol"]
        try:
            df_1d = calc_indicators(fetch_klines(sym, "1d", 110))
            df_4h = calc_indicators(fetch_klines(sym, "4h", 110))
            a1d, a4h, pa4h = df_1d.iloc[-1], df_4h.iloc[-1], df_4h.iloc[-2]
            price, atr = float(a4h["close"]), float(a4h["atr"])

            alt_ret = df_4h["close"].pct_change().tail(60)
            corr = float(btc_ret.corr(alt_ret))
            if np.isnan(corr):
                corr = 0.5
            beta = float(alt_ret.std() / (btc_ret.std() + 1e-9))

            recent = df_4h.tail(60)
            hi, lo = float(recent["high"].max()), float(recent["low"].min())
            fib_618 = hi - (hi - lo) * 0.618
            fib_382 = hi - (hi - lo) * 0.382

            reasons, direction, score = [], None, 0

            if a1d["close"] > a1d["ema25"] and a4h["ema7"] > a4h["ema25"] and 42 <= a4h["rsi"] <= 68:
                score += 3
                reasons.append(f"• <b>추세 & 이평선 정배열:</b> 일봉·4시간봉 EMA 정배열 및 RSI({a4h['rsi']:.1f}) 건강한 상승 흐름입니다.")
                if abs(price - fib_618) / price < 0.035 or price > fib_382:
                    score += 1
                    reasons.append(f"• <b>피보나치 지지:</b> 되돌림 주요 구간(${fib_618:,.4f}~${fib_382:,.4f}) 상단에서 지지받고 있습니다.")
                if a4h["hist"] > 0 and a4h["hist"] > pa4h["hist"]:
                    score += 1
                    reasons.append("• <b>MACD 수급 확장:</b> 매수 모멘텀 히스토그램이 강해지고 있습니다.")
                if corr >= 0.70 and btc_dir == "SHORT":
                    score -= 2
                elif corr < 0.35:
                    score += 1
                    reasons.append(f"• <b>독자 행보(디커플링 {corr*100:.0f}%):</b> 비트코인 눈치를 보지 않고 자체 수급으로 움직이는 종목입니다.")
                if score >= 4:
                    direction = "LONG"

            elif a1d["close"] < a1d["ema25"] and a4h["ema7"] < a4h["ema25"] and 32 <= a4h["rsi"] <= 58:
                score += 3
                reasons.append(f"• <b>하락 추세 & 역배열:</b> 일봉·4시간봉 EMA 저항 아래에서 RSI({a4h['rsi']:.1f}) 추가 하락 여력이 있습니다.")
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
                sl = price - (1.5 * atr) if direction == "LONG" else price + (1.5 * atr)
                tp = price + (2.5 * atr) if direction == "LONG" else price - (2.5 * atr)
                alt_picks.append({
                    "symbol": sym, "raw_symbol": sym, "is_btc": False,
                    "direction": direction, "price": price, "sl": sl, "tp": tp,
                    "score": score, "reasons": "<br>".join(reasons), "df_4h": df_4h,
                    "fib_618": fib_618, "fib_382": fib_382, "rsi": float(a4h["rsi"]),
                    "corr": corr, "beta": beta
                })
        except Exception:
            continue

    top_alts = sorted(alt_picks, key=lambda x: x["score"], reverse=True)[:5]
    return btc_pick, top_alts

# ================= 4. 한글 경제 일정 & 코인니스 스타일 속보 =================
@st.cache_data(ttl=1800)
def get_korean_econ_calendar():
    trans_map = {
        "CPI": ("소비자물가지수 (CPI)", "예상치 상회 시 연준 금리 인하 지연 우려로 코인 단기 하락 압력"),
        "Core CPI": ("근원 소비자물가지수 (Core CPI)", "에너지·식품 제외 물가. 예상보다 높으면 긴축 경계감 확대(악재)"),
        "Non-Farm Employment Change": ("비농업 고용지수 (NFP)", "고용이 너무 뜨거우면 금리 인하 후퇴(악재), 적당히 둔화되면 호재"),
        "Unemployment Rate": ("미국 실업률", "실업률 상승 시 금리 인하 기대감(단기 호재)과 경기침체 우려 공존"),
        "Federal Funds Rate": ("연준(FOMC) 기준금리 결정", "금리 인하 및 비둘기파(완화) 발언 시 유동성 공급 기대감으로 강한 호재"),
        "FOMC Statement": ("FOMC 성명서 발표", "향후 금리 경로 힌트에 따라 비트코인 급등락 변동성 최고조 구간"),
        "PPI": ("생산자물가지수 (PPI)", "도매 물가 지표. 예상치 하회 시 인플레이션 완화 신호로 호재"),
        "Core PCE Price Index": ("근원 개인소비지출 물가 (PCE)", "연준이 가장 중시하는 물가 지표. 둔화 확인 시 위험자산 반등 요인"),
        "Retail Sales": ("미국 소매판매 지수", "소비 경기 판단 지표. 급격한 침체 신호가 아니면 완만한 둔화가 금리에 유리"),
        "GDP": ("미국 국내총생산 (GDP) 성장률", "성장률 견조 시 경기침체 우려 해소, 과열 시 긴축 경계"),
        "Unemployment Claims": ("주간 신규 실업수당 청구건수", "매주 목요일 발표. 예상보다 청구건수 증가 시 금리 인하 기대(소폭 호재)")
    }
    events = []
    try:
        res = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=5).json()
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
                events.append({
                    "time": dt_kst,
                    "importance": "🔴 중요" if ev.get("impact") == "High" else "🟡 보통",
                    "title": ko_title,
                    "forecast": ev.get("forecast") or "-",
                    "previous": ev.get("previous") or "-",
                    "desc": impact_desc
                })
    except Exception:
        pass
    return events

def analyze_news_sentiment(title):
    bull_kw = ["인하", "둔화", "완화", "승인", "유입", "순매수", "급등", "돌파", "반등", "채택", "호재", "강세", "매집"]
    bear_kw = ["인상", "긴축", "매파", "급락", "폭락", "유출", "순매도", "해킹", "규제", "소송", "제재", "악재", "약세", "파산", "청산"]
    if any(w in title for w in bull_kw):
        return "🟢 호재 (상승 요인)", "badge-long", "유동성 완화 또는 매수 수급 유입을 자극하는 긍정적 재료입니다."
    if any(w in title for w in bear_kw):
        return "🔴 악재 (하락 요인)", "badge-short", "위험자산 회피 심리 또는 매도 압력을 키울 수 있는 경계 재료입니다."
    return "⚪ 중립 (시장 관망)", "badge-neutral", "방향성 확정 전 추가 데이터와 시장 반응을 확인할 필요가 있습니다."

@st.cache_data(ttl=300)
def fetch_coinness_style_news():
    feeds = [
        ("🇺🇸 미국 거시·증시", "https://news.google.com/rss/search?q=미국+증시+연준+금리+when:2d&hl=ko&gl=KR&ceid=KR:ko"),
        ("🪙 국내 비트코인 속보", "https://news.google.com/rss/search?q=비트코인+가상자산+시세+when:2d&hl=ko&gl=KR&ceid=KR:ko")
    ]
    items = []
    headers = {"User-Agent": "Mozilla/5.0"}
    for cat, url in feeds:
        try:
            xml_text = requests.get(url, headers=headers, timeout=5).text
            root = ET.fromstring(xml_text)
            for item in root.findall("./channel/item")[:7]:
                title = item.findtext("title", "").split(" - ")[0]
                link = item.findtext("link", "")
                pub = item.findtext("pubDate", "")
                try:
                    dt_obj = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc).astimezone(KST)
                    time_txt = dt_obj.strftime("%m/%d %H:%M")
                except Exception:
                    time_txt = "최신"
                badge_txt, badge_cls, analysis = analyze_news_sentiment(title)
                items.append({
                    "cat": cat, "time": time_txt, "title": title, "link": link,
                    "badge_txt": badge_txt, "badge_cls": badge_cls, "analysis": analysis
                })
        except Exception:
            continue
    return items

# ================= 5. 메인 화면 렌더링 =================
st.markdown("### 📡 코인 선물 레이더")
st.caption(f"업데이트: {datetime.now(KST).strftime('%Y-%m-%d %H:%M')} (KST)")

if st.button("🔄 실시간 데이터 새로고침", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

ov = get_market_overview()
c1, c2 = st.columns(2)
with c1:
    chg_col = "#00D084" if ov["btc_chg_num"] >= 0 else "#FF4B4B"
    st.markdown(f"""
    <div class="metric-card">
        <div style="font-size:0.78rem; color:#8B949E;">BTC 현재가 / 펀딩비</div>
        <div style="font-size:1.05rem; font-weight:bold; color:#F0F6FC;">{ov['btc_price']} <span style="font-size:0.78rem; color:{chg_col};">{ov['btc_chg']}</span></div>
        <div style="font-size:0.8rem; color:#58A6FF;">펀딩비: {ov['funding_rate']}</div>
    </div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""
    <div class="metric-card">
        <div style="font-size:0.78rem; color:#8B949E;">공포·탐욕(일일) / 도미넌스</div>
        <div style="font-size:1.05rem; font-weight:bold; color:#F0F6FC;">{ov['fng_val']} <span style="font-size:0.78rem;">({ov['fng_class']})</span></div>
        <div style="font-size:0.8rem; color:#D2A8FF;">도미넌스: {ov['btc_dom']}</div>
    </div>""", unsafe_allow_html=True)

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 시장 브리핑", "🎯 추천 종목", "📅 경제 일정", "📰 경제·속보", "📝 매매일지"])

with tab1:
    halving_date = datetime(2024, 4, 20, tzinfo=KST)
    days_passed = (datetime.now(KST) - halving_date).days
    progress = min(days_passed / 1460, 1.0)
    st.markdown(f"""
    <div class="metric-card">
        <div style="font-weight:bold; color:#F0F6FC; margin-bottom:4px;">⏳ 비트코인 반감기 & 거시 싸이클</div>
        <div style="font-size:0.88rem; color:#FFA657;">4차 반감기 후 <b>{days_passed}일 경과</b> (거시 조정 파동 구간)</div>
        <div class="reason-box">
            • 반감기 후 12~18개월 고점 형성 뒤 약 1년간 거시 조정 구간이 진행됩니다.<br>
            • 무리한 고배율 추격보다 <b>유동성 매물벽 지지·저항 확인 후 분할 진입</b>이 유리합니다.
        </div>
    </div>""", unsafe_allow_html=True)
    st.progress(progress)

    st.markdown("#### 🕯️ BTC 4시간봉 & 호가 유동성 매물벽 (핀치 줌 지원)")
    try:
        btc_df = calc_indicators(fetch_klines("BTCUSDT", "4h", 90))
        top_bid, top_ask = get_orderbook_walls("BTCUSDT")
        walls = [
            {"price": top_ask, "color": "#FF4B4B", "width": 2, "style": 2, "title": "상단 청산·매도벽"},
            {"price": top_bid, "color": "#00D084", "width": 2, "style": 2, "title": "하단 지지·매수벽"}
        ]
        render_tv_candle_chart(btc_df, "tv_btc_main", price_lines=walls, show_ema=True, show_waves=True, height=340)
        cvd_trend = "매수세 유입 우세 (상방 지지)" if btc_df["cvd"].iloc[-1] > btc_df["cvd"].iloc[-6] else "매도세 출회 우세 (하방 압력)"
        st.markdown(f"""
        <div class="reason-box">
            • <b>상단 저항/청산 매물벽:</b> <span style="color:#FF7B72;">${top_ask:,.0f}</span> &nbsp;|&nbsp;
              <b>하단 지지/매수 매물벽:</b> <span style="color:#7EE787;">${top_bid:,.0f}</span><br>
            • <b>최근 24시간 CVD 수급:</b> {cvd_trend}
        </div>""", unsafe_allow_html=True)
    except Exception:
        st.warning("비트코인 차트 데이터를 불러오는 중입니다.")

with tab2:
    user_margin = st.number_input("💰 내 이번 진입 증거금 ($)", min_value=10.0, value=100.0, step=10.0)
    with st.spinner("비트코인 종합 분석 및 거래대금 100위 코인 스캔 중..."):
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
            <div style="font-size:0.78rem; color:#8B949E; margin-top:3px;">🔗 {corr_txt} · RSI(4H): {p['rsi']:.1f}</div>
            <div style="margin-top:8px; font-size:0.85rem; color:#8B949E;">
                진입가: <b style="color:#F0F6FC;">${p['price']:,.4f}</b> &nbsp;|&nbsp;
                손절가: <b style="color:#FF7B72;">${p['sl']:,.4f}</b> &nbsp;|&nbsp;
                목표가: <b style="color:#7EE787;">${p['tp']:,.4f}</b>
            </div>
            <div class="lev-box">
                🛡️ <b>증거금 ${user_margin:,.0f} 기준 무청산 추천 배율: {rec_lev}배</b>
                (예상 청산가: <b>${liq_price:,.4f}</b> · 손절폭 -{sl_pct:.1f}% 방어)
            </div>
            <div class="reason-box">
                <div style="font-weight:bold; color:#58A6FF; margin-bottom:4px;">💡 추천 근거 분석</div>
                {p['reasons']}
            </div>
        </div>""", unsafe_allow_html=True)

        with st.expander(f"🕯️ {p['raw_symbol']} 캔들 차트 작도 보기 (두 손가락 확대·축소)"):
            chart_lines = [
                {"price": p["price"], "color": "#FFFFFF", "width": 1, "style": 0, "title": "진입가"},
                {"price": p["sl"], "color": "#FF4B4B", "width": 2, "style": 2, "title": "손절가"},
                {"price": p["tp"], "color": "#00D084", "width": 2, "style": 2, "title": "목표가"},
                {"price": p["fib_618"], "color": "#FFA657", "width": 1, "style": 1, "title": "Fib 0.618"},
                {"price": p["fib_382"], "color": "#D2A8FF", "width": 1, "style": 1, "title": "Fib 0.382"}
            ]
            render_tv_candle_chart(p["df_4h"], f"tv_pick_{idx}", price_lines=chart_lines, show_ema=True, show_waves=True, height=340)

with tab3:
    st.markdown("#### 📅 이번 주 미국 주요 경제지표 발표 (한국시간)")
    st.caption("중요 지표 발표 전후 30분은 위아래 꼬리(휩쏘) 주의 구간입니다.")
    events = get_korean_econ_calendar()
    if not events:
        st.info("이번 주 예정된 주요 미국 경제지표 일정을 불러오는 중입니다.")
    else:
        for ev in events:
            st.markdown(f"""
            <div class="news-card">
                <div style="display:flex; justify-content:space-between; font-size:0.78rem; color:#8B949E;">
                    <span>{ev['importance']} &nbsp;|&nbsp; {ev['time']}</span>
                    <span>예상: <b style="color:#F0F6FC;">{ev['forecast']}</b> / 이전: {ev['previous']}</span>
                </div>
                <div style="font-size:0.98rem; font-weight:bold; color:#F0F6FC; margin:4px 0;">{ev['title']}</div>
                <div style="font-size:0.82rem; color:#79C0FF;">💡 {ev['desc']}</div>
            </div>""", unsafe_allow_html=True)

with tab4:
    st.markdown("#### 🇺🇸 미국 증시 vs 비트코인 실시간 흐름")
    us_idx = get_us_indices()
    u1, u2 = st.columns(2)
    for col, (name, info) in zip([u1, u2], us_idx.items()):
        c_col = "#00D084" if info["chg"] >= 0 else "#FF4B4B"
        col.markdown(f"""
        <div class="metric-card">
            <div style="font-size:0.78rem; color:#8B949E;">{name}</div>
            <div style="font-size:1.05rem; font-weight:bold; color:#F0F6FC;">{info['price']}</div>
            <div style="font-size:0.82rem; color:{c_col};">{info['chg']:+.2f}%</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("#### ⚡ 실시간 경제·코인 속보 (호재·악재 판독)")
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

with tab5:
    st.markdown("#### 📝 매매일지 및 성과 분석")
    sheet_url = st.secrets.get("SHEET_URL", "")
    if not sheet_url:
        sheet_url = st.text_input("구글 Apps Script 웹 앱 URL 입력", type="password")

    with st.form("trade_form", clear_on_submit=True):
        c_a, c_b = st.columns(2)
        symbol_in = c_a.text_input("종목명", value="BTCUSDT")
        pos_in = c_b.selectbox("포지션", ["롱 (LONG)", "숏 (SHORT)"])

        c_c, c_d = st.columns(2)
        margin_in = c_c.number_input("증거금 ($)", min_value=1.0, value=100.0, step=10.0)
        lev_in = c_d.number_input("레버리지 (배)", min_value=1, max_value=125, value=10)

        c_e, c_f = st.columns(2)
        entry_in = c_e.number_input("진입가 ($)", min_value=0.0, format="%.4f")
        exit_in = c_f.number_input("종료가 ($)", min_value=0.0, format="%.4f")

        tags_in = st.multiselect(
            "적용 근거 태그",
            ["AI추천종목", "엘리어트파동", "피보나치", "EMA이평선", "RSI", "MACD", "CVD/수급", "경제속보", "직접판단"]
        )
        memo_in = st.text_input("복기 메모", placeholder="예: CPI 발표 후 나스닥 반등 확인 후 롱 진입")
        submitted = st.form_submit_button("💾 구글 시트에 기록 저장", use_container_width=True)

        if submitted:
            if not sheet_url:
                st.error("구글 시트 웹 앱 URL이 설정되지 않았습니다.")
            elif entry_in <= 0 or exit_in <= 0:
                st.warning("진입가와 종료가를 정확히 입력해 주세요.")
            else:
                pos_size = margin_in * lev_in
                pct_change = ((exit_in - entry_in) / entry_in) if "롱" in pos_in else ((entry_in - exit_in) / entry_in)
                roi = pct_change * lev_in * 100
                pnl = pos_size * pct_change
                row_data = [
                    datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
                    symbol_in.upper(), pos_in, round(margin_in, 2), lev_in,
                    round(pos_size, 2), entry_in, exit_in, round(pnl, 2),
                    round(roi, 2), ", ".join(tags_in), memo_in
                ]
                try:
                    res = requests.post(sheet_url, json=row_data, timeout=8)
                    if res.status_code == 200:
                        st.success(f"저장 완료! 실현손익: ${pnl:+,.2f} ({roi:+.2f}%)")
                    else:
                        st.error("저장 실패. 웹 앱 URL 권한을 확인해 주세요.")
                except Exception as e:
                    st.error(f"연결 오류: {e}")

    if sheet_url:
        try:
            rows = requests.get(sheet_url, timeout=8).json()
            if len(rows) > 1:
                df_log = pd.DataFrame(rows[1:], columns=rows[0])
                df_log["수익금"] = pd.to_numeric(df_log["수익금"], errors="coerce").fillna(0)
                df_log["수익률"] = pd.to_numeric(df_log["수익률"], errors="coerce").fillna(0)

                total_pnl = df_log["수익금"].sum()
                wins = (df_log["수익금"] > 0).sum()
                total_trades = len(df_log)
                win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0

                m1, m2, m3 = st.columns(3)
                m1.metric("총 매매", f"{total_trades}건")
                m2.metric("전체 승률", f"{win_rate:.1f}%", f"{wins}승 {total_trades-wins}패")
                m3.metric("총 실현손익", f"${total_pnl:+,.2f}")

                st.markdown("##### 🔍 근거 태그별 승률 분석")
                tag_stats = []
                for tag in ["AI추천종목", "엘리어트파동", "피보나치", "EMA이평선", "RSI", "MACD", "CVD/수급", "경제속보", "직접판단"]:
                    sub_t = df_log[df_log["근거태그"].astype(str).str.contains(tag, na=False)]
                    if len(sub_t) > 0:
                        t_win = (sub_t["수익금"] > 0).mean() * 100
                        tag_stats.append({"근거": tag, "횟수": len(sub_t), "승률(%)": round(t_win, 1), "순손익($)": round(sub_t["수익금"].sum(), 2)})
                if tag_stats:
                    st.dataframe(pd.DataFrame(tag_stats), use_container_width=True, hide_index=True)

                st.markdown("##### 📋 최근 거래 내역")
                st.dataframe(df_log.iloc[::-1].head(10), use_container_width=True, hide_index=True)
        except Exception:
            st.caption("아직 기록된 데이터가 없거나 시트를 불러오는 중입니다.")
