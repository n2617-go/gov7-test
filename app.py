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

# --- 0. 基礎設定與儲存機制 ---
tw_tz = pytz.timezone('Asia/Taipei')
SAVE_FILE = "user_stocks_v6.json"

def load_data():
    default_data = {
        "stocks": [{"id": "2330", "name": "台積電"}], 
        "tg_token": "", 
        "tg_chat_id": "", 
        "tg_threshold": 3.0
    }
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

# 初始化狀態
if 'initialized' not in st.session_state:
    config = load_data()
    st.session_state.update({
        'my_stocks': config["stocks"],
        'tg_token': config["tg_token"],
        'tg_chat_id': config["tg_chat_id"],
        'tg_threshold': config["tg_threshold"],
        'initialized': True,
        'alert_history': {}
    })

# --- 1. 核心分析引擎 ---
def get_market_status():
    now_tw = datetime.now(tw_tz)
    if now_tw.weekday() >= 5: return "💤 休市", False
    if dt_time(9, 0) <= now_tw.time() <= dt_time(13, 35): return "⚡ 開盤中", True
    return "🌙 已收盤", False

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
    
    # 指標計算 (相容性版本)
    close = pd.Series(df['Close'].values.flatten(), index=df.index).astype(float)
    high = pd.Series(df['High'].values.flatten(), index=df.index).astype(float)
    low = pd.Series(df['Low'].values.flatten(), index=df.index).astype(float)
    
    try:
        try:
            df['MA5'] = SMAIndicator(close, window=5).sma_indicator()
            df['MA10'] = SMAIndicator(close, window=10).sma_indicator()
            df['MA20'] = SMAIndicator(close, window=20).sma_indicator()
            stoch = StochasticOscillator(high, low, close, window=9)
            df['K']=stoch.stoch(); df['D']=stoch.stoch_signal()
            df['MACD_diff'] = MACD(close, window_slow=26, window_fast=12, window_sign=9).macd_diff()
            df['RSI'] = RSIIndicator(close, window=14).rsi()
            df['BBM'] = BollingerBands(close, window=20).bollinger_mavg()
        except TypeError:
            df['MA5'] = SMAIndicator(close, n=5).sma_indicator()
            df['MA10'] = SMAIndicator(close, n=10).sma_indicator()
            df['MA20'] = SMAIndicator(close, n=20).sma_indicator()
            stoch = StochasticOscillator(high, low, close, n=9)
            df['K']=stoch.stoch(); df['D']=stoch.stoch_signal()
            df['MACD_diff'] = MACD(close, n_slow=26, n_fast=12, n_sign=9).macd_diff()
            df['RSI'] = RSIIndicator(close, n=14).rsi()
            df['BBM'] = BollingerBands(close, n=20).bollinger_mavg()
    except: return None
    
    last = df.iloc[-1]; prev = df.iloc[-2]
    results = []; score = 0
    if last['MA5'] > last['MA10'] > last['MA20']: results.append("✅ 均線多頭"); score += 1
    if last['K'] > last['D'] and last['K'] > 20: results.append("✅ KD 黃金交叉"); score += 1
    if last['MACD_diff'] > 0: results.append("✅ MACD 柱狀體正"); score += 1
    if last['RSI'] > 50: results.append("✅ RSI 強勢區"); score += 1
    if last['Close'] > last['BBM']: results.append("✅ 站上布林中軸"); score += 1
    
    return {
        "price": float(last['Close']),
        "pct": (float(last['Close'])-float(prev['Close']))/float(prev['Close'])*100,
        "grade": {5:"S", 4:"A", 3:"B", 2:"C", 1:"D", 0:"E"}.get(score, "E"),
        "details": results,
        "score": score
    }

# --- 2. 介面與功能區 ---
st.set_page_config(page_title="台股監控 V6", layout="centered")
st.title("📈 關注股票：技術分級監控")

# ---【這裡就是消失的功能】---
with st.container(border=True):
    st.subheader("🔍 新增想要關注的股票")
    c1, c2, c3 = st.columns([2,3,1])
    input_id = c1.text_input("代號", placeholder="例如: 2330", key="new_stock_id")
    input_name = c2.text_input("名稱", placeholder="例如: 台積電", key="new_stock_name")
    if c3.button("新增"):
        if input_id and input_name:
            if not any(s['id'] == input_id for s in st.session_state.my_stocks):
                st.session_state.my_stocks.append({"id": input_id, "name": input_name})
                save_data()
                st.success(f"已新增 {input_name}！")
                st.rerun()
            else:
                st.warning("股票已在名單中")

# 側邊欄設定
with st.sidebar:
    st.header("⚙️ 通知設定")
    st.session_state.tg_token = st.text_input("Bot Token", type="password", value=st.session_state.tg_token)
    st.session_state.tg_chat_id = st.text_input("Chat ID", value=st.session_state.tg_chat_id)
    st.session_state.tg_threshold = st.number_input("通知門檻 (%)", value=st.session_state.tg_threshold)
    if st.button("💾 儲存設定"):
        save_data(); st.success("已儲存")
    st.divider()
    if
