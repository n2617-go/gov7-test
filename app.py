import streamlit as st
import pandas as pd
import yfinance as yf
from FinMind.data import DataLoader
import requests
import json
import os
import time
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
    if 'my_stocks' in st.session_state:
        data = {"stocks": st.session_state.my_stocks, "tg_token": st.session_state.tg_token, 
                "tg_chat_id": st.session_state.tg_chat_id, "tg_threshold": st.session_state.tg_threshold}
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

# 初始化 Session State (防禦性確保)
conf = load_data()
for key in ['my_stocks', 'tg_token', 'tg_chat_id', 'tg_threshold']:
    if key not in st.session_state:
        st.session_state[key] = conf.get(key, conf["stocks"] if key == 'my_stocks' else "")

# --- 2. 智慧雙引擎分析 (修復轉型錯誤) ---
@st.cache_data(ttl=300)
def fetch_smart_data(stock_id):
    now = datetime.now()
    # 判斷開盤時間 (週一至五 09:00 - 13:35)
    is_open = now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) <= (13, 35)
    
    df = pd.DataFrame()
    source_label = ""

    # 盤中嘗試使用 FinMind
    if is_open:
        source_label = "FinMind (即時)"
        try:
            dl = DataLoader()
            df = dl.taiwan_stock_daily(stock_id=stock_id, start_date='2025-01-01')
            if not df.empty:
                df = df.rename(columns={'close': 'Close', 'high': 'High', 'low': 'Low', 'open': 'Open'})
        except: pass
    
    # 休盤或失敗則用 yfinance
    if df.empty:
        source_label = "yfinance (盤後/延遲)"
        time.sleep(1.2) # 防阻擋延遲
        for suffix in [".TW", ".TWO"]:
            try:
                temp = yf.download(f"{stock_id}{suffix}", period="6mo", progress=False)
                if not temp.empty:
                    df = temp
                    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                    break
            except: continue

    if df.empty: return None

    # --- 【關鍵修復點：安全的資料轉型】 ---
    try:
        # 只抓取必要的數字欄位，避免將 Date 或其他文字欄位轉成 float
        cols_needed = ['Open', 'High', 'Low', 'Close']
        df_clean = df[cols_needed].copy()
        
        # 強制將資料轉換為數字，無法轉換的會變成 NaN，然後用 ffill 補齊
        for col in cols_needed:
            df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce')
        
        df_clean = df_clean.ffill().dropna()
        
        # 提取為一維 Series
        close = df_clean['Close']
        high = df_clean['High']
        low = df_clean['Low']

        # 技術指標
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
        
        return {"price": float(close.iloc[-1]), "pct": (float(close.iloc[-1])-float(close.iloc[-2]))/float(close.iloc[-2])*100,
                "grade": grade, "action": action, "color": color, "details": details, "source": source_label}
    except Exception as e:
        return None

# --- 3. 介面 ---
st.set_page_config(page_title="台股智慧監控 V7.1.4", layout="centered")
st.title("📈 台股 AI 智慧監控 (雙引擎穩定版)")

# 管理區
with st.container(border=True):
    c1, c2, c3 = st.columns([2, 3, 1.2])
    in_id = c1.text_input("代號", key="stock_id")
    in_name = c2.text_input("名稱", key="stock_name")
    if c3.button("➕ 新增", use_container_width=True):
        if in_id and in_name:
            st.session_state.my_stocks.append({"id": in_id, "name": in_name})
            save_data(); st.rerun()

# 側邊欄與通知
with st.sidebar:
    st.header("⚙️ 系統設定")
    st.session_state.tg_token = st.text_input("Bot Token", value=st.session_state.tg_token, type="password")
    st.session_state.tg_chat_id = st.text_input("Chat ID", value=st.session_state.tg_chat_id)
    st.session_state.tg_threshold = st.number_input("通知門檻 (%)", value=st.session_state.tg_threshold)
    if st.button("💾 儲存設定"):
        save_data(); st.success("已存檔")
    
    st.divider()
    if st.button("🚀 執行即時掃描通知", use_container_width=True):
        st.cache_data.clear()
        found = 0
        for s in st.session_state.my_stocks:
            res = fetch_smart_data(s['id'])
            if res and abs(res['pct']) >= st.session_state.tg_threshold:
                msg = f"🔔 標的：{s['name']} ({s['id']})\n價：{res['price']:.2f} ({res['pct']:+.2f}%)\n評級：{res['grade']}\n符合：{', '.join(res['details'])}"
                requests.post(f"https://api.telegram.org/bot{st.session_state.tg_token}/sendMessage", 
                              json={"chat_id": st.session_state.tg_chat_id, "text": msg, "parse_mode": "HTML"})
                found += 1
        st.success(f"完成，送出 {found} 則")

# 顯示列表
st.divider()
for idx, s in enumerate(st.session_state.my_stocks):
    res = fetch_smart_data(s['id'])
    if res:
        with st.container(border=True):
            col_i, col_m, col_d = st.columns([3, 2, 0.6])
            with col_i:
                st.write(f"### {s['name']} ({s['id']})")
                st.markdown(f"評級：`{res['grade']}` | 數據源：`{res['source']}`", unsafe_allow_html=True)
                st.write(f"📊 {' '.join(res['details']) if res['details'] else '無指標符合'}")
            with col_m:
                st.metric("股價", f"{res['price']:.2f}", f"{res['pct']:+.2f}%", delta_color="inverse")
            with col_d:
                if st.button("🗑️", key=f"del_{s['id']}"):
                    st.session_state.my_stocks.pop(idx); save_data(); st.rerun()

if st.button("🔄 手動刷新"):
    st.cache_data.clear(); st.rerun()
