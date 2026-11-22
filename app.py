import streamlit as st
import streamlit.components.v1 as components
import requests
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
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
    .badge-long {
        background-color: rgba(0, 208, 132, 0.15); color: #00D084;
        padding: 3px 8px; border-radius: 6px; font-weight: bold; font-size: 0.8rem;
    }
    .badge-short {
        background-color: rgba(255, 75, 75, 0.15); color: #FF4B4B;
        padding: 3px 8px; border-radius: 6px; font-weight: bold; font-size: 0.8rem;
    }
    .reason-box {
        background-color: #0D1117; border-radius: 8px; padding: 10px;
        margin-top: 8px; font-size: 0.86rem; line-height: 1.55; color: #C9D1D9;
    }
</style>
""", unsafe_allow_html=True)

KST = timezone(timedelta(hours=9))

# ================= 1. 데이터 수집 함수 =================
@st.cache_data(ttl=300)
def get_market_overview():
    fng_val, fng_class, btc_dom, btc_price, funding_rate = "N/A", "N/A", "N/A", "N/A", "N/A"
    try:
        res = requests.get("https://api.alternative.me/fng/", timeout=5).json()
        fng_val = res["data"][0]["value"]
        fng_class = res["data"][0]["value_classification"]
    except Exception:
        pass
    try:
        res = requests.get("https://api.coingecko.com/api/v3/global", timeout=5).json()
        btc_dom = f"{res['data']['market_cap_percentage']['btc']:.1f}%"
    except Exception:
        pass
    try:
        res = requests.get("https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT", timeout=5).json()
        info = res["result"]["list"][0]
        btc_price = f"${float(info['lastPrice']):,.1f}"
        funding_rate = f"{float(info['fundingRate']) * 100:.4f}%"
    except Exception:
        pass
    return fng_val, fng_class, btc_dom, btc_price, funding_rate

def fetch_klines(symbol, interval, limit=120):
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    data = requests.get(url, timeout=5).json()
    df = pd.DataFrame(data, columns=[
        "time", "open", "high", "low", "close", "volume",
        "close_time", "qav", "num_trades", "taker_base_vol", "taker_quote_vol", "ignore"
    ])
    df["dt"] = pd.to_datetime(df["time"], unit="ms") + timedelta(hours=9)
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
def get_orderbook_heatmap(symbol="BTCUSDT"):
    url = f"https://data-api.binance.vision/api/v3/depth?symbol={symbol}&limit=500"
    depth = requests.get(url, timeout=5).json()
    bids = pd.DataFrame(depth["bids"], columns=["price", "qty"]).astype(float)
    asks = pd.DataFrame(depth["asks"], columns=["price", "qty"]).astype(float)
    bids["notional"] = bids["price"] * bids["qty"]
    asks["notional"] = asks["price"] * asks["qty"]
    all_df = pd.concat([bids, asks])
    all_df["bin"] = np.round(all_df["price"] / 250) * 250
    grouped = all_df.groupby("bin")["notional"].sum().reset_index()
    top_bid = bids.groupby(np.round(bids["price"] / 250) * 250)["notional"].sum().idxmax()
    top_ask = asks.groupby(np.round(asks["price"] / 250) * 250)["notional"].sum().idxmax()
    return grouped, top_bid, top_ask

@st.cache_data(ttl=600)
def scan_markets():
    tickers = requests.get("https://data-api.binance.vision/api/v3/ticker/24hr", timeout=5).json()
    usdt_pairs = [
        t for t in tickers
        if t["symbol"].endswith("USDT") and not any(x in t["symbol"] for x in ["UPUSDT", "DOWNUSDT", "USDC", "FDUSD"])
    ]
    top_symbols = sorted(usdt_pairs, key=lambda x: float(x["quoteVolume"]), reverse=True)[:25]
    picks = []
    for item in top_symbols:
        sym = item["symbol"]
        try:
            df_1d = calc_indicators(fetch_klines(sym, "1d", 110))
            df_4h = calc_indicators(fetch_klines(sym, "4h", 110))
            c1d, c4h, p4h = df_1d.iloc[-1], df_4h.iloc[-1], df_4h.iloc[-2]
            price, atr = c4h["close"], c4h["atr"]
            reasons, direction, score = [], None, 0

            recent = df_4h.tail(60)
            swing_high, swing_low = recent["high"].max(), recent["low"].min()
            fib_618 = swing_high - (swing_high - swing_low) * 0.618
            fib_382 = swing_high - (swing_high - swing_low) * 0.382

            if c1d["close"] > c1d["ema25"] and c1d["ema25"] > c1d["ema99"]:
                score += 2
                reasons.append("• **일봉(1D) 정배열 추세:** EMA 25·99 상단에서 중기 상승 파동이 유지되고 있습니다.")
                if c4h["ema7"] > c4h["ema25"] and 45 <= c4h["rsi"] <= 68:
                    score += 2
                    reasons.append(f"• **4시간봉(4H) 이평선 & RSI:** 단기 이평선 정배열 및 RSI({c4h['rsi']:.1f}) 건강한 매수 구간입니다.")
                if abs(price - fib_618) / price < 0.03 or price > fib_382:
                    score += 1
                    reasons.append(f"• **피보나치 지지 확인:** 주요 되돌림 구간(${fib_618:,.2f}~${fib_382:,.2f}) 위에서 지지를 받고 있습니다.")
                if c4h["hist"] > 0 and c4h["hist"] > p4h["hist"]:
                    score += 1
                    reasons.append("• **MACD & 거래량:** MACD 양봉 확장과 함께 매수 수급이 유입되고 있습니다.")
                if score >= 4:
                    direction = "LONG"

            elif c1d["close"] < c1d["ema25"] and c1d["ema25"] < c1d["ema99"]:
                score += 2
                reasons.append("• **일봉(1D) 역배열 하락 추세:** 주요 이평선 아래에서 거시 하락 압력이 우세합니다.")
                if c4h["ema7"] < c4h["ema25"] and 32 <= c4h["rsi"] <= 55:
                    score += 2
                    reasons.append(f"• **4시간봉(4H) 이평선 & RSI:** EMA 7 하향 이탈 및 RSI({c4h['rsi']:.1f}) 추가 하락 여력이 있습니다.")
                if c4h["hist"] < 0 and c4h["hist"] < p4h["hist"]:
                    score += 1
                    reasons.append("• **MACD 음봉 확대:** 반등 이후 매도 압력이 다시 강해지는 구간입니다.")
                if score >= 4:
                    direction = "SHORT"

            if direction:
                sl = price - (1.5 * atr) if direction == "LONG" else price + (1.5 * atr)
                tp = price + (2.5 * atr) if direction == "LONG" else price - (2.5 * atr)
                picks.append({
                    "symbol": sym, "direction": direction, "price": price,
                    "sl": sl, "tp": tp, "score": score, "reasons": "<br>".join(reasons),
                    "df_4h": df_4h
                })
        except Exception:
            continue
    return sorted(picks, key=lambda x: x["score"], reverse=True)[:5]

# ================= 2. 차트 그리기 함수 =================
def draw_detailed_chart(df, pick):
    sub = df.tail(65).copy().reset_index(drop=True)
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03,
        row_heights=[0.52, 0.14, 0.17, 0.17]
    )
    fig.add_trace(go.Candlestick(
        x=sub["dt"], open=sub["open"], high=sub["high"], low=sub["low"], close=sub["close"],
        increasing_line_color="#00D084", decreasing_line_color="#FF4B4B", name="가격"
    ), row=1, col=1)
    fig.add_trace(go.Scatter(x=sub["dt"], y=sub["ema7"], line=dict(color="#58A6FF", width=1.2), name="EMA 7"), row=1, col=1)
    fig.add_trace(go.Scatter(x=sub["dt"], y=sub["ema25"], line=dict(color="#F2CC60", width=1.4), name="EMA 25"), row=1, col=1)
    fig.add_trace(go.Scatter(x=sub["dt"], y=sub["ema99"], line=dict(color="#FF7B72", width=1.6), name="EMA 99"), row=1, col=1)

    hi, lo = sub["high"].max(), sub["low"].min()
    for ratio, color in [(0.382, "#7EE787"), (0.5, "#D2A8FF"), (0.618, "#FFA657")]:
        lvl = hi - (hi - lo) * ratio
        fig.add_hline(y=lvl, line_dash="dot", line_color=color, opacity=0.7,
                      annotation_text=f"Fib {ratio}", annotation_position="right", row=1, col=1)

    fig.add_hline(y=pick["price"], line_color="#FFFFFF", line_width=1, annotation_text="진입가", row=1, col=1)
    fig.add_hline(y=pick["sl"], line_dash="dash", line_color="#FF4B4B", annotation_text="손절가", row=1, col=1)
    fig.add_hline(y=pick["tp"], line_dash="dash", line_color="#00D084", annotation_text="목표가", row=1, col=1)

    pivots_x, pivots_y = [], []
    step = 10
    for i in range(0, len(sub), step):
        chunk = sub.iloc[i:i+step]
        if len(pivots_y) % 2 == 0:
            idx = chunk["low"].idxmin()
            pivots_y.append(sub.loc[idx, "low"])
        else:
            idx = chunk["high"].idxmax()
            pivots_y.append(sub.loc[idx, "high"])
        pivots_x.append(sub.loc[idx, "dt"])
    wave_names = ["1", "2", "3", "4", "5", "A", "B", "C"][:len(pivots_x)]
    fig.add_trace(go.Scatter(
        x=pivots_x, y=pivots_y, mode="lines+markers+text", text=wave_names,
        textposition="top center", line=dict(color="#E3B341", width=1.5, dash="dot"),
        textfont=dict(color="#E3B341", size=12), name="파동 흐름"
    ), row=1, col=1)

    vol_colors = ["#00D084" if c >= o else "#FF4B4B" for c, o in zip(sub["close"], sub["open"])]
    fig.add_trace(go.Bar(x=sub["dt"], y=sub["volume"], marker_color=vol_colors, name="거래량"), row=2, col=1)

    fig.add_trace(go.Scatter(x=sub["dt"], y=sub["rsi"], line=dict(color="#D2A8FF", width=1.5), name="RSI"), row=3, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="#FF4B4B", row=3, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#00D084", row=3, col=1)

    hist_colors = ["#00D084" if h >= 0 else "#FF4B4B" for h in sub["hist"]]
    fig.add_trace(go.Bar(x=sub["dt"], y=sub["hist"], marker_color=hist_colors, name="MACD Hist"), row=4, col=1)
    fig.add_trace(go.Scatter(x=sub["dt"], y=sub["macd"], line=dict(color="#58A6FF", width=1.2), name="MACD"), row=4, col=1)
    fig.add_trace(go.Scatter(x=sub["dt"], y=sub["signal"], line=dict(color="#FFA657", width=1.2), name="Signal"), row=4, col=1)

    fig.update_layout(
        template="plotly_dark", height=620, margin=dict(l=10, r=45, t=25, b=10),
        xaxis_rangeslider_visible=False, showlegend=False,
        paper_bgcolor="#0D1117", plot_bgcolor="#0D1117"
    )
    return fig

# ================= UI 메인 렌더링 =================
st.markdown("### 📡 코인 선물 레이더")
st.caption(f"업데이트: {datetime.now(KST).strftime('%Y-%m-%d %H:%M')} (KST)")

if st.button("🔄 실시간 데이터 새로고침", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

fng_val, fng_class, btc_dom, btc_price, funding_rate = get_market_overview()
c1, c2 = st.columns(2)
with c1:
    st.markdown(f"""
    <div class="metric-card">
        <div style="font-size:0.78rem; color:#8B949E;">BTC 현재가 / 펀딩비</div>
        <div style="font-size:1.1rem; font-weight:bold; color:#F0F6FC;">{btc_price}</div>
        <div style="font-size:0.8rem; color:#58A6FF;">펀딩비: {funding_rate}</div>
    </div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""
    <div class="metric-card">
        <div style="font-size:0.78rem; color:#8B949E;">공포·탐욕 / 도미넌스</div>
        <div style="font-size:1.1rem; font-weight:bold; color:#F0F6FC;">{fng_val} <span style="font-size:0.78rem;">({fng_class})</span></div>
        <div style="font-size:0.8rem; color:#D2A8FF;">도미넌스: {btc_dom}</div>
    </div>""", unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["📊 시장 브리핑", "🎯 추천 종목", "📅 경제 일정", "📝 매매일지"])

with tab1:
    halving_date = datetime(2024, 4, 20, tzinfo=KST)
    days_passed = (datetime.now(KST) - halving_date).days
    progress = min(days_passed / 1460, 1.0)
    st.markdown(f"""
    <div class="metric-card">
        <div style="font-weight:bold; color:#F0F6FC; margin-bottom:4px;">⏳ 비트코인 반감기 & 거시 싸이클</div>
        <div style="font-size:0.88rem; color:#FFA657;">4차 반감기 후 <b>{days_passed}일 경과</b> (거시 조정 파동 구간)</div>
        <div class="reason-box">
            • 역대 4년 주기상 반감기 후 12~18개월 고점 형성 뒤 약 1년간 거시 조정 구간이 진행됩니다.<br>
            • 현재는 추세 추종 고배율 롱보다 <b>주요 지지선 반등 및 저항선 숏 분할 대응</b>이 유리한 국면입니다.
        </div>
    </div>""", unsafe_allow_html=True)
    st.progress(progress)

    st.markdown("#### 📈 BTC 누적 거래량 델타 (CVD - 4시간봉)")
    try:
        btc_df = calc_indicators(fetch_klines("BTCUSDT", "4h", 80))
        fig_cvd = go.Figure()
        fig_cvd.add_trace(go.Scatter(
            x=btc_df["dt"], y=btc_df["cvd"], fill="tozeroy",
            line=dict(color="#00D084", width=2), name="CVD"
        ))
        fig_cvd.update_layout(
            template="plotly_dark", height=230, margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="#161B22", plot_bgcolor="#161B22"
        )
        st.plotly_chart(fig_cvd, use_container_width=True)
        cvd_trend = "매수세 유입 우세 (상방 지지)" if btc_df["cvd"].iloc[-1] > btc_df["cvd"].iloc[-6] else "매도세 출회 우세 (하방 압력)"
        st.caption(f"💡 최근 24시간 수급 해석: **{cvd_trend}**")
    except Exception:
        st.warning("CVD 데이터를 불러오는 중입니다.")

    st.markdown("#### 🔥 파이어차트 (실시간 호가창 유동성 매물대)")
    try:
        grouped, top_bid, top_ask = get_orderbook_heatmap("BTCUSDT")
        fig_fire = go.Figure(go.Bar(
            x=grouped["notional"], y=grouped["bin"], orientation="h",
            marker=dict(color=grouped["notional"], colorscale="Hot")
        ))
        fig_fire.update_layout(
            template="plotly_dark", height=260, margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="#161B22", plot_bgcolor="#161B22",
            xaxis_title="매물 규모 (USDT)", yaxis_title="가격대 ($)"
        )
        st.plotly_chart(fig_fire, use_container_width=True)
        st.markdown(f"""
        <div class="reason-box">
            • <b>상단 저항/청산 매물벽:</b> <span style="color:#FF7B72;">${top_ask:,.0f}</span><br>
            • <b>하단 지지/매수 매물벽:</b> <span style="color:#7EE787;">${top_bid:,.0f}</span>
        </div>""", unsafe_allow_html=True)
    except Exception:
        st.warning("호가창 유동성 데이터를 불러오는 중입니다.")

with tab2:
    st.markdown("#### 오늘의 기술적 타점 포착 종목")
    with st.spinner("실시간 차트 및 파동·이평선 스캔 중..."):
        picks = scan_markets()

    if not picks:
        st.info("현재 일봉 추세와 4시간봉 타점이 동시에 일치하는 고확률 자리가 없습니다. 관망을 권장합니다.")
    else:
        for p in picks:
            is_long = p["direction"] == "LONG"
            card_cls = "coin-card" if is_long else "coin-card coin-card-short"
            badge_cls = "badge-long" if is_long else "badge-short"
            label_txt = "롱 (매수) 추천" if is_long else "숏 (매도) 추천"
            st.markdown(f"""
            <div class="{card_cls}">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:1.1rem; font-weight:bold; color:#FFFFFF;">{p['symbol']}</span>
                    <span class="{badge_cls}">{label_txt}</span>
                </div>
                <div style="margin-top:8px; font-size:0.85rem; color:#8B949E;">
                    진입가: <b style="color:#F0F6FC;">${p['price']:,.4f}</b> &nbsp;|&nbsp;
                    손절가: <b style="color:#FF7B72;">${p['sl']:,.4f}</b> &nbsp;|&nbsp;
                    목표가: <b style="color:#7EE787;">${p['tp']:,.4f}</b>
                </div>
                <div class="reason-box">
                    <div style="font-weight:bold; color:#58A6FF; margin-bottom:4px;">💡 추천 근거 분석</div>
                    {p['reasons']}
                </div>
            </div>""", unsafe_allow_html=True)

            with st.expander(f"📊 {p['symbol']} 상세 차트 보기 (파동·피보나치·EMA·RSI·MACD)"):
                st.plotly_chart(draw_detailed_chart(p["df_4h"], p), use_container_width=True)

with tab3:
    st.markdown("#### 미국 주요 경제지표 발표 일정 (KST)")
    st.caption("FOMC, CPI, 고용지표 발표 전후 1시간은 변동성 주의 구간입니다.")
    components.html("""
    <div class="tradingview-widget-container">
      <div class="tradingview-widget-container__widget"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-events.js" async>
      { "colorTheme": "dark", "isTransparent": false, "width": "100%", "height": "520", "locale": "kr", "importanceFilter": "0,1", "countryFilter": "us" }
      </script>
    </div>""", height=540)

with tab4:
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
            ["AI추천종목", "엘리어트파동", "피보나치", "EMA이평선", "RSI", "MACD", "CVD/수급", "직접판단"]
        )
        memo_in = st.text_input("복기 메모", placeholder="예: 피보나치 0.618 지지 반등 성공")
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
                for tag in ["AI추천종목", "엘리어트파동", "피보나치", "EMA이평선", "RSI", "MACD", "CVD/수급", "직접판단"]:
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
