import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import json
import os
from ta.trend import SMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands

# --- 1. 核心資料存取 (回歸 V7.1 最穩定的寫法) ---
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
    data = {
        "stocks": st.session_state.my_stocks,
        "tg_token": st.session_state.tg_token,
        "tg_chat_id": st.session_state.tg_chat_id,
        "tg_threshold": st.session_state.tg_threshold
    }
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# 初始化 Session State
if 'my_stocks' not in st.session_state:
    config = load_data()
    st.session_state.my_stocks = config["stocks"]
    st.session_state.tg_token = config["tg_token"]
    st.session_state.tg_chat_id = config["tg_chat_id"]
    st.session_state.tg_threshold = config["tg_threshold"]

# --- 2. 分析引擎 ---
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
    
    close = pd.Series(df['Close'].values.flatten(), index=df.index)
    try:
        # 指標計算
        df['MA5'] = SMAIndicator(close, window=5).sma_indicator()
        df['MA10'] = SMAIndicator(close, window=10).sma_indicator()
        df['MA20'] = SMAIndicator(close, window=20).sma_indicator()
        stoch = StochasticOscillator(df['High'], df['Low'], close, window=9)
        df['K']=stoch.stoch(); df['D']=stoch.stoch_signal()
        df['MACD_diff'] = MACD(close).macd_diff()
        df['RSI'] = RSIIndicator(close).rsi()
        df['BBM'] = BollingerBands(close).bollinger_mavg()
    except: return None
    
    last = df.iloc[-1]; prev = df.iloc[-2]
    
    # 判定指標
    m1 = last['MA5'] > last['MA10'] > last['MA20']
    m2 = last['K'] > last['D'] and last['K'] > 20
    m3 = last['MACD_diff'] > 0
    m4 = last['RSI'] > 50
    m5 = last['Close'] > last['BBM']
    
    score = sum([m1, m2, m3, m4, m5])
    details = []
    if m1: details.append("✅均線多頭")
    if m2: details.append("✅KD金叉")
    if m3: details.append("✅MACD轉正")
    if m4: details.append("✅RSI強勢")
    if m5: details.append("✅站穩月線")
    
    decision_map = {
        5: ("S (極強)", "🔥 續抱/加碼", "red"),
        4: ("A (強勢)", "🚀 偏多持股", "orange"),
        3: ("B (轉強)", "📈 少量試單", "green"),
        2: ("C (盤整)", "⚖️ 暫時觀望", "blue"),
        1: ("D (弱勢)", "📉 減碼避險", "gray"),
        0: ("E (極弱)", "🚫 觀望不進場", "black")
    }
    grade, action, color = decision_map[score]
    
    return {
        "price": float(last['Close']),
        "pct": (float(last['Close'])-float(prev['Close']))/float(prev['Close'])*100,
        "grade": grade, "action": action, "color": color, "details": details
    }

# --- 3. 介面 (簡約穩定版) ---
st.set_page_config(page_title="台股監控 V7.5", layout="centered")
st.title("📈 台股 AI 技術分級監控")

# 新增功能
with st.container(border=True):
    st.subheader("🔍 新增股票")
    c1, c2, c3 = st.columns([2, 3, 1.2])
    add_id = c1.text_input("代號", key="new_id")
    add_name = c2.text_input("名稱", key="new_name")
    if c3.button("➕ 新增"):
        if add_id and add_name:
            st.session_state.my_stocks.append({"id": add_id, "name": add_name})
            save_data()
            st.rerun()

# 側邊欄 (按鈕全部找回來了)
with st.sidebar:
    st.header("⚙️ 設定與通知")
    st.session_state.tg_token = st.text_input("Bot Token", value=st.session_state.tg_token, type="password")
    st.session_state.tg_chat_id = st.text_input("Chat ID", value=st.session_state.tg_chat_id)
    st.session_state.tg_threshold = st.number_input("通知門檻 (%)", value=st.session_state.tg_threshold)
    
    if st.button("💾 儲存設定"):
        save_data()
        st.success("已存檔")
        
    st.divider()
    
    if st.button("🚀 測試連線並掃描通知", use_container_width=True):
        st.cache_data.clear()
        found = 0
        for s in st.session_state.my_stocks:
            res = fetch_and_analyze(s['id'])
            if res and abs(res['pct']) >= st.session_state.tg_threshold:
                msg = (f"🔔 <b>【決策通知】</b>\n\n標的：{s['name']} ({s['id']})\n"
                       f"股價：{res['price']:.2f} ({res['pct']:+.2f}%)\n"
                       f"評級：{res['grade']}\n建議：{res['action']}\n\n符合：{', '.join(res['details'])}")
                requests.post(f"https://api.telegram.org/bot{st.session_state.tg_token}/sendMessage", 
                              json={"chat_id": st.session_state.tg_chat_id, "text": msg, "parse_mode": "HTML"})
                found += 1
        st.success(f"已發送 {found} 則通知")

# --- 4. 顯示清單 ---
st.divider()
for idx, s in enumerate(st.session_state.my_stocks):
    res = fetch_and_analyze(s['id'])
    if res:
        with st.container(border=True):
            col_info, col_metric, col_del = st.columns([3, 2, 0.6])
            with col_info:
                st.write(f"### {s['name']} ({s['id']})")
                st.markdown(f"評級：`{res['grade']}`")
                st.markdown(f"**建議：<span style='color:{res['color']}'>{res['action']}</span>**", unsafe_allow_html=True)
                # 這裡補上網頁顯示指標！
                st.write(f"📊 {' '.join(res['details'])}") 
            with col_metric:
                st.metric("股價", f"{res['price']:.2f}", f"{res['pct']:+.2f}%", delta_color="inverse")
            with col_del:
                if st.button("🗑️", key=f"del_{s['id']}"):
                    st.session_state.my_stocks.pop(idx)
                    save_data()
                    st.rerun()

if st.button("🔄 全部重新整理"):
    st.cache_data.clear()
    st.rerun()
