import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import pytz
import json
import os
from datetime import datetime, time as dt_time
from FinMind.data import DataLoader
from ta.trend import SMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands

# --- 0. 基礎設定 ---
tw_tz = pytz.timezone('Asia/Taipei')
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

if 'initialized' not in st.session_state:
    config = load_data()
    st.session_state.update({'my_stocks': config["stocks"], 'tg_token': config["tg_token"], 'tg_chat_id': config["tg_chat_id"], 'tg_threshold': config["tg_threshold"], 'initialized': True})

# --- 1. 分析引擎 ---
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
    
    close = pd.Series(df['Close'].values.flatten(), index=df.index).astype(float)
    high = pd.Series(df['High'].values.flatten(), index=df.index).astype(float)
    low = pd.Series(df['Low'].values.flatten(), index=df.index).astype(float)
    
    try:
        df['MA5'] = SMAIndicator(close, window=5).sma_indicator()
        df['MA10'] = SMAIndicator(close, window=10).sma_indicator()
        df['MA20'] = SMAIndicator(close, window=20).sma_indicator()
        stoch = StochasticOscillator(high, low, close, window=9)
        df['K']=stoch.stoch(); df['D']=stoch.stoch_signal()
        df['MACD_diff'] = MACD(close, window_slow=26, window_fast=12, window_sign=9).macd_diff()
        df['RSI'] = RSIIndicator(close, window=14).rsi()
        df['BBM'] = BollingerBands(close, window=20).bollinger_mavg()
    except: return None
    
    last = df.iloc[-1]; prev = df.iloc[-2]
    
    # 建立指標清單 (名稱, 判斷結果, 意義)
    check_list = [
        ("均線多頭", last['MA5'] > last['MA10'] > last['MA20'], "MA5 > 10 > 20"),
        ("KD黃金交叉", last['K'] > last['D'] and last['K'] > 20, "K > D 且離超賣區"),
        ("MACD轉正", last['MACD_diff'] > 0, "柱狀體 OSC > 0"),
        ("RSI強勢", last['RSI'] > 50, "RSI(14) > 50"),
        ("站穩月線", last['Close'] > last['BBM'], "收盤價 > 布林中軸")
    ]
    
    score = sum(1 for _, res, _ in check_list if res)
    details = [name for name, res, _ in check_list if res]
    
    decision_map = {
        5: {"grade": "S (極強)", "action": "🔥 續抱/加碼", "color": "red"},
        4: {"grade": "A (強勢)", "action": "🚀 偏多持股", "color": "orange"},
        3: {"grade": "B (轉強)", "action": "📈 少量試單", "color": "green"},
        2: {"grade": "C (盤整)", "action": "⚖️ 暫時觀望", "color": "blue"},
        1: {"grade": "D (弱勢)", "action": "📉 減碼避險", "color": "gray"},
        0: {"grade": "E (極弱)", "action": "🚫 觀望不進場", "color": "black"}
    }
    res = decision_map.get(score)
    
    return {
        "price": float(last['Close']),
        "pct": (float(last['Close'])-float(prev['Close']))/float(prev['Close'])*100,
        "grade": res["grade"],
        "action": res["action"],
        "color": res["color"],
        "details": details,
        "check_list": check_list, # 傳回完整清單供網頁顯示
        "score": score
    }

# --- 2. 介面 ---
st.set_page_config(page_title="台股決策系統 V7.2", layout="centered")
st.title("🤖 台股 AI 技術分級監控")

# 新增股票
with st.container(border=True):
    c1, c2, c3 = st.columns([2,3,1.2])
    input_id = c1.text_input("代號", key="add_id")
    input_name = c2.text_input("名稱", key="add_name")
    if c3.button("➕ 新增", use_container_width=True):
        if input_id and input_name:
            if not any(s['id'] == input_id for s in st.session_state.my_stocks):
                st.session_state.my_stocks.append({"id": input_id, "name": input_name})
                save_data(); st.rerun()

# 側邊欄通知
with st.sidebar:
    st.header("⚙️ 通知設定")
    st.session_state.tg_token = st.text_input("Bot Token", type="password", value=st.session_state.tg_token)
    st.session_state.tg_chat_id = st.text_input("Chat ID", value=st.session_state.tg_chat_id)
    st.session_state.tg_threshold = st.number_input("通知門檻 (%)", value=st.session_state.tg_threshold)
    if st.button("💾 儲存並刷新"):
        save_data(); st.cache_data.clear(); st.rerun()
    st.divider()
    if st.button("🚀 手動掃描發送通知", use_container_width=True):
        st.cache_data.clear()
        found = 0
        for s in st.session_state.my_stocks:
            res = fetch_and_analyze(s['id'])
            if res and abs(res['pct']) >= st.session_state.tg_threshold:
                msg = (f"🔔 <b>【AI 決策通知】</b>\n\n標的：<b>{s['name']} ({s['id']})</b>\n股價：<b>{res['price']:.2f}</b> ({res['pct']:+.2f}%)\n"
                       f"評級：{res['grade']}\n建議：<b>{res['action']}</b>\n\n符合：{', '.join(res['details'])}")
                requests.post(f"https://api.telegram.org/bot{st.session_state.tg_token}/sendMessage", 
                              json={"chat_id": st.session_state.tg_chat_id, "text": msg, "parse_mode": "HTML"})
                found += 1
        st.success(f"已發送 {found} 則通知")

# --- 3. 股票清單顯示 ---
st.divider()
for idx, stock in enumerate(st.session_state.my_stocks):
    res = fetch_and_analyze(stock['id'])
    if res:
        with st.container(border=True):
            col_main, col_del = st.columns([5, 0.5])
            with col_main:
                c1, c2 = st.columns([3, 2])
                c1.write(f"### {stock['name']} ({stock['id']})")
                c1.markdown(f"評級：**{res['grade']}** | 建議：<span style='color:{res['color']}'>**{res['action']}**</span>", unsafe_allow_html=True)
                c2.metric("最新股價", f"{res['price']:.2f}", f"{res['pct']:+.2f}%", delta_color="inverse")
                
                # --- 新增：網頁直接顯示指標標籤 ---
                st.write("符合指標：")
                cols = st.columns(len(res['check_list']))
                for i, (name, is_met, hint) in enumerate(res['check_list']):
                    if is_met:
                        cols[i].markdown(f":green[✔ {name}]")
                    else:
                        cols[i].markdown(f":gray[✘ {name}]")
            with col_del:
                if st.button("🗑️", key=f"del_{stock['id']}"):
                    st.session_state.my_stocks.pop(idx); save_data(); st.rerun()

if st.button("🔄 全部重新整理"):
    st.cache_data.clear(); st.rerun()
