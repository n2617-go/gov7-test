import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import json
import os
from ta.trend import SMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands

# --- 1. 核心資料存取 (V7.1 原始邏輯，絕不更動) ---
SAVE_FILE = "user_stocks_v7.json"

def load_data():
    default_data = {"stocks": [{"id": "2330", "name": "台積電"}], "tg_token": "", "tg_chat_id": "", "tg_threshold": 3.0}
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return default_data

def save_data():
    data = {"stocks": st.session_state.my_stocks, "tg_token": st.session_state.tg_token, "tg_chat_id": st.session_state.tg_chat_id, "tg_threshold": st.session_state.tg_threshold}
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

if 'my_stocks' not in st.session_state:
    config = load_data()
    st.session_state.my_stocks = config["stocks"]
    st.session_state.tg_token = config["tg_token"]
    st.session_state.tg_chat_id = config["tg_chat_id"]
    st.session_state.tg_threshold = config["tg_threshold"]

# --- 2. 分析引擎 (回歸 V7.1 最原始狀態) ---
@st.cache_data(ttl=60)
def fetch_and_analyze(stock_id):
    df = pd.DataFrame()
    for suffix in [".TW", ".TWO"]:
        try:
            temp_df = yf.download(f"{stock_id}{suffix}", period="6mo", progress=False)
            if not temp_df.empty:
                df = temp_df
                break
        except: continue
    if df.empty: return None
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    df = df.astype(float).ffill()
    return df # 直接回傳整個 DataFrame，讓網頁端自己算指標

# --- 3. 介面設計 ---
st.set_page_config(page_title="台股監控 V7.1 修復版", layout="centered")
st.title("📈 台股 AI 技術分級監控")

# 新增股票
with st.container(border=True):
    st.subheader("🔍 新增自選股")
    c1, c2, c3 = st.columns([2, 3, 1.2])
    add_id = c1.text_input("代號", key="in_id")
    add_name = c2.text_input("名稱", key="in_name")
    if c3.button("➕ 新增", use_container_width=True):
        if add_id and add_name:
            st.session_state.my_stocks.append({"id": add_id, "name": add_name})
            save_data(); st.rerun()

# 側邊欄
with st.sidebar:
    st.header("⚙️ 系統設定")
    st.session_state.tg_token = st.text_input("Bot Token", value=st.session_state.tg_token, type="password")
    st.session_state.tg_chat_id = st.text_input("Chat ID", value=st.session_state.tg_chat_id)
    st.session_state.tg_threshold = st.number_input("通知門檻 (%)", value=st.session_state.tg_threshold)
    if st.button("💾 儲存所有設定"):
        save_data(); st.success("已存檔")

# --- 4. 顯示清單 (在這裡進行即時計算) ---
st.divider()
for idx, s in enumerate(st.session_state.my_stocks):
    df = fetch_and_analyze(s['id'])
    if df is not None:
        # --- 原位計算技術指標 ---
        close = pd.Series(df['Close'].values.flatten(), index=df.index)
        ma5 = SMAIndicator(close, window=5).sma_indicator().iloc[-1]
        ma10 = SMAIndicator(close, window=10).sma_indicator().iloc[-1]
        ma20 = SMAIndicator(close, window=20).sma_indicator().iloc[-1]
        stoch = StochasticOscillator(df['High'], df['Low'], close, window=9)
        last_k, last_d = stoch.stoch().iloc[-1], stoch.stoch_signal().iloc[-1]
        last_macd = MACD(close).macd_diff().iloc[-1]
        last_rsi = RSIIndicator(close).rsi().iloc[-1]
        last_bbm = BollingerBands(close).bollinger_mavg().iloc[-1]
        last_price = close.iloc[-1]
        prev_price = close.iloc[-2]
        pct = (last_price - prev_price) / prev_price * 100

        # 判定
        details = []
        if ma5 > ma10 > ma20: details.append("✅均線多頭")
        if last_k > last_d and last_k > 20: details.append("✅KD金叉")
        if last_macd > 0: details.append("✅MACD轉正")
        if last_rsi > 50: details.append("✅RSI強勢")
        if last_price > last_bbm: details.append("✅站穩月線")
        
        score = len(details)
        decision_map = {5:("S","🔥續抱","red"), 4:("A","🚀偏多","orange"), 3:("B","📈轉強","green"), 
                        2:("C","⚖️觀望","blue"), 1:("D","📉避險","gray"), 0:("E","🚫空方","black")}
        grade, action, color = decision_map.get(score, ("?","?","black"))

        # 渲染畫面
        with st.container(border=True):
            c_info, c_metric, c_del = st.columns([3, 2, 0.6])
            with c_info:
                st.write(f"### {s['name']} ({s['id']})")
                st.markdown(f"評級：`{grade}` | **建議：<span style='color:{color}'>{action}</span>**", unsafe_allow_html=True)
                st.write(f"📊 {' '.join(details) if details else '無指標符合'}")
            with c_metric:
                st.metric("股價", f"{last_price:.2f}", f"{pct:+.2f}%", delta_color="inverse")
            with c_del:
                if st.button("🗑️", key=f"del_{s['id']}"):
                    st.session_state.my_stocks.pop(idx); save_data(); st.rerun()

if st.button("🔄 刷新全部數據"):
    st.cache_data.clear(); st.rerun()
