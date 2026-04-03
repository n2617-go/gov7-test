import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import json
import os
from ta.trend import SMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands

# --- 1. 核心資料存取邏輯 ---
SAVE_FILE = "user_stocks_v7.json"

def load_data():
    """讀取設定檔，若失敗則回傳預設值"""
    default = {"stocks": [{"id": "2330", "name": "台積電"}], "tg_token": "", "tg_chat_id": "", "tg_threshold": 3.0}
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                content = json.load(f)
                if content and "stocks" in content:
                    return content
        except: pass
    return default

def save_data():
    """將目前的 Session State 存入檔案"""
    if 'my_stocks' in st.session_state:
        data = {
            "stocks": st.session_state.my_stocks,
            "tg_token": st.session_state.tg_token,
            "tg_chat_id": st.session_state.tg_chat_id,
            "tg_threshold": st.session_state.tg_threshold
        }
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

# --- 2. 【關鍵】立即初始化所有變數 ---
# 放在所有邏輯之前，防止 AttributeError
conf = load_data()
if 'my_stocks' not in st.session_state:
    st.session_state.my_stocks = conf["stocks"]
if 'tg_token' not in st.session_state:
    st.session_state.tg_token = conf["tg_token"]
if 'tg_chat_id' not in st.session_state:
    st.session_state.tg_chat_id = conf["tg_chat_id"]
if 'tg_threshold' not in st.session_state:
    st.session_state.tg_threshold = conf["tg_threshold"]

# --- 3. 分析引擎 (回歸 V7.1 並加入指標清單回傳) ---
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
    
    # 處理資料格式
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.astype(float).ffill()
    
    try:
        close = pd.Series(df['Close'].values.flatten(), index=df.index)
        high = pd.Series(df['High'].values.flatten(), index=df.index)
        low = pd.Series(df['Low'].values.flatten(), index=df.index)
        
        # 指標計算
        m1 = SMAIndicator(close, 5).sma_indicator().iloc[-1] > SMAIndicator(close, 10).sma_indicator().iloc[-1] > SMAIndicator(close, 20).sma_indicator().iloc[-1]
        stoch = StochasticOscillator(high, low, close, 9)
        m2 = stoch.stoch().iloc[-1] > stoch.stoch_signal().iloc[-1] and stoch.stoch().iloc[-1] > 20
        m3 = MACD(close).macd_diff().iloc[-1] > 0
        m4 = RSIIndicator(close).rsi().iloc[-1] > 50
        m5 = close.iloc[-1] > BollingerBands(close).bollinger_mavg().iloc[-1]
        
        # 整理指標清單
        details = []
        if m1: details.append("✅均線多頭")
        if m2: details.append("✅KD金叉")
        if m3: details.append("✅MACD轉正")
        if m4: details.append("✅RSI強勢")
        if m5: details.append("✅站穩月線")
        
        score = sum([m1, m2, m3, m4, m5])
        d_map = {5:("S","🔥續抱","red"), 4:("A","🚀偏多","orange"), 3:("B","📈轉強","green"), 
                 2:("C","⚖️觀望","blue"), 1:("D","📉避險","gray"), 0:("E","🚫空方","black")}
        grade, action, color = d_map.get(score, ("?","?","black"))
        
        return {"price": float(close.iloc[-1]), "pct": (float(close.iloc[-1])-float(close.iloc[-2]))/float(close.iloc[-2])*100,
                "grade": grade, "action": action, "color": color, "details": details}
    except: return None

# --- 4. 介面設計 ---
st.set_page_config(page_title="台股監控 V7.1.1", layout="centered")
st.title("📈 台股 AI 技術分級監控")

# 新增股票
with st.container(border=True):
    st.subheader("🔍 新增股票")
    c1, c2, c3 = st.columns([2, 3, 1.2])
    add_id = c1.text_input("代號", key="new_id")
    add_name = c2.text_input("名稱", key="new_name")
    if c3.button("➕ 新增", use_container_width=True):
        if add_id and add_name:
            st.session_state.my_stocks.append({"id": add_id, "name": add_name})
            save_data()
            st.rerun()

# --- 5. 顯示清單 ---
st.divider()

# 防禦性檢查：確保變數存在才執行迴圈
if 'my_stocks' in st.session_state:
    for idx, s in enumerate(st.session_state.my_stocks):
        res = fetch_and_analyze(s['id'])
        if res:
            with st.container(border=True):
                col_i, col_m, col_d = st.columns([3, 2, 0.6])
                with col_i:
                    st.write(f"### {s['name']} ({s['id']})")
                    st.markdown(f"評級：`{res['grade']}` | **建議：<span style='color:{res['color']}'>{res['action']}</span>**", unsafe_allow_html=True)
                    # 網頁即時顯示指標
                    st.write(f"📊 {' '.join(res['details']) if res['details'] else '無符合指標'}")
                with col_m:
                    st.metric("股價", f"{res['price']:.2f}", f"{res['pct']:+.2f}%", delta_color="inverse")
                with col_d:
                    if st.button("🗑️", key=f"del_{s['id']}"):
                        st.session_state.my_stocks.pop(idx)
                        save_data()
                        st.rerun()

# 側邊欄
with st.sidebar:
    st.header("⚙️ 系統設定")
    st.session_state.tg_token = st.text_input("Bot Token", value=st.session_state.tg_token, type="password")
    st.session_state.tg_chat_id = st.text_input("Chat ID", value=st.session_state.tg_chat_id)
    st.session_state.tg_threshold = st.number_input("通知門檻 (%)", value=st.session_state.tg_threshold)
    if st.button("💾 儲存設定並刷新", use_container_width=True):
        save_data()
        st.cache_data.clear()
        st.rerun()
