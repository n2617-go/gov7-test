import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import json
import os
import time
import random
from datetime import datetime
from ta.trend import SMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands

# --- 1. 核心資料存取 ---
SAVE_FILE = "user_stocks_v7.json"

def load_data():
    default = {"stocks": [{"id": "2330", "name": "台積電"}], "tg_token": "", "tg_chat_id": "", "tg_threshold": 3.0}
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return default

def save_data():
    data = {
        "stocks": st.session_state.get('my_stocks', []),
        "tg_token": st.session_state.get('tg_token', ""),
        "tg_chat_id": st.session_state.get('tg_chat_id', ""),
        "tg_threshold": st.session_state.get('tg_threshold', 3.0)
    }
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

if 'my_stocks' not in st.session_state:
    conf = load_data()
    st.session_state.update(conf)

# --- 2. 核心分析引擎 (休盤優化版) ---
@st.cache_data(ttl=600) # 休盤期間資料不變，快取拉長到 10 分鐘避免重複請求
def fetch_offmarket_data(stock_id):
    # 【防封鎖機制】：隨機長延遲
    time.sleep(random.uniform(2.0, 4.5))
    
    df = pd.DataFrame()
    # 嘗試不同的後綴
    for suffix in [".TW", ".TWO"]:
        try:
            # 偽裝瀏覽器 Header (部分繞過 yfinance 限制)
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            ticker = yf.Ticker(f"{stock_id}{suffix}")
            # 使用 history 而非 download，並限制抓取欄位
            df = ticker.history(period="8m", interval="1d")
            
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                break
        except Exception:
            continue

    if df.empty:
        return None

    try:
        # 資料清理
        df_num = df[['Open', 'High', 'Low', 'Close']].copy().astype(float).ffill()
        if len(df_num) < 30: return None

        close, high, low = df_num['Close'], df_num['High'], df_num['Low']

        # 技術指標計算
        m1 = SMAIndicator(close, 5).sma_indicator().iloc[-1] > SMAIndicator(close, 10).sma_indicator().iloc[-1] > SMAIndicator(close, 20).sma_indicator().iloc[-1]
        stoch = StochasticOscillator(high, low, close, 9)
        m2 = stoch.stoch().iloc[-1] > stoch.stoch_signal().iloc[-1] and stoch.stoch().iloc[-1] > 20
        m3 = MACD(close).macd_diff().iloc[-1] > 0
        m4 = RSIIndicator(close).rsi().iloc[-1] > 50
        m5 = close.iloc[-1] > BollingerBands(close).bollinger_mavg().iloc[-1]
        
        details = []
        if m1: details.append("✅均線多頭")
        if m2: details.append("✅KD金叉")
        if m3: details.append("✅MACD轉正")
        if m4: details.append("✅RSI強勢")
        if m5: details.append("✅站穩月線")
        
        score = sum([m1, m2, m3, m4, m5])
        d_map = {5:("S","🔥續抱/加碼","red"), 4:("A","🚀偏多持股","orange"), 3:("B","📈轉強試單","green"), 
                 2:("C","⚖️暫時觀望","blue"), 1:("D","📉減碼避險","gray"), 0:("E","🚫觀望不進場","black")}
        grade, action, color = d_map.get(score, ("?","?","black"))
        
        return {
            "price": float(close.iloc[-1]), 
            "pct": (float(close.iloc[-1])-float(close.iloc[-2]))/float(close.iloc[-2])*100,
            "grade": grade, "action": action, "color": color, "details": details
        }
    except Exception:
        return None

# --- 3. UI 介面 ---
st.set_page_config(page_title="台股監控 V7.1.7", layout="centered")
st.title("📈 台股 AI 監控 (休盤穩定版)")

# 管理區
with st.container(border=True):
    c1, c2, c3 = st.columns([2, 3, 1.2])
    in_id = c1.text_input("代號", placeholder="1773", key="ui_id")
    in_name = c2.text_input("名稱", placeholder="勝一", key="ui_name")
    if c3.button("➕ 新增", use_container_width=True):
        if in_id and in_name:
            st.session_state.my_stocks.append({"id": in_id, "name": in_name})
            save_data(); st.rerun()

# 顯示清單
st.divider()
for idx, s in enumerate(st.session_state.my_stocks):
    res = fetch_offmarket_data(s['id'])
    if res:
        with st.container(border=True):
            col_i, col_m, col_d = st.columns([3, 2, 0.6])
            with col_i:
                st.write(f"### {s['name']} ({s['id']})")
                st.markdown(f"評級：`{res['grade']}` | **建議：<span style='color:{res['color']}'>{res['action']}</span>**", unsafe_allow_html=True)
                st.write(f"📊 {' '.join(res['details']) if res['details'] else '無指標符合'}")
            with col_m:
                st.metric("收盤價", f"{res['price']:.2f}", f"{res['pct']:+.2f}%", delta_color="inverse")
            with col_d:
                if st.button("🗑️", key=f"del_{idx}"):
                    st.session_state.my_stocks.pop(idx); save_data(); st.rerun()
    else:
        st.error(f"❌ {s['name']} ({s['id']}) 抓取失敗。原因：yfinance 頻率限制。請稍候 5 分鐘再試。")

with st.sidebar:
    if st.button("🔄 強制刷新 (慎用)"):
        st.cache_data.clear(); st.rerun()
