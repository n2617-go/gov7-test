import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import json
import os
from ta.trend import SMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands

# --- 1. 核心資料存取 (加入強制補全邏輯) ---
SAVE_FILE = "user_stocks_v7.json"

def load_data():
    # 這是保底的預設值
    default_config = {"stocks": [{"id": "2330", "name": "台積電"}], "tg_token": "", "tg_chat_id": "", "tg_threshold": 3.0}
    
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 如果檔案讀出來是空的，或 stocks 是空的，就回傳預設值
                if not data or not data.get("stocks"):
                    return default_config
                return data
        except:
            return default_config
    return default_config

def save_data(data_to_save):
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data_to_save, f, ensure_ascii=False, indent=4)

# --- 2. 狀態初始化 (解決新增失效的關鍵) ---
# 每次跑程式都先讀取檔案，確保資料是最新的
config = load_data()

if 'my_stocks' not in st.session_state:
    st.session_state.my_stocks = config["stocks"]
if 'tg_token' not in st.session_state:
    st.session_state.tg_token = config["tg_token"]
if 'tg_chat_id' not in st.session_state:
    st.session_state.tg_chat_id = config["tg_chat_id"]
if 'tg_threshold' not in st.session_state:
    st.session_state.tg_threshold = config["tg_threshold"]

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
    
    close = pd.Series(df['Close'].values.flatten(), index=df.index)
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
    
    # 判定五大指標
    m = [
        last['MA5'] > last['MA10'] > last['MA20'],
        last['K'] > last['D'] and last['K'] > 20,
        last['MACD_diff'] > 0,
        last['RSI'] > 50,
        last['Close'] > last['BBM']
    ]
    
    names = ["均線多頭", "KD金叉", "MACD轉正", "RSI強勢", "站穩月線"]
    details = [f"✅{names[i]}" for i in range(5) if m[i]]
    
    score = sum(m)
    decision_map = {
        5: ("S (極強)", "🔥 續抱/加碼", "red"),
        4: ("A (強勢)", "🚀 偏多持股", "orange"),
        3: ("B (轉強)", "📈 少量試單", "green"),
        2: ("C (盤整)", "⚖️ 暫時觀望", "blue"),
        1: ("D (弱勢)", "📉 減碼避險", "gray"),
        0: ("E (極弱)", "🚫 觀望不進場", "black")
    }
    grade, action, color = decision_map[score]
    
    return {"price": float(last['Close']), "pct": (float(last['Close'])-float(prev['Close']))/float(prev['Close'])*100, 
            "grade": grade, "action": action, "color": color, "details": details}

# --- 4. 介面設計 ---
st.set_page_config(page_title="台股監控 V7.6", layout="centered")
st.title("📈 台股 AI 技術分級監控")

#【重要修復：新增股票功能】
with st.container(border=True):
    st.subheader("🔍 新增股票")
    c1, c2, c3 = st.columns([2, 3, 1.2])
    add_id = c1.text_input("代號", key="stock_id_input")
    add_name = c2.text_input("名稱", key="stock_name_input")
    if c3.button("➕ 新增", use_container_width=True):
        if add_id and add_name:
            # 直接更新 session_state
            st.session_state.my_stocks.append({"id": add_id, "name": add_name})
            # 立即同步到檔案
            save_data({
                "stocks": st.session_state.my_stocks,
                "tg_token": st.session_state.tg_token,
                "tg_chat_id": st.session_state.tg_chat_id,
                "tg_threshold": st.session_state.tg_threshold
            })
            st.success(f"已新增 {add_name}")
            st.rerun()

# 側邊欄
with st.sidebar:
    st.header("⚙️ 設定與通知")
    st.session_state.tg_token = st.text_input("Bot Token", value=st.session_state.tg_token, type="password")
    st.session_state.tg_chat_id = st.text_input("Chat ID", value=st.session_state.tg_chat_id)
    st.session_state.tg_threshold = st.number_input("通知門檻 (%)", value=st.session_state.tg_threshold)
    
    if st.button("💾 儲存設定", use_container_width=True):
        save_data({
            "stocks": st.session_state.my_stocks,
            "tg_token": st.session_state.tg_token,
            "tg_chat_id": st.session_state.tg_chat_id,
            "tg_threshold": st.session_state.tg_threshold
        })
        st.success("已手動存檔！")
        
    st.divider()
    
    if st.button("🚀 測試掃描並通知", use_container_width=True):
        st.cache_data.clear()
        found = 0
        for s in st.session_state.my_stocks:
            res = fetch_and_analyze(s['id'])
            if res and abs(res['pct']) >= st.session_state.tg_threshold:
                msg = (f"🔔 <b>【決策通知】</b>\n標的：{s['name']}\n股價：{res['price']:.2f} ({res['pct']:+.2f}%)\n評級：{res['grade']}\n建議：{res['action']}")
                requests.post(f"https://api.telegram.org/bot{st.session_state.tg_token}/sendMessage", 
                              json={"chat_id": st.session_state.tg_chat_id, "text": msg, "parse_mode": "HTML"})
                found += 1
        st.success(f"已發送 {found} 則通知")

# --- 5. 顯示清單 ---
st.divider()

# 如果清單還是空的 (防呆機制)
if not st.session_state.my_stocks:
    st.warning("⚠️ 目前清單為空，請輸入代號新增股票。")
else:
    for idx, s in enumerate(st.session_state.my_stocks):
        res = fetch_and_analyze(s['id'])
        if res:
            with st.container(border=True):
                col_info, col_metric, col_del = st.columns([3, 2, 0.6])
                with col_info:
                    st.write(f"### {s['name']} ({s['id']})")
                    st.markdown(f"評級：`{res['grade']}` | **建議：<span style='color:{res['color']}'>{res['action']}</span>**", unsafe_allow_html=True)
                    st.write(f"📊 {' '.join(res['details']) if res['details'] else '無指標符合'}")
                with col_metric:
                    st.metric("股價", f"{res['price']:.2f}", f"{res['pct']:+.2f}%", delta_color="inverse")
                with col_del:
                    if st.button("🗑️", key=f"del_{s['id']}"):
                        st.session_state.my_stocks.pop(idx)
                        save_data({"stocks": st.session_state.my_stocks, "tg_token": st.session_state.tg_token, "tg_chat_id": st.session_state.tg_chat_id, "tg_threshold": st.session_state.tg_threshold})
                        st.rerun()

if st.button("🔄 手動刷新數據"):
    st.cache_data.clear(); st.rerun()
