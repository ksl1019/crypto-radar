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
    # TradingView Lightweight Charts용 KST Unix Timestamp(초)
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

      if ({'true' if show_ema else 'false'}) {{
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
    # 손절폭의 2배 + 변동 민감도(beta) 반영하여 강제청산 여유폭 확보
    effective_risk = sl_pct * 2.0 * max(1.0, beta)
    max_safe = 100.0 / effective_risk

    # 증거금 크기에 따른 리스크 보정 계수
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
    # 1) 비트코인(BTCUSDT) 무조건 고정 분석
    btc_1d = calc_indicators(fetch_klines("BTCUSDT", "1d", 110))
    btc_4h = calc_indicators(fetch_klines("BTCUSDT", "4h", 110))
    c1d, c4h, p4h = btc_1d.iloc[-1], btc_4h.iloc[-1], btc_4h.iloc[-2]
    btc_price = float(c4h["close"])
    btc_atr = float(c4h["atr"])

    recent_btc = btc_4h.tail(60)
    hi_b, lo_b = float(recent_btc["high"].max()), float(recent_btc["low"].min())
    fib_618_b = hi_b - (hi_b - lo_b) * 0.618
    fib_382_b = hi_b - (hi_b - lo_b) * 0.382

    long_score, short_score = 0, 0
    btc_reasons = []

    # 거시/심리/수급 점수
    fng = overview["fng_val"]
    fund = overview["funding_num"]
    cvd_up = btc_4h["cvd"].iloc[-1] > btc_4h["cvd"].iloc[-6]

    if fng <= 20:
        long_score += 1.5
        btc_reasons.append(f"• **공포·탐욕 지수({fng}):** 극단적 공포 구간으로 투매 소진 후 기술적 반등 확률이 높습니다.")
    elif fng >= 75:
        short_score += 1.5
        btc_reasons.append(f"• **공포·탐욕 지수({fng}):** 극단적 탐욕 과열로 롱 물량 청산 빔 주의 구간입니다.")

    if fund < 0:
        long_score += 1
        btc_reasons.append(f"• **펀딩비({overview['funding_rate']}):** 음수(-) 펀딩비로 숏 포지션 쏠림(숏 스퀴즈 여력)이 포착됩니다.")
    elif fund > 0.03:
        short_score += 1
        btc_reasons.append(f"• **펀딩비({overview['funding_rate']}):** 양수(+) 과열로 롱 포지션 유지 비용 부담이 큽니다.")

    if cvd_up:
        long_score += 1
        btc_reasons.append("• **CVD 수급:** 최근 24시간 시장가 매수 델타가 우세합니다.")
    else:
        short_score += 1
        btc_reasons.append("• **CVD 수급:** 최근 24시간 시장가 매도 출회 압력이 우세합니다.")

    # 기술적 파동 & 이평선 점수
    if c4h["close"] > c4h["ema25"]:
        long_score += 1.5
        btc_reasons.append("• **4시간봉 이평선 & 파동:** EMA 25 상단 지지를 받으며 단기 상승 파동을 이어가고 있습니다.")
    else:
        short_score += 1.5
        btc_reasons.append("• **4시간봉 이평선 & 파동:** EMA 25 저항 아래에서 조정 파동(하방 압력)이 진행 중입니다.")

    if c4h["rsi"] < 35:
        long_score += 1.5
        btc_reasons.append(f"• **RSI({c4h['rsi']:.1f}):** 과매도권 진입으로 분할 반등 타점이 유효합니다.")
    elif c4h["rsi"] > 68:
        short_score += 1.5
        btc_reasons.append(f"• **RSI({c4h['rsi']:.1f}):** 과매수권 근접으로 단기 저항 눌림 가능성이 높습니다.")

    if abs(long_score - short_score) < 1.0:
        btc_dir = "SIDEWAYS"
        btc_sl = btc_price - (1.2 * btc_atr)
        btc_tp = btc_price + (1.2 * btc_atr)
        btc_reasons.append("• **종합 판단:** 상·하방 힘이 팽팽한 박스권 횡보 구간입니다. 돌파 확인 전까지 관망을 권장합니다.")
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

    # 2) 거래대금 상위 100위 중 변동성 활발한 35개 정밀 스캔 + BTC 동조화 계산
    tickers = requests.get("https://data-api.binance.vision/api/v3/ticker/24hr", timeout=5).json()
    usdt_pairs = [
        t for t in tickers
        if t["symbol"].endswith("USDT")
        and t["symbol"] != "BTCUSDT"
        and not any(x in t["symbol"] for x in ["UPUSDT", "DOWNUSDT", "USDC", "FDUSD", "TUSD", "USDP"])
    ]
    top100 = sorted(usdt_pairs, key=lambda x: float(x["quoteVolume"]), reverse=True)[:100]
    # 100위 안에서 당일 변동폭이 살아있는 35개 선별 (속도 및 타점 효율)
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

            # BTC 동조화(상관계수) 및 변동 민감도(베타)
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

            # 롱 조건
            if a1d["close"] > a1d["ema25"] and a4h["ema7"] > a4h["ema25"] and 42 <= a4h["rsi"] <= 68:
                score += 3
                reasons.append(f"• **추세 & 이평선 정배열:** 일봉·4시간봉 EMA 정배열 및 RSI({a4h['rsi']:.1f}) 건강한 상승 흐름입니다.")
                if abs(price - fib_618) / price < 0.035 or price > fib_382:
                    score += 1
                    reasons.append(f"• **피보나치 지지:** 되돌림 주요 구간(${fib_618:,.4f}~${fib_382:,.4f}) 상단에서 지지받고 있습니다.")
                if a4h["hist"] > 0 and a4h["hist"] > pa4h["hist"]:
                    score += 1
                    reasons.append("• **MACD 수급 확장:** 매수 모멘텀 히스토그램이 강해지고 있습니다.")
                # BTC 동조화 필터
                if corr >= 0.70 and btc_dir == "SHORT":
                    score -= 2
                elif corr < 0.35:
                    score += 1
                    reasons.append(f"• **독자 행보(디커플링 {corr*100:.0f}%):** 비트코인 눈치를 보지 않고 자체 수급으로 움직이는 종목입니다.")
                if score >= 4:
                    direction = "LONG"

            # 숏 조건
            elif a1d["close"] < a1d["ema25"] and a4h["ema7"] < a4h["ema25"] and 32 <= a4h["rsi"] <= 58:
                score += 3
                reasons.append(f"• **하락 추세 & 역배열:** 일봉·4시간봉 EMA 저항 아래에서 RSI({a4h['rsi']:.1f}) 추가 하락 여력이 있습니다.")
                if a4h["hist"] < 0 and a4h["hist"] < pa4h["hist"]:
                    score += 1
                    reasons.append("• **MACD 매도 압력:** 반등 실패 후 음봉 모멘텀이 다시 확대되고 있습니다.")
                if corr >= 0.70 and btc_dir == "LONG":
                    score -= 2
                elif corr < 0.35:
                    score += 1
                    reasons.append(f"• **독자 약세(디커플링 {corr*100:.0f}%):** 시장 반등과 무관하게 개별 매도세가 강합니다.")
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

# ---------------- TAB 1: 시장 브리핑 & 캔들 차트 & 유동성 ----------------
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
            • <b>상단 저항/청산 매물벽:</b> <span style="color:#
