import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import pytz
import json
import os
from datetime import datetime
from ta.trend import SMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands

# --- 0. 基礎設定與修復核心 ---
tw_tz = pytz.timezone('Asia/Taipei')
SAVE_FILE = "user_stocks_v7.json"

def load_data():
    # 預設資料包含台積電
    default_data = {
        "stocks": [{"id": "2330", "name": "台積電"}], 
        "tg_token": "", 
        "tg_chat_id": "", 
        "tg_threshold": 3.0
    }
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 確保 stocks 欄位存在且不為空，否則補回台積電
                if not data.get("stocks"):
                    data["stocks"] = default_data["stocks"]
                return data
        except Exception as e:
            st.error(f"讀取存檔失敗: {e}")
    return default_data

def save_data():
    data = {
        "stocks": st.session_state.my_stocks,
        "tg_token": st.session_state.tg_token,
        "tg_chat_id": st.session_state.tg_chat_id,
        "tg_threshold": st.session_state.tg_threshold
    }
    try:
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        st.error(f"儲存檔案失敗: {e}")

# 初始化狀態 (關鍵修復：確保每次啟動都重讀檔案)
if 'initialized' not in st.session_state or st.button("🔌 重啟系統"):
    config = load_data()
    st.session_state.my_stocks = config["stocks"]
    st.session_state.tg_token = config["tg_token"]
    st.session_state.tg_chat_id = config["tg_chat_id"]
    st.session_state.tg_threshold = config["tg_threshold"]
    st.session_state.initialized = True

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
    
    check_list = [
        ("均線多頭", last['MA5'] > last['MA10'] > last['MA20'], "多頭排列"),
        ("KD黃金交叉", last['K'] > last['D'] and last['K'] > 20, "攻擊動能"),
        ("MACD轉正", last['MACD_diff'] > 0, "波段向上"),
        ("RSI強勢", last['RSI'] > 50, "買氣旺盛"),
        ("站穩月線", last['Close'] > last['BBM'], "生命線支撐")
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
        "check_list": check_list,
        "score": score
    }

# --- 2. 介面 ---
st.set_page_config(page_title="台股決策系統 V7.3", layout="centered")
st.title("🤖 台股 AI 技術分級監控")

#【修復：新增股票功能】
with st.container(border=True):
    st.subheader("🔍 管理自選股清單")
    c1, c2, c3 = st.columns([2,3,1.2])
    new_id = c1.text_input("代號", placeholder="例如: 2454", key="input_id")
    new_name = c2.text_input("名稱", placeholder="例如: 聯發科", key="input_name")
    if c3.button("➕ 新增股票", use_container_width=True):
        if new_id and new_name:
            if not any(s['id'] == new_id for s in st.session_state.my_stocks):
                st.session_state.my_stocks.append({"id": new_id, "name": new_name})
                save_data() # 立即存檔
                st.success(f"已成功加入 {new_name}！")
                st.rerun() # 強制刷新畫面
            else:
                st.warning("此股票已在清單中")
        else:
            st.error("請填寫代號與名稱")

# 側邊欄設定
with st.sidebar:
    st.header("⚙️ 系統設定")
    st.session_state.tg_token = st.text_input("Telegram Bot Token", value=st.session_state.tg_token, type="password")
    st.session_state.tg_chat_id = st.text_input("Chat ID", value=st.session_state.tg_chat_id)
    st.session_state.tg_threshold = st.number_input("漲跌通知門檻 (%)", value=st.session_state.tg_threshold)
    if st.button("💾 儲存所有設定", use_container_width=True):
        save_data(); st.success("設定已儲存！"); st.rerun()

# --- 3. 顯示清單 ---
st.divider()
if not st.session_state.my_stocks:
    st.info("目前清單為空，請從上方新增股票。")
else:
    for idx, stock in enumerate(st.session_state.my_stocks):
        res = fetch_and_analyze(stock['id'])
        if res:
            with st.container(border=True):
                col_main, col_del = st.columns([5, 0.5])
                with col_main:
                    c1, c2 = st.columns([3, 2])
                    c1.write(f"### {stock['name']} ({stock['id']})")
                    c1.markdown(f"評級：**{res['grade']}** | 建議：<span style='color:{res['color']}'>**{res['action']}**</span>", unsafe_allow_html=True)
                    c2.metric("股價", f"{res['price']:.2f}", f"{res['pct']:+.2f}%", delta_color="inverse")
                    
                    st.write("符合指標：")
                    indicator_cols = st.columns(len(res['check_list']))
                    for i, (name, is_met, hint) in enumerate(res['check_list']):
                        if is_met:
                            indicator_cols[i].markdown(f":green[✔ {name}]")
                        else:
                            indicator_cols[i].markdown(f":gray[✘ {name}]")
                with col_del:
                    if st.button("🗑️", key=f"del_{stock['id']}"):
                        st.session_state.my_stocks.pop(idx)
                        save_data()
                        st.rerun()

if st.button("🔄 全球即時數據刷新"):
    st.cache_data.clear(); st.rerun()
