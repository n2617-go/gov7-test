import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import json
import os
from ta.trend import SMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands

# --- 1. 核心資料存取 ---
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
    # 確保儲存時不會因為變數不存在而崩潰
    if 'my_stocks' in st.session_state:
        data = {
            "stocks": st.session_state.my_stocks,
            "tg_token": st.session_state.tg_token,
            "tg_chat_id": st.session_state.tg_chat_id,
            "tg_threshold": st.session_state.tg_threshold
        }
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

# --- 2. 【關鍵修復】初始化 Session State ---
# 確保在任何 UI 渲染前，所有變數都已存在
config = load_data()
if 'my_stocks' not in st.session_state:
    st.session_state['my_stocks'] = config.get("stocks", [{"id": "2330", "name": "台積電"}])
if 'tg_token' not in st.session_state:
    st.session_state['tg_token'] = config.get("tg_token", "")
if 'tg_chat_id' not in st.session_state:
    st.session_state['tg_chat_id'] = config.get("tg_chat_id", "")
if 'tg_threshold' not in st.session_state:
    st.session_state['tg_threshold'] = config.get("tg_threshold", 3.0)

# --- 3. 分析引擎 (含資料轉換修復) ---
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
    
    # 處理 yfinance 可能產生的 MultiIndex 格式
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    df = df.astype(float).ffill()
    
    # 強制拍平成一維數列，防止技術指標計算錯誤
    try:
        close = pd.Series(df['Close'].values.flatten(), index=df.index)
        high = pd.Series(df['High'].values.flatten(), index=df.index)
        low = pd.Series(df['Low'].values.flatten(), index=df.index)
        
        ma5 = SMAIndicator(close, window=5).sma_indicator().iloc[-1]
        ma10 = SMAIndicator(close, window=10).sma_indicator().iloc[-1]
        ma20 = SMAIndicator(close, window=20).sma_indicator().iloc[-1]
        
        stoch = StochasticOscillator(high, low, close, window=9)
        lk, ld = stoch.stoch().iloc[-1], stoch.stoch_signal().iloc[-1]
        
        macd_val = MACD(close).macd_diff().iloc[-1]
        rsi_val = RSIIndicator(close).rsi().iloc[-1]
        bbm_val = BollingerBands(close).bollinger_mavg().iloc[-1]
        
        # 指標判定清單
        active_m = []
        if ma5 > ma10 > ma20: active_m.append("✅均線多頭")
        if lk > ld and lk > 20: active_m.append("✅KD金叉")
        if macd_val > 0: active_m.append("✅MACD轉正")
        if rsi_val > 50: active_m.append("✅RSI強勢")
        if close.iloc[-1] > bbm_val: active_m.append("✅站穩月線")
        
        score = len(active_m)
        d_map = {5:("S","🔥續抱","red"), 4:("A","🚀偏多","orange"), 3:("B","📈轉強","green"), 
                 2:("C","⚖️觀望","blue"), 1:("D","📉避險","gray"), 0:("E","🚫空方","black")}
        grade, action, color = d_map.get(score, ("?","?","black"))

        return {
            "price": float(close.iloc[-1]),
            "pct": (float(close.iloc[-1]) - float(close.iloc[-2])) / float(close.iloc[-2]) * 100,
            "grade": grade, "action": action, "color": color, "details": active_m
        }
    except:
        return None

# --- 4. 介面設計 ---
st.set_page_config(page_title="台股監控 V7.1 Final", layout="centered")
st.title("📈 台股 AI 技術分級監控")

# 新增股票介面
with st.container(border=True):
    st.subheader("🔍 新增自選股")
    c1, c2, c3 = st.columns([2, 3, 1.2])
    in_id = c1.text_input("代號", key="input_id_field")
    in_name = c2.text_input("名稱", key="input_name_field")
    if c3.button("➕ 新增", use_container_width=True):
        if in_id and in_name:
            st.session_state.my_stocks.append({"id": in_id, "name": in_name})
            save_data()
            st.rerun()

# --- 5. 顯示清單 ---
st.divider()

# 防禦性檢查：若變數不存在則跳過顯示，避免整頁崩潰
if 'my_stocks' in st.session_state:
    for idx, s in enumerate(st.session_state.my_stocks):
        res = fetch_and_analyze(s['id'])
        if res:
            with st.container(border=True):
                col_i, col_m, col_d = st.columns([3, 2, 0.6])
                with col_i:
                    st.write(f"### {s['name']} ({s['id']})")
                    st.markdown(f"評級：`{res['grade']}` | **建議：<span style='color:{res['color']}'>{res['action']}</span>**", unsafe_allow_html=True)
                    st.write(f"📊 {' '.join(res['details']) if res['details'] else '無指標符合'}")
                with col_m:
                    st.metric("股價", f"{res['price']:.2f}", f"{res['pct']:+.2f}%", delta_color="inverse")
                with col_d:
                    if st.button("🗑️", key=f"del_btn_{s['id']}"):
                        st.session_state.my_stocks.pop(idx)
                        save_data()
                        st.rerun()

# 側邊欄
with st.sidebar:
    st.header("⚙️ 系統設定")
    st.session_state.tg_token = st.text_input("Bot Token", value=st.session_state.tg_token, type="password")
    st.session_state.tg_chat_id = st.text_input("Chat ID", value=st.session_state.tg_chat_id)
    st.session_state.tg_threshold = st.number_input("通知門檻 (%)", value=st.session_state.tg_threshold)
    if st.button("💾 儲存並刷新"):
        save_data()
        st.cache_data.clear()
        st.rerun()
