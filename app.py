import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import json
import os
from ta.trend import SMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands

# --- 1. 核心資料存取 (沿用 V7.1 穩定邏輯) ---
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
    st.session_state.update({'my_stocks': config["stocks"], 'tg_token': config["tg_token"], 'tg_chat_id': config["tg_chat_id"], 'tg_threshold': config["tg_threshold"]})

# --- 2. 分析引擎 (核心修改：將指標判定提前至此步驟) ---
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
        # 計算技術指標
        ma5 = SMAIndicator(close, window=5).sma_indicator()
        ma10 = SMAIndicator(close, window=10).sma_indicator()
        ma20 = SMAIndicator(close, window=20).sma_indicator()
        stoch = StochasticOscillator(df['High'], df['Low'], close, window=9)
        k, d = stoch.stoch(), stoch.stoch_signal()
        macd_diff = MACD(close).macd_diff()
        rsi = RSIIndicator(close).rsi()
        bb_m = BollingerBands(close).bollinger_mavg()
        
        last_ma5, last_ma10, last_ma20 = ma5.iloc[-1], ma10.iloc[-1], ma20.iloc[-1]
        last_k, last_d = k.iloc[-1], d.iloc[-1]
        last_macd, last_rsi, last_close, last_bbm = macd_diff.iloc[-1], rsi.iloc[-1], close.iloc[-1], bb_m.iloc[-1]
    except: return None
    
    # --- 事先計算指標符合狀況 ---
    m_list = [
        ("均線多頭", last_ma5 > last_ma10 > last_ma20),
        ("KD金叉", last_k > last_d and last_k > 20),
        ("MACD轉正", last_macd > 0),
        ("RSI強勢", last_rsi > 50),
        ("站穩月線", last_close > last_bbm)
    ]
    
    details = [f"✅{name}" for name, met in m_list if met]
    score = sum(1 for name, met in m_list if met)
    
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
        "price": float(last_close),
        "pct": (float(last_close) - float(close.iloc[-2])) / float(close.iloc[-2]) * 100,
        "grade": grade, "action": action, "color": color, "details": details
    }

# --- 3. 介面與功能 ---
st.set_page_config(page_title="台股監控 V7.1 Plus", layout="centered")
st.title("📈 台股 AI 技術分級監控")

# 管理股票
with st.container(border=True):
    st.subheader("🔍 管理自選股")
    c1, c2, c3 = st.columns([2, 3, 1.2])
    if c3.button("➕ 新增", use_container_width=True):
        if c1.session_state.get("new_id") and c2.session_state.get("new_name"):
            st.session_state.my_stocks.append({"id": c1.session_state.new_id, "name": c2.session_state.new_name})
            save_data(); st.rerun()
    # 這裡使用直接輸入而非 state 綁定以維持 7.1 的簡潔感
    input_id = c1.text_input("代號", key="new_id")
    input_name = c2.text_input("名稱", key="new_name")

# 側邊欄
with st.sidebar:
    st.header("⚙️ 系統設定")
    st.session_state.tg_token = st.text_input("Bot Token", value=st.session_state.tg_token, type="password")
    st.session_state.tg_chat_id = st.text_input("Chat ID", value=st.session_state.tg_chat_id)
    st.session_state.tg_threshold = st.number_input("通知門檻 (%)", value=st.session_state.tg_threshold)
    if st.button("💾 儲存所有設定", use_container_width=True):
        save_data(); st.success("設定已儲存！")
    
    st.divider()
    
    if st.button("🚀 測試掃描並發送通知", use_container_width=True):
        st.cache_data.clear()
        for s in st.session_state.my_stocks:
            res = fetch_and_analyze(s['id'])
            if res and abs(res['pct']) >= st.session_state.tg_threshold:
                msg = (f"🔔 <b>{s['name']} ({s['id']})</b>\n價：{res['price']:.2f} ({res['pct']:+.2f}%)\n評級：{res['grade']}\n符合：{', '.join(res['details'])}")
                requests.post(f"https://api.telegram.org/bot{st.session_state.tg_token}/sendMessage", 
                              json={"chat_id": st.session_state.tg_chat_id, "text": msg, "parse_mode": "HTML"})
        st.success("通知已處理")

# --- 4. 顯示清單 (網頁顯示邏輯) ---
st.divider()
for idx, s in enumerate(st.session_state.my_stocks):
    res = fetch_and_analyze(s['id'])
    if res:
        with st.container(border=True):
            col_info, col_metric, col_del = st.columns([3, 2, 0.6])
            with col_info:
                st.write(f"### {s['name']} ({s['id']})")
                st.markdown(f"評級：`{res['grade']}` | **建議：<span style='color:{res['color']}'>{res['action']}</span>**", unsafe_allow_html=True)
                
                # --- 事先算好，直接在網頁顯示指標細節 ---
                st.write(f"📊 {' '.join(res['details']) if res['details'] else '⚠️ 無指標符合'}")
                
            with col_metric:
                st.metric("股價", f"{res['price']:.2f}", f"{res['pct']:+.2f}%", delta_color="inverse")
            with col_del:
                if st.button("🗑️", key=f"del_{s['id']}"):
                    st.session_state.my_stocks.pop(idx); save_data(); st.rerun()

if st.button("🔄 全部數據重整"):
    st.cache_data.clear(); st.rerun()
