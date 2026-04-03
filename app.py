import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import json
import os
from ta.trend import SMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands

# --- 1. 檔案與資料核心 ---
SAVE_FILE = "user_stocks_v7.json"

def load_data():
    """從檔案讀取設定，若無檔案則建立預設值"""
    default_data = {
        "stocks": [{"id": "2330", "name": "台積電"}], 
        "tg_token": "", 
        "tg_chat_id": "", 
        "tg_threshold": 3.0
    }
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                content = f.read()
                if content:
                    return json.loads(content)
        except Exception:
            pass
    return default_data

def save_data(data_dict):
    """將目前的狀態存入檔案"""
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data_dict, f, ensure_ascii=False, indent=4)

# --- 2. 初始化 (最簡單的邏輯) ---
config = load_data()
if 'my_stocks' not in st.session_state:
    st.session_state.my_stocks = config["stocks"]
if 'tg_token' not in st.session_state:
    st.session_state.tg_token = config.get("tg_token", "")
if 'tg_chat_id' not in st.session_state:
    st.session_state.tg_chat_id = config.get("tg_chat_id", "")
if 'tg_threshold' not in st.session_state:
    st.session_state.tg_threshold = config.get("tg_threshold", 3.0)

# --- 3. 分析引擎 ---
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
    
    close = df['Close']
    try:
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
    check_list = [
        ("均線多頭", last['MA5'] > last['MA10'] > last['MA20']),
        ("KD金叉", last['K'] > last['D'] and last['K'] > 20),
        ("MACD轉正", last['MACD_diff'] > 0),
        ("RSI強勢", last['RSI'] > 50),
        ("站穩月線", last['Close'] > last['BBM'])
    ]
    score = sum(1 for _, res in check_list if res)
    
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
        "grade": grade, "action": action, "color": color,
        "check_list": check_list, "score": score
    }

# --- 4. 介面與功能 ---
st.set_page_config(page_title="台股監控 V7.4", layout="wide")
st.title("🤖 台股 AI 技術分析與決策支援")

# 功能 A：新增股票
with st.expander("➕ 新增自選股", expanded=True):
    c1, c2, c3 = st.columns([2, 3, 1])
    add_id = c1.text_input("代號 (如: 2454)")
    add_name = c2.text_input("名稱 (如: 聯發科)")
    if c3.button("執行新增"):
        if add_id and add_name:
            new_stock = {"id": add_id, "name": add_name}
            if new_stock not in st.session_state.my_stocks:
                st.session_state.my_stocks.append(new_stock)
                save_data({
                    "stocks": st.session_state.my_stocks,
                    "tg_token": st.session_state.tg_token,
                    "tg_chat_id": st.session_state.tg_chat_id,
                    "tg_threshold": st.session_state.tg_threshold
                })
                st.success(f"已加入 {add_name}")
                st.rerun()

# 側邊欄設定與測試
with st.sidebar:
    st.header("⚙️ 系統設定")
    st.session_state.tg_token = st.text_input("Bot Token", value=st.session_state.tg_token, type="password")
    st.session_state.tg_chat_id = st.text_input("Chat ID", value=st.session_state.tg_chat_id)
    st.session_state.tg_threshold = st.number_input("通知門檻 (%)", value=st.session_state.tg_threshold)
    
    if st.button("💾 儲存設定"):
        save_data({
            "stocks": st.session_state.my_stocks,
            "tg_token": st.session_state.tg_token,
            "tg_chat_id": st.session_state.tg_chat_id,
            "tg_threshold": st.session_state.tg_threshold
        })
        st.success("已儲存！")
    
    st.divider()
    
    # 【修復】通知按鈕確保存在
    if st.button("🚀 連線測試：全掃描通知"):
        found = 0
        for s in st.session_state.my_stocks:
            res = fetch_and_analyze(s['id'])
            if res and abs(res['pct']) >= st.session_state.tg_threshold:
                msg = (f"🔔 <b>【決策通知】</b>\n標的：{s['name']}\n股價：{res['price']:.2f} ({res['pct']:+.2f}%)\n評級：{res['grade']}\n建議：{res['action']}")
                requests.post(f"https://api.telegram.org/bot{st.session_state.tg_token}/sendMessage", 
                              json={"chat_id": st.session_state.tg_chat_id, "text": msg, "parse_mode": "HTML"})
                found += 1
        st.sidebar.write(f"✅ 已發送 {found} 則符合門檻之通知")

# --- 5. 顯示結果清單 ---
st.header("📋 我的監控清單")

if not st.session_state.my_stocks:
    st.warning("目前清單中沒有股票，請使用上方功能新增。")
else:
    for idx, s in enumerate(st.session_state.my_stocks):
        res = fetch_and_analyze(s['id'])
        if res:
            with st.container(border=True):
                col1, col2, col3, col4 = st.columns([2, 2, 4, 0.5])
                with col1:
                    st.subheader(f"{s['name']} ({s['id']})")
                    st.write(f"評級：**{res['grade']}**")
                with col2:
                    st.metric("股價", f"{res['price']:.2f}", f"{res['pct']:+.2f}%")
                    st.markdown(f"建議：<span style='color:{res['color']};font-size:20px;'>**{res['action']}**</span>", unsafe_allow_html=True)
                with col3:
                    st.write("技術指標狀態：")
                    # 直接顯示指標
                    tags = ""
                    for name, met in res['check_list']:
                        icon = "✅" if met else "❌"
                        color = "green" if met else "gray"
                        tags += f"<span style='color:{color}; margin-right:10px;'>{icon} {name}</span>"
                    st.markdown(tags, unsafe_allow_html=True)
                with col4:
                    if st.button("🗑️", key=f"del_{s['id']}"):
                        st.session_state.my_stocks.pop(idx)
                        save_data({"stocks": st.session_state.my_stocks, "tg_token": st.session_state.tg_token, "tg_chat_id": st.session_state.tg_chat_id, "tg_threshold": st.session_state.tg_threshold})
                        st.rerun()

if st.button("🔄 立即重新整理所有數據"):
    st.cache_data.clear()
    st.rerun()
