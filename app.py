import streamlit as st
import streamlit.components.v1 as components
import requests
import pandas as pd
import numpy as np
import json
import re
import math
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
        border-radius: 8px; padding: 9px 11px; margin-top: 8px;
        font-size: 0.83rem; line-height: 1.52; color: #79C0FF;
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

def parse_ymd(val_str):
    nums = re.findall(r"\d+", str(val_str))
    if len(nums) >= 3:
        y, m, d = int(nums[0]), int(nums[1]), int(nums[2])
        if y < 100:
            y += 2000
        return y, m, d
    return None

# ================= 1. 구글 시트 계좌 · 보유종목 · 목표설정 영구 저장 로더 =================
@st.cache_data(ttl=25)
def load_sheet_state():
    sheet_url = st.secrets.get("SHEET_URL", "")
    state = {
        "has_url": bool(sheet_url),
        "wallet_bal": 0.0,
        "avail_bal": 0.0,
        "used_margin": 0.0,
        "open_list": [],
        "df_closed": pd.DataFrame(),
        "saved_goal": None,
        "error": None
    }
    if not sheet_url:
        return state

    try:
        rows = requests.get(sheet_url, timeout=8).json()
        if len(rows) > 1:
            clean_headers = [str(c).strip() for c in rows[0]]
            if clean_headers and clean_headers[0] != "일시":
                clean_headers[0] = "일시"
            df_all = pd.DataFrame(rows[1:], columns=clean_headers)

            for req_col in ["일시", "종목", "포지션", "증거금", "레버리지", "진입가", "종료가", "수익금", "수익률", "근거태그", "메모"]:
                if req_col not in df_all.columns:
                    df_all[req_col] = ""

            tag_col = df_all["근거태그"].astype(str)
            memo_col = df_all["메모"].astype(str)

            # 0) 구글 시트에 영구 저장된 마지막 목표 설정값 복원
            goal_mask = tag_col.str.startswith("GOAL_CONFIG") | (df_all["종목"] == "GOAL_CFG")
            df_goal = df_all[goal_mask]
            if not df_goal.empty:
                last_g = df_goal.iloc[-1]
                g_target = float(pd.to_numeric(last_g["진입가"], errors="coerce") or 0)
                g_days = int(float(pd.to_numeric(last_g["레버리지"], errors="coerce") or 30))
                g_ratio_idx = int(float(pd.to_numeric(last_g["수익금"], errors="coerce") or 0))
                if g_target > 0:
                    state["saved_goal"] = {
                        "target": g_target,
                        "days": max(3, g_days),
                        "ratio_idx": min(2, max(0, g_ratio_idx))
                    }

            # 1) 총 증거금(지갑 잔고) 스냅샷
            bal_mask = tag_col.str.startswith("BAL_SNAPSHOT|")
            df_bal = df_all[bal_mask]
            if not df_bal.empty:
                last_b = df_bal.iloc[-1]
                state["wallet_bal"] = float(pd.to_numeric(last_b["증거금"], errors="coerce") or 0)
                state["avail_bal"] = float(pd.to_numeric(last_b["진입가"], errors="coerce") or 0)
                state["used_margin"] = float(pd.to_numeric(last_b["종료가"], errors="coerce") or 0)

            # 2) 현재 보유 포지션 스냅샷
            open_mask = tag_col.str.startswith("OPEN_SNAPSHOT|") | memo_col.str.startswith("OPEN_SNAPSHOT|")
            df_open = df_all[tag_col.str.startswith("OPEN_SNAPSHOT|")].copy()
            if not df_open.empty:
                latest_batch = df_open["근거태그"].iloc[-1]
                cur_open = df_open[(df_open["근거태그"] == latest_batch) & (df_open["종목"] != "NONE")]
                state["open_list"] = cur_open.to_dict("records")

            # 3) 실제 종료된 매매 기록
            exclude_mask = goal_mask | bal_mask | open_mask | (df_all["종목"].isin(["WALLET", "NONE", "GOAL_CFG"]))
            df_closed = df_all[~exclude_mask].copy()
            if not df_closed.empty:
                for num_c in ["증거금", "레버리지", "진입가", "종료가", "수익금", "수익률"]:
                    df_closed[num_c] = pd.to_numeric(df_closed[num_c], errors="coerce").fillna(0)
                ymd_list = [parse_ymd(v) for v in df_closed["일시"]]
                df_closed["_ymd"] = ymd_list
                df_closed["_date_str"] = [f"{x[0]:04d}-{x[1]:02d}-{x[2]:02d}" if x else str(raw)[:10] for x, raw in zip(ymd_list, df_closed["일시"])]
            state["df_closed"] = df_closed
    except Exception as e:
        state["error"] = str(e)
    return state

def save_goal_to_sheet(target_val, days_val, ratio_idx):
    sheet_url = st.secrets.get("SHEET_URL", "")
    st.session_state["goal_target"] = float(target_val)
    st.session_state["goal_days"] = int(days_val)
    st.session_state["goal_ratio_idx"] = int(ratio_idx)
    if not sheet_url:
        return
    try:
        dt_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        row_data = [
            dt_str, "GOAL_CFG", "목표설정",
            0, int(days_val),
            round(float(target_val), 2), 0,
            int(ratio_idx), 0,
            "GOAL_CONFIG", "사용자목표영구저장"
        ]
        requests.post(sheet_url, json=row_data, timeout=6)
        load_sheet_state.clear()
    except Exception:
        pass

# ================= 2. 병렬 시장 요약 & 매크로 데이터 수집 =================
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

@st.cache_data(ttl=90)
def fetch_spot_klines(symbol, interval, limit=450):
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

# ================= 3. 현물 스윙 고·저점 기반 피보나치 & 추세 정밀 분석 =================
def fmt_p(val):
    return f"${val:,.4f}" if val < 10 else f"${val:,.1f}"

def analyze_spot_swing_fib(df, tf_name):
    sub = df.tail(180).copy().reset_index(drop=True)
    last_close = float(sub["close"].iloc[-1])
    ema25 = float(sub["ema25"].iloc[-1])
    rsi_val = float(sub["rsi"].iloc[-1]) if not np.isnan(sub["rsi"].iloc[-1]) else 50.0

    swing_low = float(sub["low"].min())
    low_idx = int(sub["low"].idxmin())
    swing_high = float(sub["high"].max())
    high_idx = int(sub["high"].idxmax())

    if low_idx < high_idx:
        swing_range = max(swing_high - swing_low, 1e-9)
        fib_382 = swing_high - swing_range * 0.382
        fib_500 = swing_high - swing_range * 0.500
        fib_618 = swing_high - swing_range * 0.618
        fib_ext_1272 = swing_low + swing_range * 1.272
        fib_ext_1618 = swing_low + swing_range * 1.618

        up_1272_pct = (fib_ext_1272 - last_close) / last_close * 100
        up_1618_pct = (fib_ext_1618 - last_close) / last_close * 100

        if last_close >= fib_618 and last_close > ema25:
            badge = f'<span class="badge-long">🟢 {tf_name} 상승 추세 · 피보나치 지지 유효</span>'
            main_scen = (
                f"최근 1달 스윙 저점(<b>{fmt_p(swing_low)}</b>)→고점(<b>{fmt_p(swing_high)}</b>) 상승폭 대비 핵심 눌림목 지지선인 "
                f"<b>피보나치 0.618({fmt_p(fib_618)})</b> 및 EMA 25 상단을 지키고 있습니다. "
                f"직전 고점 돌파 시 1차 확장 목표는 <b>{fmt_p(fib_ext_1272)} ({up_1272_pct:+.1f}%)</b>, "
                f"1.618 확장 목표는 <b>{fmt_p(fib_ext_1618)} ({up_1618_pct:+.1f}%)</b>입니다."
            )
            alt_scen = (
                f"<b>피보나치 0.618({fmt_p(fib_618)})</b> 아래로 종가 이탈 시 상승 추세 눌림목 관점은 <b>무효화</b>되며, "
                f"스윙 저점 <b>{fmt_p(swing_low)}</b> 재테스트 가능성을 열어둬야 합니다."
            )
        else:
            badge = f'<span class="badge-short">🔴 {tf_name} 피보나치 0.618 지지 이탈 · 조정 우세</span>'
            main_scen = (
                f"직전 상승폭의 핵심 방어선인 <b>피보나치 0.618({fmt_p(fib_618)})</b> 아래로 밀려나 단기 상승 탄력이 꺾였습니다. "
                f"하단 스윙 저점(<b>{fmt_p(swing_low)}</b>) 부근까지 추가 조정 압력이 열려 있습니다."
            )
            alt_scen = (
                f"<b>{fmt_p(fib_500)} ~ {fmt_p(fib_382)}</b> 저항 구간과 EMA 25를 강하게 돌파 안착해야만 "
                f"전고점(<b>{fmt_p(swing_high)}</b>) 재도전 시나리오가 복구됩니다."
            )

        chart_lines = [
            {"price": swing_high, "color": "#8B949E", "width": 1, "style": 2, "title": "스윙 고점"},
            {"price": fib_382, "color": "#58A6FF", "width": 1, "style": 3, "title": "Fib 0.382"},
            {"price": fib_618, "color": "#FF4B4B", "width": 2, "style": 2, "title": "⚠️ 지지마지노선(0.618)"},
            {"price": fib_ext_1272, "color": "#00D084", "width": 1, "style": 1, "title": "🎯 확장 1.272"},
            {"price": fib_ext_1618, "color": "#7EE787", "width": 1, "style": 1, "title": "🎯 확장 1.618"}
        ]
    else:
        swing_range = max(swing_high - swing_low, 1e-9)
        fib_382 = swing_low + swing_range * 0.382
        fib_500 = swing_low + swing_range * 0.500
        fib_618 = swing_low + swing_range * 0.618
        fib_down_1272 = max(swing_low * 0.5, swing_high - swing_range * 1.272)

        dn_pct = (fib_down_1272 - last_close) / last_close * 100

        if last_close <= fib_618 and last_close < ema25:
            badge = f'<span class="badge-short">🔴 {tf_name} 하락 추세 · 피보나치 저항 유효</span>'
            main_scen = (
                f"최근 1달 스윙 고점(<b>{fmt_p(swing_high)}</b>)→저점(<b>{fmt_p(swing_low)}</b>) 하락폭의 되돌림 저항선인 "
                f"<b>피보나치 0.618({fmt_p(fib_618)})</b> 및 EMA 25 저항 아래에 눌려 있습니다. "
                f"저점 이탈 시 하방 확장 목표는 <b>{fmt_p(fib_down_1272)} ({dn_pct:+.1f}%)</b> 구간입니다."
            )
            alt_scen = (
                f"되돌림 저항인 <b>피보나치 0.618({fmt_p(fib_618)})</b> 위로 안착하면 하락 추세 관점은 <b>무효화</b>되며, "
                f"전고점(<b>{fmt_p(swing_high)}</b>) 방향 추세 전환을 대비해야 합니다."
            )
        else:
            badge = f'<span class="badge-long">🟢 {tf_name} 하락 추세 돌파 시도 (0.618 상회)</span>'
            main_scen = (
                f"직전 하락폭의 핵심 저항이던 <b>피보나치 0.618({fmt_p(fib_618)})</b> 위로 올라서며 바닥 다지기 후 반등 추세로 전환 중입니다. "
                f"1차 상단 목표는 직전 스윙 고점(<b>{fmt_p(swing_high)}</b>)입니다."
            )
            alt_scen = (
                f"다시 <b>{fmt_p(fib_382)}</b> 아래로 밀려나면 돌파 실패(속임수 반등)로 판단해야 합니다."
            )

        chart_lines = [
            {"price": swing_high, "color": "#8B949E", "width": 1, "style": 2, "title": "스윙 고점"},
            {"price": fib_618, "color": "#FF4B4B", "width": 2, "style": 2, "title": "⚠️ 저항마지노선(0.618)"},
            {"price": fib_382, "color": "#FFA657", "width": 1, "style": 3, "title": "되돌림 0.382"},
            {"price": swing_low, "color": "#00D084", "width": 1, "style": 2, "title": "스윙 저점"}
        ]

    html_desc = (
        f"{badge} <span style='font-size:0.76rem; color:#8B949E;'>· RSI {rsi_val:.1f}</span>"
        f"<div style='margin-top:6px;'><b style='color:#7EE787;'>[🟢 메인 시나리오 · 피보나치 분석]</b><br>{main_scen}</div>"
        f"<div style='margin-top:6px;'><b style='color:#FF7B72;'>[🔴 대안 시나리오 · 무효화 기준]</b><br>{alt_scen}</div>"
    )
    return {
        "html_desc": html_desc,
        "chart_lines": chart_lines,
        "swing_low": swing_low,
        "swing_high": swing_high,
        "fib_382": fib_382,
        "fib_618": fib_618,
        "is_uptrend_structure": low_idx < high_idx
    }

# ================= 4. 1초 실시간 캔들 + 보조지표(EMA·거래량·RSI·MACD) 동시 재계산 차트 =================
def render_tv_pro_chart(df, chart_id, watermark_text="", price_lines=None, live_symbol=None, live_interval="4h", show_indicators=True, height=480):
    sub = df.copy().reset_index(drop=True)
    candles = [
        {"time": int(r["ts"]), "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"])}
        for _, r in sub.iterrows()
    ]
    vols = [
        {
            "time": int(r["ts"]),
            "value": float(r["volume"]),
            "color": "rgba(0, 208, 132, 0.45)" if float(r["close"]) >= float(r["open"]) else "rgba(255, 75, 75, 0.45)"
        }
        for _, r in sub.iterrows()
    ]
    ema7_data = [{"time": int(r["ts"]), "value": float(r["ema7"])} for _, r in sub.iterrows() if not np.isnan(r["ema7"])]
    ema25_data = [{"time": int(r["ts"]), "value": float(r["ema25"])} for _, r in sub.iterrows() if not np.isnan(r["ema25"])]
    ema99_data = [{"time": int(r["ts"]), "value": float(r["ema99"])} for _, r in sub.iterrows() if not np.isnan(r["ema99"])]
    rsi_data = [{"time": int(r["ts"]), "value": float(r["rsi"])} for _, r in sub.iterrows() if not np.isnan(r["rsi"])]
    macd_data = [{"time": int(r["ts"]), "value": float(r["macd"])} for _, r in sub.iterrows() if not np.isnan(r["macd"])]
    sig_data = [{"time": int(r["ts"]), "value": float(r["signal"])} for _, r in sub.iterrows() if not np.isnan(r["signal"])]
    hist_data = [
        {
            "time": int(r["ts"]),
            "value": float(r["hist"]),
            "color": "rgba(0, 208, 132, 0.65)" if float(r["hist"]) >= 0 else "rgba(255, 75, 75, 0.65)"
        }
        for _, r in sub.iterrows() if not np.isnan(r["hist"])
    ]

    # JS에서 1초마다 RSI(14)와 MACD(12,26,9), EMA(7,25,99)를 즉시 재계산할 수 있도록 직전 14개 종가 및 직전 EMA 상태 전달
    closes_tail = [float(x) for x in sub["close"].tail(20).tolist()]
    prev_ema7 = float(sub["ema7"].iloc[-2]) if len(sub) >= 2 else float(sub["close"].iloc[-1])
    prev_ema25 = float(sub["ema25"].iloc[-2]) if len(sub) >= 2 else float(sub["close"].iloc[-1])
    prev_ema99 = float(sub["ema99"].iloc[-2]) if len(sub) >= 2 else float(sub["close"].iloc[-1])
    ema12_series = sub["close"].ewm(span=12, adjust=False).mean()
    ema26_series = sub["close"].ewm(span=26, adjust=False).mean()
    prev_ema12 = float(ema12_series.iloc[-2]) if len(sub) >= 2 else float(sub["close"].iloc[-1])
    prev_ema26 = float(ema26_series.iloc[-2]) if len(sub) >= 2 else float(sub["close"].iloc[-1])
    prev_sig = float(sub["signal"].iloc[-2]) if len(sub) >= 2 else 0.0

    last_price = float(sub["close"].iloc[-1])
    last_rsi = float(sub["rsi"].iloc[-1]) if not np.isnan(sub["rsi"].iloc[-1]) else 50.0
    last_macd = float(sub["macd"].iloc[-1]) if not np.isnan(sub["macd"].iloc[-1]) else 0.0
    last_sig = float(sub["signal"].iloc[-1]) if not np.isnan(sub["signal"].iloc[-1]) else 0.0

    if last_price < 1:
        prec, min_move = 4, 0.0001
    elif last_price < 50:
        prec, min_move = 3, 0.001
    else:
        prec, min_move = 2, 0.01

    lines_json = json.dumps(price_lines or [])
    wm_flag = "true" if watermark_text else "false"
    ws_sym = str(live_symbol).lower() if live_symbol else ""
    ind_flag = "true" if show_indicators else "false"

    main_h = int(height * 0.58) if show_indicators else height
    rsi_h = int(height * 0.21) if show_indicators else 0
    macd_h = int(height * 0.21) if show_indicators else 0

    sub_panels_html = ""
    if show_indicators:
        sub_panels_html = f"""
        <div style="font-size:11px; color:#8B949E; padding:4px 8px 2px 8px; background:#0D1117; border-top:1px solid #21262D; display:flex; justify-content:space-between;">
          <span>📊 RSI (14) <span style="color:#E3B341;">■</span></span>
          <span>실시간 RSI: <b id="{chart_id}_rsi_txt" style="color:#F0F6FC;">{last_rsi:.1f}</b> (70 / 30)</span>
        </div>
        <div id="{chart_id}_rsi" style="width: 100%; height: {rsi_h}px; background: #0D1117;"></div>
        <div style="font-size:11px; color:#8B949E; padding:4px 8px 2px 8px; background:#0D1117; border-top:1px solid #21262D; display:flex; justify-content:space-between;">
          <span>📉 MACD (12, 26, 9) · <span style="color:#58A6FF;">MACD</span> / <span style="color:#FFA657;">Signal</span></span>
          <span id="{chart_id}_macd_txt" style="color:#C9D1D9;">{last_macd:.4f} / {last_sig:.4f}</span>
        </div>
        <div id="{chart_id}_macd" style="width: 100%; height: {macd_h}px; background: #0D1117;"></div>
        """

    html_code = f"""
    <div style="border:1px solid #30363D; border-radius:10px; overflow:hidden; background:#0D1117; font-family:sans-serif;">
      <div style="font-size:11px; color:#8B949E; padding:5px 8px; background:#161B22; display:flex; justify-content:space-between; align-items:center;">
        <span>🕯️ 캔들+거래량 · <span style="color:#58A6FF;">EMA7</span>/<span style="color:#F2CC60;">25</span>/<span style="color:#FF7B72;">99</span></span>
        <span style="color:#00D084; font-weight:bold;">● 1초 실시간 (지표 연동)</span>
      </div>
      <div id="{chart_id}_main" style="width: 100%; height: {main_h}px; background: #0D1117;"></div>
      {sub_panels_html}
    </div>
    <script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
    <script>
      const mainEl = document.getElementById('{chart_id}_main');
      const initW = mainEl.clientWidth || window.innerWidth || 560;

      const commonOpts = {{
        width: initW,
        layout: {{ background: {{ color: '#0D1117' }}, textColor: '#C9D1D9' }},
        grid: {{ vertLines: {{ color: '#1F242C' }}, horzLines: {{ color: '#1F242C' }} }},
        rightPriceScale: {{ borderColor: '#30363D', minimumWidth: 68 }},
        timeScale: {{ borderColor: '#30363D', timeVisible: true, secondsVisible: false, rightOffset: 4, minBarSpacing: 0.4 }},
        handleScroll: {{ mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false }},
        handleScale: {{ axisPressedMouseMove: true, mouseWheel: true, pinch: true }}
      }};

      const mainChart = LightweightCharts.createChart(mainEl, {{
        ...commonOpts,
        height: {main_h},
        watermark: {{
          visible: {wm_flag},
          fontSize: 20,
          horzAlign: 'center',
          vertAlign: 'center',
          color: 'rgba(255, 255, 255, 0.08)',
          text: '{watermark_text}'
        }}
      }});

      const candleSeries = mainChart.addCandlestickSeries({{
        upColor: '#00D084', downColor: '#FF4B4B', borderVisible: false,
        wickUpColor: '#00D084', wickDownColor: '#FF4B4B',
        priceFormat: {{ type: 'price', precision: {prec}, minMove: {min_move} }}
      }});
      candleSeries.setData({json.dumps(candles)});

      const volSeries = mainChart.addHistogramSeries({{
        priceFormat: {{ type: 'volume' }},
        priceScaleId: 'vol'
      }});
      mainChart.priceScale('vol').applyOptions({{
        scaleMargins: {{ top: 0.80, bottom: 0 }}
      }});
      volSeries.setData({json.dumps(vols)});

      const s7 = mainChart.addLineSeries({{ color: '#58A6FF', lineWidth: 1, priceFormat: {{ type: 'price', precision: {prec}, minMove: {min_move} }} }});
      s7.setData({json.dumps(ema7_data)});
      const s25 = mainChart.addLineSeries({{ color: '#F2CC60', lineWidth: 1.5, priceFormat: {{ type: 'price', precision: {prec}, minMove: {min_move} }} }});
      s25.setData({json.dumps(ema25_data)});
      const s99 = mainChart.addLineSeries({{ color: '#FF7B72', lineWidth: 1.5, priceFormat: {{ type: 'price', precision: {prec}, minMove: {min_move} }} }});
      s99.setData({json.dumps(ema99_data)});

      const priceLines = {lines_json};
      priceLines.forEach(pl => {{
        candleSeries.createPriceLine({{
          price: pl.price, color: pl.color, lineWidth: pl.width || 1,
          lineStyle: pl.style || 2, axisLabelVisible: true, title: pl.title
        }});
      }});
      mainChart.timeScale().fitContent();

      let rsiChart = null, macdChart = null;
      let rsiSeries = null, histSeries = null, macdLine = null, sigLine = null;
      if ({ind_flag}) {{
        const rsiEl = document.getElementById('{chart_id}_rsi');
        rsiChart = LightweightCharts.createChart(rsiEl, {{
          ...commonOpts,
          height: {rsi_h},
          timeScale: {{ ...commonOpts.timeScale, visible: false }}
        }});
        rsiSeries = rsiChart.addLineSeries({{ color: '#E3B341', lineWidth: 1.5 }});
        rsiSeries.setData({json.dumps(rsi_data)});
        rsiSeries.createPriceLine({{ price: 70, color: 'rgba(255, 75, 75, 0.5)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '' }});
        rsiSeries.createPriceLine({{ price: 30, color: 'rgba(0, 208, 132, 0.5)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '' }});
        rsiChart.timeScale().fitContent();

        const macdEl = document.getElementById('{chart_id}_macd');
        macdChart = LightweightCharts.createChart(macdEl, {{
          ...commonOpts,
          height: {macd_h}
        }});
        histSeries = macdChart.addHistogramSeries({{}});
        histSeries.setData({json.dumps(hist_data)});
        macdLine = macdChart.addLineSeries({{ color: '#58A6FF', lineWidth: 1.3 }});
        macdLine.setData({json.dumps(macd_data)});
        sigLine = macdChart.addLineSeries({{ color: '#FFA657', lineWidth: 1.3 }});
        sigLine.setData({json.dumps(sig_data)});
        macdChart.timeScale().fitContent();

        mainChart.timeScale().subscribeVisibleLogicalRangeChange(range => {{
          if (range) {{
            rsiChart.timeScale().setVisibleLogicalRange(range);
            macdChart.timeScale().setVisibleLogicalRange(range);
          }}
        }});
      }}

      // 실시간 웹소켓: 캔들 + 거래량 + EMA + RSI(14) + MACD(12,26,9) 1초마다 동시 재계산 & 갱신
      const wsSym = '{ws_sym}';
      const wsIntv = '{live_interval}';
      const histCloses = {json.dumps(closes_tail)};
      const prevEma7 = {prev_ema7};
      const prevEma25 = {prev_ema25};
      const prevEma99 = {prev_ema99};
      const prevEma12 = {prev_ema12};
      const prevEma26 = {prev_ema26};
      const prevSig = {prev_sig};

      function calcLiveRSI(closesArr) {{
        if (closesArr.length < 15) return 50.0;
        const recent = closesArr.slice(-15);
        let gainSum = 0, lossSum = 0;
        for (let i = 1; i < recent.length; i++) {{
          const diff = recent[i] - recent[i - 1];
          if (diff > 0) gainSum += diff;
          else lossSum -= diff;
        }}
        const avgGain = gainSum / 14.0;
        const avgLoss = lossSum / 14.0;
        if (avgLoss === 0) return 100.0;
        const rs = avgGain / avgLoss;
        return 100.0 - (100.0 / (1.0 + rs));
      }}

      if (wsSym) {{
        function connectKlineWS() {{
          const ws = new WebSocket('wss://stream.binance.com:9443/ws/' + wsSym + '@kline_' + wsIntv);
          ws.onmessage = (ev) => {{
            const msg = JSON.parse(ev.data);
            if (!msg.k) return;
            const k = msg.k;
            const tSec = Math.floor(k.t / 1000) + (9 * 3600);
            const o = parseFloat(k.o), h = parseFloat(k.h), l = parseFloat(k.l), c = parseFloat(k.c), v = parseFloat(k.v);

            // 1) 메인 캔들 & 거래량 갱신
            candleSeries.update({{ time: tSec, open: o, high: h, low: l, close: c }});
            volSeries.update({{
              time: tSec,
              value: v,
              color: c >= o ? 'rgba(0, 208, 132, 0.45)' : 'rgba(255, 75, 75, 0.45)'
            }});

            // 2) EMA 7 / 25 / 99 실시간 갱신
            const curEma7 = c * (2 / 8) + prevEma7 * (1 - 2 / 8);
            const curEma25 = c * (2 / 26) + prevEma25 * (1 - 2 / 26);
            const curEma99 = c * (2 / 100) + prevEma99 * (1 - 2 / 100);
            s7.update({{ time: tSec, value: curEma7 }});
            s25.update({{ time: tSec, value: curEma25 }});
            s99.update({{ time: tSec, value: curEma99 }});

            // 3) RSI(14) & MACD(12, 26, 9) 실시간 재계산 & 그래프/텍스트 동시 갱신
            if ({ind_flag}) {{
              const tempCloses = histCloses.slice(0, -1).concat([c]);
              const liveRsi = calcLiveRSI(tempCloses);
              if (rsiSeries) rsiSeries.update({{ time: tSec, value: liveRsi }});
              const rsiTxtEl = document.getElementById('{chart_id}_rsi_txt');
              if (rsiTxtEl) {{
                rsiTxtEl.textContent = liveRsi.toFixed(1);
                rsiTxtEl.style.color = liveRsi >= 70 ? '#FF4B4B' : (liveRsi <= 30 ? '#00D084' : '#F0F6FC');
              }}

              const curEma12 = c * (2 / 13) + prevEma12 * (1 - 2 / 13);
              const curEma26 = c * (2 / 27) + prevEma26 * (1 - 2 / 27);
              const curMacd = curEma12 - curEma26;
              const curSig = curMacd * (2 / 10) + prevSig * (1 - 2 / 10);
              const curHist = curMacd - curSig;

              if (macdLine) macdLine.update({{ time: tSec, value: curMacd }});
              if (sigLine) sigLine.update({{ time: tSec, value: curSig }});
              if (histSeries) {{
                histSeries.update({{
                  time: tSec,
                  value: curHist,
                  color: curHist >= 0 ? 'rgba(0, 208, 132, 0.65)' : 'rgba(255, 75, 75, 0.65)'
                }});
              }}
              const macdTxtEl = document.getElementById('{chart_id}_macd_txt');
              if (macdTxtEl) {{
                macdTxtEl.textContent = curMacd.toFixed(4) + ' / ' + curSig.toFixed(4);
              }}
            }}
          }};
          ws.onclose = () => setTimeout(connectKlineWS, 3000);
        }}
        connectKlineWS();
      }}

      const ro = new ResizeObserver(entries => {{
        for (let entry of entries) {{
          const w = entry.contentRect.width;
          if (w > 10) {{
            mainChart.resize(w, {main_h});
            mainChart.timeScale().fitContent();
            if (rsiChart) {{ rsiChart.resize(w, {rsi_h}); rsiChart.timeScale().fitContent(); }}
            if (macdChart) {{ macdChart.resize(w, {macd_h}); macdChart.timeScale().fitContent(); }}
          }}
        }}
      }});
      ro.observe(mainEl);
    </script>
    """
    total_h = height + (52 if show_indicators else 34)
    components.html(html_code, height=total_h)

def render_tv_cvd_chart(df, chart_id="tv_cvd_chart", height=220):
    sub = df.tail(240).copy().reset_index(drop=True)
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
        watermark: {{
          visible: true,
          fontSize: 18,
          horzAlign: 'center',
          vertAlign: 'center',
          color: 'rgba(255, 255, 255, 0.08)',
          text: 'BTCUSDT · 4H CVD (40일)'
        }},
        grid: {{ vertLines: {{ color: '#1F242C' }}, horzLines: {{ color: '#1F242C' }} }},
        rightPriceScale: {{ borderColor: '#30363D' }},
        timeScale: {{ borderColor: '#30363D', timeVisible: true, secondsVisible: false, minBarSpacing: 0.4 }},
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

# ================= 5. 목표 역산 맞춤 배율 계산기 & 병렬 고속 스캔 =================
def calc_goal_adjusted_leverage(entry, sl, tp, entry_margin, daily_goal_usd, beta=1.0, is_btc=False):
    sl_pct = max(0.5, abs(entry - sl) / entry * 100)
    tp_pct = max(0.5, abs(tp - entry) / entry * 100)

    effective_risk = sl_pct * 2.0 * max(1.0, beta)
    max_safe_lev = int(max(1, min(25 if is_btc else 15, round(100.0 / effective_risk))))

    if entry_margin > 0 and tp_pct > 0 and daily_goal_usd > 0:
        raw_needed_lev = math.ceil(daily_goal_usd / (entry_margin * (tp_pct / 100.0)))
    else:
        raw_needed_lev = 3

    final_lev = max(1, min(max_safe_lev, raw_needed_lev))
    est_tp_profit = entry_margin * (tp_pct / 100.0) * final_lev
    est_sl_loss = entry_margin * (sl_pct / 100.0) * final_lev
    trades_needed = max(1, math.ceil(daily_goal_usd / max(est_tp_profit, 0.01)))
    capped_by_safety = raw_needed_lev > max_safe_lev

    return {
        "lev": final_lev,
        "max_safe_lev": max_safe_lev,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "est_tp_profit": est_tp_profit,
        "est_sl_loss": est_sl_loss,
        "trades_needed": trades_needed,
        "capped": capped_by_safety
    }

def analyze_single_alt(sym, btc_ret, btc_dir):
    try:
        df_1d = calc_indicators(fetch_spot_klines(sym, "1d", 250))
        df_4h = calc_indicators(fetch_spot_klines(sym, "4h", 450))
        a1d, a4h, pa4h = df_1d.iloc[-1], df_4h.iloc[-1], df_4h.iloc[-2]
        price, atr = float(a4h["close"]), float(a4h["atr"])

        fib_info = analyze_spot_swing_fib(df_4h, "4시간봉")
        fib_618 = fib_info["fib_618"]
        fib_382 = fib_info["fib_382"]
        swing_low = fib_info["swing_low"]
        swing_high = fib_info["swing_high"]

        alt_ret = df_4h["close"].pct_change().tail(60)
        corr = float(btc_ret.corr(alt_ret))
        if np.isnan(corr):
            corr = 0.5
        beta = float(alt_ret.std() / (btc_ret.std() + 1e-9))

        reasons, direction, score = [], None, 0

        if a1d["close"] > a1d["ema25"] and a4h["ema7"] > a4h["ema25"] and 42 <= a4h["rsi"] <= 68 and price > fib_618:
            score += 3
            reasons.append(f"• <b>일봉·4시간봉 추세 정배열:</b> EMA 7 > 25 정배열 및 RSI({a4h['rsi']:.1f}) 건강한 상승 흐름입니다.")
            reasons.append(f"• <b>피보나치 0.618 지지 방어:</b> 핵심 지지선(<b>${fib_618:,.4f}</b>) 위에서 눌림목 지지를 확인했습니다.")
            if a4h["hist"] > 0 and a4h["hist"] > pa4h["hist"]:
                score += 1
                reasons.append("• <b>4시간봉 MACD 수급:</b> 매수 모멘텀 히스토그램이 확장되고 있습니다.")
            if corr >= 0.70 and btc_dir == "SHORT":
                score -= 2
            elif corr < 0.35:
                score += 1
                reasons.append(f"• <b>독자 강세(디커플링 {corr*100:.0f}%):</b> 비트코인 약세와 무관하게 개별 수급이 유입 중입니다.")
            if score >= 4:
                direction = "LONG"

        elif a1d["close"] < a1d["ema25"] and a4h["ema7"] < a4h["ema25"] and 32 <= a4h["rsi"] <= 58 and price < fib_618:
            score += 3
            reasons.append(f"• <b>일봉·4시간봉 추세 역배열:</b> EMA 7 < 25 저항 아래에서 RSI({a4h['rsi']:.1f}) 하방 압력이 우세합니다.")
            reasons.append(f"• <b>피보나치 저항 구간:</b> 되돌림 저항선(<b>${fib_618:,.4f}</b>) 돌파에 실패하고 약세가 이어집니다.")
            if a4h["hist"] < 0 and a4h["hist"] < pa4h["hist"]:
                score += 1
                reasons.append("• <b>4시간봉 MACD 매도 압력:</b> 음봉 모멘텀이 다시 확대되고 있습니다.")
            if corr >= 0.70 and btc_dir == "LONG":
                score -= 2
            elif corr < 0.35:
                score += 1
                reasons.append(f"• <b>독자 약세(디커플링 {corr*100:.0f}%):</b> 시장 반등과 무관하게 매도 출회가 강합니다.")
            if score >= 4:
                direction = "SHORT"

        if direction:
            if direction == "LONG":
                sl = max(fib_618 * 0.992, price - (1.6 * atr))
                tp = swing_high if swing_high > price * 1.02 else price + (2.6 * atr)
            else:
                sl = min(fib_618 * 1.008, price + (1.6 * atr)) if fib_618 > price else price + (1.6 * atr)
                tp = swing_low if swing_low < price * 0.98 else price - (2.6 * atr)

            return {
                "symbol": sym, "raw_symbol": sym, "is_btc": False,
                "direction": direction, "price": price, "sl": sl, "tp": tp,
                "score": score, "reasons": "<br>".join(reasons), "df_4h": df_4h,
                "fib_618": fib_618, "fib_382": fib_382, "swing_high": swing_high, "swing_low": swing_low,
                "rsi": float(a4h["rsi"]), "corr": corr, "beta": beta
            }
    except Exception:
        return None
    return None

@st.cache_data(ttl=300)
def scan_all_markets(overview):
    btc_4h = calc_indicators(fetch_spot_klines("BTCUSDT", "4h", 450))
    c4h = btc_4h.iloc[-1]
    btc_price = float(c4h["close"])
    btc_atr = float(c4h["atr"])

    fib_b = analyze_spot_swing_fib(btc_4h, "4시간봉")
    fib_618_b = fib_b["fib_618"]
    fib_382_b = fib_b["fib_382"]
    swing_high_b = fib_b["swing_high"]
    swing_low_b = fib_b["swing_low"]

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
        btc_reasons.append("• <b>4시간봉 현물 CVD:</b> 최근 24시간 시장가 매수 델타가 우세합니다.")
    else:
        short_score += 1
        btc_reasons.append("• <b>4시간봉 현물 CVD:</b> 최근 24시간 시장가 매도 출회 압력이 우세합니다.")

    if c4h["close"] > c4h["ema25"]:
        long_score += 1.5
        btc_reasons.append("• <b>4시간봉 EMA 추세:</b> EMA 25 상단 지지를 받으며 단기 상승 흐름을 유지 중입니다.")
    else:
        short_score += 1.5
        btc_reasons.append("• <b>4시간봉 EMA 추세:</b> EMA 25 저항 아래에서 조정 흐름이 진행 중입니다.")

    if abs(long_score - short_score) < 1.0:
        btc_dir = "SIDEWAYS"
        btc_sl = btc_price - (1.2 * btc_atr)
        btc_tp = btc_price + (1.8 * btc_atr)
        btc_reasons.append(f"• <b>피보나치 박스권:</b> 지지(<b>${fib_618_b:,.1f}</b>)와 저항(<b>${fib_382_b:,.1f}</b>) 사이 방향성 탐색 구간입니다.")
    elif long_score > short_score:
        btc_dir = "LONG"
        btc_sl = max(fib_618_b * 0.995, btc_price - (1.5 * btc_atr)) if fib_618_b < btc_price else btc_price - (1.5 * btc_atr)
        btc_tp = swing_high_b if swing_high_b > btc_price * 1.015 else btc_price + (2.5 * btc_atr)
        btc_reasons.append(f"• <b>피보나치 핵심 기준:</b> 지지 방어선 <b>${fib_618_b:,.1f}</b> / 상단 목표 <b>${btc_tp:,.1f}</b>")
    else:
        btc_dir = "SHORT"
        btc_sl = min(fib_618_b * 1.005, btc_price + (1.5 * btc_atr)) if fib_618_b > btc_price else btc_price + (1.5 * btc_atr)
        btc_tp = swing_low_b if swing_low_b < btc_price * 0.985 else btc_price - (2.5 * btc_atr)
        btc_reasons.append(f"• <b>피보나치 핵심 기준:</b> 저항 마지노선 <b>${fib_618_b:,.1f}</b> / 하단 목표 <b>${btc_tp:,.1f}</b>")

    btc_pick = {
        "symbol": "BTCUSDT (기준 대장주)", "raw_symbol": "BTCUSDT", "is_btc": True,
        "direction": btc_dir, "price": btc_price, "sl": btc_sl, "tp": btc_tp,
        "reasons": "<br>".join(btc_reasons), "df_4h": btc_4h,
        "fib_618": fib_618_b, "fib_382": fib_382_b, "swing_high": swing_high_b, "swing_low": swing_low_b,
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

# ================= 6. 실시간 경제 일정(발표치 판독) & 금·환율·속보 =================
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

# ================= 7. 보유 종목 1초 실시간 웹소켓 & 캘린더 & 종료 매매 자동 분석 =================
def render_live_positions_ws(pos_list):
    cards_html = ""
    for idx, p in enumerate(pos_list):
        sym = str(p.get("종목", ""))
        is_long = "롱" in str(p.get("포지션", ""))
        border_col = "#00D084" if is_long else "#FF4B4B"
        badge_bg = "rgba(0, 208, 132, 0.15)" if is_long else "rgba(255, 75, 75, 0.15)"
        badge_col = "#00D084" if is_long else "#FF4B4B"

        entry_p = float(pd.to_numeric(p.get("진입가", 0), errors="coerce") or 0)
        init_mark = float(pd.to_numeric(p.get("종료가", 0), errors="coerce") or 0)
        margin = float(pd.to_numeric(p.get("증거금", 0), errors="coerce") or 0)
        lev = int(float(pd.to_numeric(p.get("레버리지", 1), errors="coerce") or 1))
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
            <span style="background:{badge_bg}; color:{badge_col}; padding:3px 8px; border-radius:6px; font-weight:bold; font-size:12px;">{p.get('포지션', '')} · ● LIVE</span>
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
        entry_p = float(pd.to_numeric(p.get("진입가", 0), errors="coerce") or 0)
        margin = float(pd.to_numeric(p.get("증거금", 0), errors="coerce") or 0)
        lev = int(float(pd.to_numeric(p.get("레버리지", 1), errors="coerce") or 1))
        memo_parts = str(p.get("메모", "0|0")).split("|")
        qty = float(memo_parts[0]) if len(memo_parts) > 0 and memo_parts[0] else (margin * lev / entry_p if entry_p > 0 else 0)
        js_items.append({
            "idx": idx,
            "stream": f"{str(p.get('종목', '')).lower()}@markPrice@1s",
            "isLong": "롱" in str(p.get("포지션", "")),
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
    if not df_closed.empty and "_ymd" in df_closed.columns:
        for _, r in df_closed.iterrows():
            ymd = r["_ymd"]
            if ymd and ymd[0] == year and ymd[1] == month:
                d_num = ymd[2]
                prev_pnl, prev_cnt = daily_map.get(d_num, (0.0, 0))
                daily_map[d_num] = (prev_pnl + float(r["수익금"]), prev_cnt + 1)

    weekdays = ["일", "월", "화", "수", "목", "금", "토"]
    th_html = "".join([f"<th style='padding:6px; font-size:12px; color:#8B949E; text-align:center;'>{w}</th>" for w in weekdays])

    rows_html = ""
    for week in month_days:
        tds = ""
        for d in week:
            if d == 0:
                tds += "<td style='background:#0D1117; border:1px solid #21262D; height:60px;'></td>"
            else:
                if d in daily_map:
                    pnl_val, cnt = daily_map[d]
                    bg = "rgba(0, 208, 132, 0.16)" if pnl_val >= 0 else "rgba(255, 75, 75, 0.16)"
                    col = "#00D084" if pnl_val >= 0 else "#FF4B4B"
                    pnl_txt = f"{pnl_val:+.2f}$"
                    sub_txt = f"<div style='font-size:11px; font-weight:bold; color:{col}; margin-top:2px;'>{pnl_txt}</div><div style='font-size:10px; color:#8B949E;'>{cnt}건</div>"
                else:
                    bg = "#161B22"
                    sub_txt = "<div style='font-size:10px; color:#30363D; margin-top:6px;'>-</div>"
                tds += f"<td style='background:{bg}; border:1px solid #30363D; vertical-align:top; padding:4px; width:14.2%; height:60px; text-align:center;'><div style='font-size:11px; color:#C9D1D9; text-align:left;'>{d}</div>{sub_txt}</td>"
        rows_html += f"<tr>{tds}</tr>"

    cal_html = f"""
    <table style="width:100%; border-collapse:collapse; table-layout:fixed; border-radius:8px; overflow:hidden; margin-bottom:10px;">
      <thead><tr style="background:#161B22;">{th_html}</tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    """
    st.markdown(cal_html, unsafe_allow_html=True)

def diagnose_single_trade(row, wallet_bal):
    sym = str(row.get("종목", ""))
    pos = str(row.get("포지션", ""))
    margin = float(row.get("증거금", 0))
    lev = int(float(row.get("레버리지", 1)))
    pnl = float(row.get("수익금", 0))
    roi = float(row.get("수익률", 0))
    dt = str(row.get("일시", ""))

    reasons = []
    if pnl < 0:
        badge = f'<span class="badge-short">🔴 손실 복기 · {sym} {pos} (${pnl:+.2f} / {roi:+.1f}%)</span>'
        if lev >= 10 or roi <= -45:
            reasons.append(f"• <b>고배율 리스크({lev}배):</b> 배율이 높아 가격의 작은 역행에도 손실폭({roi:.1f}%)이 크게 확대되었습니다. 동일 종목 재진입 시 <b>5배 이하</b>로 낮추세요.")
        if wallet_bal > 0 and margin > wallet_bal * 0.35:
            ratio_pct = (margin / wallet_bal) * 100
            reasons.append(f"• <b>시드 비중 과다(잔고의 {ratio_pct:.0f}% 투입):</b> 1회 투입금이 커서 손실 타격이 컸습니다. 시드의 <b>20~25% 이내</b>로 분할 진입해야 복리가 유지됩니다.")
        if -45 < roi <= -15:
            reasons.append(f"• <b>손절 지연({roi:.1f}%):</b> 허용 손절폭(-10~15%)을 넘겨 손실을 키운 뒤 종료되었습니다. 진입 즉시 스탑로스(SL) 예약을 걸어두세요.")
        if not reasons:
            reasons.append(f"• <b>짧은 손절 방어({roi:.1f}%):</b> 손절폭 자체는 잘 끊어냈으나 횡보 구간 추격 또는 BTC 역행 타이밍에 진입했을 가능성이 높습니다. 4시간봉 EMA 방향과 일치하는 자리만 노리세요.")
    else:
        badge = f'<span class="badge-long">🟢 수익 복기 · {sym} {pos} (${pnl:+.2f} / {roi:+.1f}%)</span>'
        if roi < 8.0:
            reasons.append(f"• <b>조기 익절 패턴(+{roi:.1f}%):</b> 수익 확정은 좋으나 목표가 도달 전 일찍 종료한 편입니다. 50% 반익절 후 나머지 물량은 본절 스탑을 걸고 목표가까지 끌고 가면 복리 속도가 빨라집니다.")
        else:
            reasons.append(f"• <b>이상적 손익비(+{roi:.1f}% · {lev}배):</b> 진입 근거와 배율 조절이 안정적이었습니다. 이 패턴을 유지하세요.")

    return f"<div style='margin-bottom:8px;'>{badge} <span style='font-size:0.75rem; color:#8B949E;'>({dt})</span><div style='margin-top:4px;'>{'<br>'.join(reasons)}</div></div>"

def build_overall_habit_diagnosis(df_closed):
    if df_closed.empty:
        return ""
    wins_df = df_closed[df_closed["수익금"] > 0]
    loss_df = df_closed[df_closed["수익금"] < 0]

    avg_win = float(wins_df["수익금"].mean()) if not wins_df.empty else 0.0
    avg_loss = abs(float(loss_df["수익금"].mean())) if not loss_df.empty else 0.0

    long_df = df_closed[df_closed["포지션"].astype(str).str.contains("롱")]
    short_df = df_closed[df_closed["포지션"].astype(str).str.contains("숏")]
    long_wr = (long_df["수익금"] > 0).mean() * 100 if not long_df.empty else 0.0
    short_wr = (short_df["수익금"] > 0).mean() * 100 if not short_df.empty else 0.0

    notes = []
    if avg_loss > 0 and avg_win > 0 and avg_loss > avg_win * 1.2:
        notes.append(f"• <b>역손익비 주의:</b> 평균 익절(<b>+${avg_win:.2f}</b>)보다 평균 손절(<b>-${avg_loss:.2f}</b>)이 더 큽니다. 익절은 길게, 손절은 짧게 자르지 않으면 승률이 높아도 계좌가 제자리걸음을 합니다.")
    elif avg_win > 0:
        notes.append(f"• <b>양호한 손익비:</b> 평균 익절(<b>+${avg_win:.2f}</b>)이 평균 손절(<b>-${avg_loss:.2f}</b>)보다 크거나 잘 방어되고 있습니다.")

    if not long_df.empty and not short_df.empty:
        notes.append(f"• <b>방향별 승률 비교:</b> 롱 승률 <b>{long_wr:.0f}%</b> ({len(long_df)}건) vs 숏 승률 <b>{short_wr:.0f}%</b> ({len(short_df)}건) — 승률이 낮은 방향은 진입 기준을 한 단계 더 엄격하게 보세요.")

    return "<br>".join(notes)

# ================= 8. 실시간 자동 갱신 섹션(@st.fragment) =================
@st.fragment(run_every="120s")
def live_top_header_section():
    ov = get_market_overview()
    render_realtime_top_board(ov)

@st.fragment(run_every="60s")
def live_cvd_and_firechart_section():
    st.markdown("#### 📈 BTC 현물 누적 거래량 델타 (CVD · 4시간봉 40일치 · 1분 갱신)")
    try:
        btc_4h_df = calc_indicators(fetch_spot_klines("BTCUSDT", "4h", 360))
        render_tv_cvd_chart(btc_4h_df, "tv_btc_cvd", height=220)

        price_up = btc_4h_df["close"].iloc[-1] > btc_4h_df["close"].iloc[-6]
        cvd_up = btc_4h_df["cvd"].iloc[-1] > btc_4h_df["cvd"].iloc[-6]

        if price_up and cvd_up:
            cvd_badge = '<span class="badge-long">🟢 호재 (실매수 유입 동반 상승)</span>'
            cvd_desc = "4시간봉 현물 가격이 오르는 동안 실제 시장가 매수 체결(CVD)도 같이 늘어나고 있습니다. 현물 매수세가 뒷받침되는 건강한 상승입니다."
        elif (not price_up) and cvd_up:
            cvd_badge = '<span class="badge-long">🟢 반등 신호 (저점 매도 물량 흡수)</span>'
            cvd_desc = "가격은 눌렸지만 4시간봉 CVD는 오히려 버티거나 올라가고 있습니다. 현물 시장에서 매도 물량을 받아내고 있어 단기 반등 확률이 높습니다."
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
    acc_state = load_sheet_state()
    wallet_bal = acc_state["wallet_bal"]
    avail_bal = acc_state["avail_bal"]
    base_seed = max(10.0, round(wallet_bal, 2)) if wallet_bal > 0 else (max(10.0, round(avail_bal, 2)) if avail_bal > 0 else 100.0)

    saved_g = acc_state.get("saved_goal")
    if "goal_target" not in st.session_state:
        st.session_state["goal_target"] = saved_g["target"] if saved_g else round(base_seed * 2.0, 2)
    if "goal_days" not in st.session_state:
        st.session_state["goal_days"] = saved_g["days"] if saved_g else 30
    if "goal_ratio_idx" not in st.session_state:
        st.session_state["goal_ratio_idx"] = saved_g["ratio_idx"] if saved_g else 0

    st.markdown("#### 🎯 내 시드 · 복리 목표 연동 자동 세팅 (구글 시트 영구 저장)")
    g1, g2, g3 = st.columns(3)
    cur_seed_disp = g1.number_input("현재 총 시드 ($)", min_value=10.0, value=base_seed, step=10.0, key="rec_seed_in")
    target_goal = g2.number_input("목표 금액 ($)", min_value=cur_seed_disp + 5.0, value=max(cur_seed_disp + 5.0, float(st.session_state["goal_target"])), step=10.0, key="rec_target_in")
    target_days = g3.number_input("목표 기간 (일)", min_value=3, max_value=365, value=int(st.session_state["goal_days"]), step=5, key="rec_days_in")

    ratio_opts = ["시드 25% (권장)", "시드 50% (분할 2회)", "시드 100% (전액)"]
    saved_r_idx = min(2, max(0, int(st.session_state.get("goal_ratio_idx", 0))))
    ratio_choice = st.radio("💰 1회 진입 증거금 비중", ratio_opts, index=saved_r_idx, horizontal=True, key="rec_ratio_in")
    cur_r_idx = ratio_opts.index(ratio_choice)

    if (
        abs(target_goal - float(st.session_state["goal_target"])) > 0.001
        or target_days != int(st.session_state["goal_days"])
        or cur_r_idx != int(st.session_state["goal_ratio_idx"])
    ):
        save_goal_to_sheet(target_goal, target_days, cur_r_idx)

    growth_mult = target_goal / cur_seed_disp
    req_daily_pct = ((growth_mult ** (1.0 / target_days)) - 1.0) * 100.0
    daily_goal_usd = cur_seed_disp * (req_daily_pct / 100.0)

    if cur_r_idx == 0:
        entry_margin = round(cur_seed_disp * 0.25, 2)
    elif cur_r_idx == 1:
        entry_margin = round(cur_seed_disp * 0.50, 2)
    else:
        entry_margin = round(cur_seed_disp, 2)

    st.markdown(f"""
    <div class="metric-card" style="padding:10px 14px;">
        <div style="font-size:0.84rem; color:#F0F6FC;">
            오늘 목표 수익: <b style="color:#00D084;">+${daily_goal_usd:,.2f} (일 +{req_daily_pct:.2f}%)</b> &nbsp;|&nbsp;
            1회 진입 증거금: <b style="color:#58A6FF;">${entry_margin:,.2f}</b>
        </div>
        <div style="font-size:0.76rem; color:#8B949E; margin-top:3px;">
            목표 설정은 구글 시트에 자동 저장되어 앱을 껐다 켜도 그대로 유지됩니다.
        </div>
    </div>""", unsafe_allow_html=True)

    btc_pick, alt_picks = scan_all_markets(ov)
    all_picks = [btc_pick] + alt_picks

    for idx, p in enumerate(all_picks):
        is_long = p["direction"] == "LONG"
        is_short = p["direction"] == "SHORT"
        card_cls = "coin-card" if is_long else ("coin-card coin-card-short" if is_short else "coin-card coin-card-neutral")
        badge_cls = "badge-long" if is_long else ("badge-short" if is_short else "badge-neutral")
        label_txt = "롱 (매수) 추천" if is_long else ("숏 (매도) 추천" if is_short else "횡보 관망")

        adj = calc_goal_adjusted_leverage(p["price"], p["sl"], p["tp"], entry_margin, daily_goal_usd, p["beta"], p["is_btc"])
        rec_lev = adj["lev"]
        liq_price = p["price"] * (1 - (0.9 / rec_lev)) if is_long else p["price"] * (1 + (0.9 / rec_lev))

        corr_txt = "기준 대장주" if p["is_btc"] else (
            f"독자 행보 (디커플링 {p['corr']*100:.0f}%)" if p["corr"] < 0.35 else f"BTC 동조화 {p['corr']*100:.0f}% (변동성 {p['beta']:.1f}배)"
        )
        cap_note = f" (청산 방어를 위해 안전 상한 {adj['max_safe_lev']}배로 자동 제한됨)" if adj["capped"] else " (목표 수익 1회 달성 맞춤 배율)"

        st.markdown(f"""
        <div class="{card_cls}">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:1.08rem; font-weight:bold; color:#FFFFFF;">{p['symbol']}</span>
                <span class="{badge_cls}">{label_txt}</span>
            </div>
            <div style="font-size:0.78rem; color:#8B949E; margin-top:3px;">🕒 4시간봉(4H) 기준 · 🔗 {corr_txt} · RSI: {p['rsi']:.1f}</div>
            <div style="margin-top:8px; font-size:0.85rem; color:#8B949E;">
                진입가: <b style="color:#F0F6FC;">${p['price']:,.4f}</b> &nbsp;|&nbsp;
                손절가: <b style="color:#FF7B72;">${p['sl']:,.4f} (-{adj['sl_pct']:.1f}%)</b> &nbsp;|&nbsp;
                목표가: <b style="color:#7EE787;">${p['tp']:,.4f} (+{adj['tp_pct']:.1f}%)</b>
            </div>
            <div class="lev-box">
                ⚙️ <b>자동 조절 세팅: 증거금 ${entry_margin:,.2f} × {rec_lev}배</b>{cap_note}<br>
                🎯 목표가 익절 시: <b style="color:#7EE787;">+${adj['est_tp_profit']:,.2f}</b> (오늘 목표 달성까지 약 <b>{adj['trades_needed']}회</b> 성공 필요)<br>
                🛡️ 손절가 손실: <b style="color:#FF7B72;">-${adj['est_sl_loss']:,.2f}</b> · 예상 청산가: <b>${liq_price:,.4f}</b>
            </div>
            <div class="reason-box">
                <div style="font-weight:bold; color:#58A6FF; margin-bottom:4px;">💡 4시간봉 추세 & 피보나치 추천 근거</div>
                {p['reasons']}
            </div>
        </div>""", unsafe_allow_html=True)

        disp_df = p["df_4h"].tail(360)
        days_span = round(len(disp_df) / 6)
        with st.expander(f"🕯️ {p['raw_symbol']} · 4시간봉(4H) 1초 실시간 차트 + 보조지표 ({days_span}일치)"):
            chart_lines = [
                {"price": p["price"], "color": "#FFFFFF", "width": 1, "style": 0, "title": "진입가"},
                {"price": p["sl"], "color": "#FF4B4B", "width": 2, "style": 2, "title": "손절가"},
                {"price": p["tp"], "color": "#00D084", "width": 2, "style": 2, "title": "🎯 목표가"},
                {"price": p["fib_618"], "color": "#FFA657", "width": 1, "style": 2, "title": "Fib 0.618"},
                {"price": p["fib_382"], "color": "#58A6FF", "width": 1, "style": 3, "title": "Fib 0.382"}
            ]
            render_tv_pro_chart(
                disp_df,
                f"tv_pick_{idx}",
                watermark_text=f"{p['raw_symbol']} · 4H ({days_span}일)",
                price_lines=chart_lines,
                live_symbol=p["raw_symbol"],
                live_interval="4h",
                show_indicators=True,
                height=520
            )

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

@st.fragment(run_every="45s")
def live_trade_journal_section():
    acc_state = load_sheet_state()
    if not acc_state["has_url"]:
        st.warning("Streamlit Secrets에 SHEET_URL이 설정되지 않았습니다.")
        return

    if acc_state["error"]:
        st.warning(f"구글 시트 데이터 동기화 중입니다: {acc_state['error']}")

    wallet_bal = acc_state["wallet_bal"]
    avail_bal = acc_state["avail_bal"]
    used_margin = acc_state["used_margin"]
    cur_open_list = acc_state["open_list"]
    df_closed = acc_state["df_closed"]

    # --- [영역 A] 선물 계좌 총 증거금(시드) ---
    st.markdown("#### 💰 내 바이낸스 선물 증거금 총액")
    c1, c2, c3 = st.columns(3)
    c1.metric("총 지갑 잔고(시드)", f"${wallet_bal:,.2f}")
    c2.metric("포지션 투입 증거금", f"${used_margin:,.2f}")
    c3.metric("주문 가능 잔고", f"${avail_bal:,.2f}")

    # --- [영역 B] 현재 보유 중인 실시간 포지션 (1초 웹소켓 + 실시간 차트) ---
    st.markdown("#### 🟢 현재 보유 중인 실시간 포지션 (1초 실시간)")
    if cur_open_list:
        render_live_positions_ws(cur_open_list)
        for p_idx, p_item in enumerate(cur_open_list):
            p_sym = str(p_item.get("종목", "")).strip()
            if not p_sym:
                continue
            entry_p = float(pd.to_numeric(p_item.get("진입가", 0), errors="coerce") or 0)
            memo_parts = str(p_item.get("메모", "0|0")).split("|")
            liq_p = float(memo_parts[1]) if len(memo_parts) > 1 and memo_parts[1] else 0.0

            with st.expander(f"🕯️ 보유 중 · {p_sym} 4시간봉(4H) 1초 실시간 차트 & 보조지표 보기"):
                try:
                    pos_df = calc_indicators(fetch_spot_klines(p_sym, "4h", 360))
                    fib_pos = analyze_spot_swing_fib(pos_df, "4시간봉")
                    pos_lines = [
                        {"price": entry_p, "color": "#FFFFFF", "width": 2, "style": 0, "title": "내 진입가"},
                        {"price": fib_pos["fib_618"], "color": "#FFA657", "width": 1, "style": 2, "title": "Fib 0.618"}
                    ]
                    if liq_p > 0:
                        pos_lines.append({"price": liq_p, "color": "#FF4B4B", "width": 2, "style": 2, "title": "⚠️ 예상 청산가"})
                    render_tv_pro_chart(
                        pos_df,
                        f"tv_hold_{p_idx}_{p_sym}",
                        watermark_text=f"{p_sym} · 보유 중 (4H)",
                        price_lines=pos_lines,
                        live_symbol=p_sym,
                        live_interval="4h",
                        show_indicators=True,
                        height=500
                    )
                except Exception:
                    st.warning(f"{p_sym} 실시간 차트를 불러오는 중입니다.")
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

    total_pnl = 0.0
    recent_streak_pnl = 0.0
    if df_closed.empty:
        st.caption("아직 종료된 매매 기록이 없습니다. 보유 포지션을 익절·손절로 종료하면 캘린더와 아래 표에 즉시 반영됩니다.")
    else:
        total_pnl = float(df_closed["수익금"].sum())
        wins = int((df_closed["수익금"] > 0).sum())
        total_trades = len(df_closed)
        win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0
        recent_streak_pnl = float(df_closed["수익금"].tail(3).sum())

        m1, m2, m3 = st.columns(3)
        m1.metric("종료 매매", f"{total_trades}건")
        m2.metric("전체 승률", f"{win_rate:.1f}%", f"{wins}승 {total_trades-wins}패")
        m3.metric("누적 실현손익", f"${total_pnl:+,.2f}")

        date_options = ["전체 내역 보기"] + sorted(df_closed["_date_str"].unique().tolist(), reverse=True)
        sel_day = st.selectbox("🔍 날짜별 상세 필터", date_options)
        view_df = df_closed if sel_day == "전체 내역 보기" else df_closed[df_closed["_date_str"] == sel_day]

        display_cols = ["일시", "종목", "포지션", "증거금", "레버리지", "진입가", "종료가", "수익금", "수익률", "메모"]
        valid_cols = [c for c in display_cols if c in view_df.columns]
        st.dataframe(view_df[valid_cols].iloc[::-1], use_container_width=True, hide_index=True)

        # --- [영역 C-2] 매매 종료 자동 원인 진단 리포트 ---
        st.markdown("#### 🔍 종료 매매 자동 원인 분석 (AI 복기)")
        recent_rows = df_closed.iloc[::-1].head(4)
        diag_blocks = "".join([diagnose_single_trade(r, wallet_bal) for _, r in recent_rows.iterrows()])
        habit_summary = build_overall_habit_diagnosis(df_closed)

        st.markdown(f"""
        <div class="reason-box">
            {diag_blocks}
            <hr style="border-color:#21262D; margin:10px 0;">
            <div style="font-weight:bold; color:#58A6FF; margin-bottom:4px;">📊 전체 매매 습관 패턴 진단</div>
            <div>{habit_summary}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # --- [영역 D] 목표 기반 복리 플래너 & 손익 상황별 대응 대책 ---
    st.markdown("#### 🎯 복리 목표 플래너 & 상황별 대응 전략 (구글 시트 영구 저장)")
    default_seed = max(10.0, round(wallet_bal, 2)) if wallet_bal > 0 else 100.0
    saved_g = acc_state.get("saved_goal")
    if "goal_target" not in st.session_state:
        st.session_state["goal_target"] = saved_g["target"] if saved_g else round(default_seed * 2.0, 2)
    if "goal_days" not in st.session_state:
        st.session_state["goal_days"] = saved_g["days"] if saved_g else 30

    g1, g2, g3 = st.columns(3)
    start_seed = g1.number_input("시작 시드 ($)", min_value=10.0, value=default_seed, step=10.0, key="jr_seed_in")
    target_seed = g2.number_input("목표 금액 ($)", min_value=start_seed + 5.0, value=max(start_seed + 5.0, float(st.session_state["goal_target"])), step=10.0, key="jr_target_in")
    goal_days = g3.number_input("목표 기간 (일)", min_value=3, max_value=365, value=int(st.session_state["goal_days"]), step=5, key="jr_days_in")

    if abs(target_seed - float(st.session_state["goal_target"])) > 0.001 or goal_days != int(st.session_state["goal_days"]):
        save_goal_to_sheet(target_seed, goal_days, st.session_state.get("goal_ratio_idx", 0))

    growth_mult = target_seed / start_seed
    req_daily_rate = ((growth_mult ** (1.0 / goal_days)) - 1.0) * 100.0
    day1_profit_target = start_seed * (req_daily_rate / 100.0)

    k1, k2 = st.columns(2)
    k1.metric("하루 필요 복리 수익률", f"{req_daily_rate:.2f}% / 일", f"오늘 목표 +${day1_profit_target:,.2f}")
    k2.metric("목표 배수 / 총 필요 수익", f"{growth_mult:.2f}배", f"+${target_seed - start_seed:,.2f}")

    if req_daily_rate <= 2.5:
        plan_badge = '<span class="badge-long">🟢 현실적·안정 복리 플랜 (달성 가능성 높음)</span>'
        plan_advice = (
            f"하루 <b>{req_daily_rate:.2f}%</b> 복리는 무리한 고배율 없이도 충분히 달성 가능한 속도입니다. "
            f"<b>시드의 25%(${start_seed * 0.25:,.2f})</b>씩 3~5배 저배율로만 진입해 손절(-1.5%)은 작게 자르고, "
            f"확실한 4시간봉 추세 자리에서만 1일 1~2회 익절하는 전략이 가장 유리합니다."
        )
    elif req_daily_rate <= 6.0:
        plan_badge = '<span class="badge-neutral">🟡 공격적 복리 플랜 (철저한 손절 필수)</span>'
        plan_advice = (
            f"하루 <b>{req_daily_rate:.2f}%</b>를 복리로 쌓으려면 거래량 터지는 돌파·눌림목 1~2자리만 엄선해야 합니다. "
            f"목표 수익(+${day1_profit_target:,.2f}) 달성 시 당일 차트를 바로 닫는 '익절 후 퇴근' 규칙이 핵심입니다."
        )
    else:
        plan_badge = '<span class="badge-short">🔴 과욕 경계 (고배율 청산 위험 구간)</span>'
        plan_advice = (
            f"하루 <b>{req_daily_rate:.2f}%</b> 복리는 한 번의 반대 빔에 계좌가 초기화될 위험이 큽니다. "
            f"<b>목표 기간을 {int(np.ceil(np.log(growth_mult) / np.log(1.03)))}일 이상으로 늘리거나</b> 목표 금액을 낮춰 하루 2~3% 복리 속도로 조절하는 것을 권장합니다."
        )

    if recent_streak_pnl < 0:
        flow_title = f"🚨 최근 매매 손실(${recent_streak_pnl:,.2f}) 방어 대책 (손실 구간 대응)"
        loss_pct = min(90.0, abs(recent_streak_pnl) / max(start_seed, 1.0) * 100)
        recov_pct = (100.0 / max(100.0 - loss_pct, 10.0) - 1.0) * 100.0
        flow_advice = (
            f"• <b>본전 회복 착시 주의:</b> 시드가 {loss_pct:.1f}% 줄면 원금 복구에 <b>+{recov_pct:.1f}%</b> 수익이 필요합니다. 한 번에 만회하려고 배율을 올리면 청산으로 직결됩니다.<br>"
            f"• <b>비중 절반 축소 룰:</b> 다음 2~3번의 매매는 평소 투입금의 절반(<b>${start_seed * 0.12:,.2f}</b>)으로 줄여 감각부터 회복하세요.<br>"
            f"• <b>일일 손실 한도(-${start_seed * 0.05:,.2f}):</b> 하루 손실이 시드의 5%를 넘기면 당일 바이낸스 앱을 종료하고 다음 날 새 캔들에서 다시 시작하세요."
        )
    else:
        flow_title = "📈 수익 구간 복리 증액 & 원금 보호 대책 (벌고 있을 때 대응)"
        skim_target = start_seed * 1.5
        flow_advice = (
            f"• <b>복리 비중 자동 증액:</b> 잔고가 늘어날 때마다 1회 투입금도 현재 시드의 25%(<b>${start_seed * 0.25:,.2f}</b>) 비율로 함께 늘려야 복리 효과가 작동합니다.<br>"
            f"• <b>원금 회수 스키밍 (1차 목표 ${skim_target:,.2f}):</b> 시드가 현재 대비 +50%(<b>${skim_target:,.2f}</b>)에 도달하면 수익의 절반(<b>${start_seed * 0.25:,.2f}</b>)을 현물 지갑으로 출금해 원금을 먼저 회수하세요.<br>"
            f"• <b>연승 후 자만 경계:</b> 3연승 이상 직후에는 레버리지를 높이고 싶은 심리가 강해집니다. 수익이 날수록 배율은 5배 이하로 고정하세요."
        )

    st.markdown(f"""
    <div class="reason-box">
        {plan_badge}
        <div style="margin-top:6px;">{plan_advice}</div>
        <hr style="border-color:#21262D; margin:10px 0;">
        <div style="font-weight:bold; color:#FFA657; margin-bottom:4px;">{flow_title}</div>
        <div>{flow_advice}</div>
    </div>
    """, unsafe_allow_html=True)

# ================= 9. 메인 화면 렌더링 =================
st.markdown("### 📡 코인 선물 레이더")
st.caption("BTC 시세와 보유 포지션·차트·보조지표는 1초마다 실시간 반영되며, 목표 설정은 구글 시트에 자동 저장됩니다.")

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
            반감기 이후 12~18개월 사이 대형 고점을 형성한 뒤 약 1년간 거시 조정 파동이 진행됩니다. 청산 빔 왜곡이 없는 <b>현물(Spot) 차트 기준 스윙·피보나치 목표가</b>를 먼저 확인하세요.
        </div>
    </div>""", unsafe_allow_html=True)
    st.progress(progress)

    st.markdown("#### 🕯️ 비트코인 현물(Spot) 타임프레임별 피보나치 & 1초 실시간 차트")
    tf_configs = [
        ("1M", 120, "월봉(1M) 현물 · 10년치", "tv_btc_1m", "BTCUSDT · 1M 월봉 (10년)"),
        ("1w", 160, "주봉(1W) 현물 · 3년치", "tv_btc_1w", "BTCUSDT · 1W 주봉 (3년)"),
        ("1d", 365, "일봉(1D) 현물 · 1년치", "tv_btc_1d", "BTCUSDT · 1D 일봉 (1년)"),
        ("4h", 360, "4시간봉(4H) 현물 · 60일치", "tv_btc_4h", "BTCUSDT · 4H 4시간봉 (60일)")
    ]
    with ThreadPoolExecutor(max_workers=4) as ex:
        tf_dfs = list(ex.map(lambda cfg: fetch_spot_klines("BTCUSDT", cfg[0], cfg[1]), tf_configs))

    tf_tabs = st.tabs(["월봉 (1M)", "주봉 (1W)", "일봉 (1D)", "4시간봉 (4H)"])
    for t_tab, (interval, lim, label, cid, wm_txt), raw_df in zip(tf_tabs, tf_configs, tf_dfs):
        with t_tab:
            try:
                df_tf = calc_indicators(raw_df)
                fib_res = analyze_spot_swing_fib(df_tf, label)
                render_tv_pro_chart(
                    df_tf,
                    cid,
                    watermark_text=wm_txt,
                    price_lines=fib_res["chart_lines"],
                    live_symbol="BTCUSDT",
                    live_interval=interval,
                    show_indicators=True,
                    height=480
                )
                st.markdown(f'<div class="reason-box">{fib_res["html_desc"]}</div>', unsafe_allow_html=True)
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
