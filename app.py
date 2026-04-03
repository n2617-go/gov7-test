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
SAVE_FILE = "user_stocks_v6_final.json"

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
    st.session_state.update({
        'my_stocks': config["stocks"], 
        'tg_token': config["tg_token"], 
        'tg_chat_id': config["tg_chat_id"], 
        'tg_threshold': config["tg_threshold"], 
        'initialized': True, 
        'alert_history': {}
    })

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
    
    return {"price": float(last['Close']), "pct": (float(last['Close'])-float(prev['Close']))/float(prev['Close'])*100, "grade": {5:"S", 4:"A", 3:"B", 2:"C", 1:"D", 0:"E"}.get(score, "E"), "details": results, "score": score}

# --- 2. 介面 ---
st.set_page_config(page_title="台股監控 V6.2", layout="centered")
st.title("📈 關注股票：技術分級監控")

#【功能：新增自選股】
with st.container(border=True):
    st.subheader("🔍 新增想要關注的股票")
    c1, c2, c3 = st.columns([2,3,1.2])
    input_id = c1.text_input("代號", placeholder="2330", key="add_id")
    input_name = c2.text_input("名稱", placeholder="台積電", key="add_name")
    if c3.button("➕ 新增", use_container_width=True):
        if input_id and input_name:
            if not any(s['id'] == input_id for s in st.session_state.my_stocks):
                st.session_state.my_stocks.append({"id": input_id, "name": input_name})
                save_data()
                st.success(f"已加入 {input_name}")
                st.rerun()
            else:
                st.warning("股票已在清單中")

# 側邊欄設定
with st.sidebar:
    st.header("⚙️ 通知設定")
    st.session_state.tg_token = st.text_input("Bot Token", type="password", value=st.session_state.tg_token)
    st.session_state.tg_chat_id = st.text_input("Chat ID", value=st.session_state.tg_chat_id)
    st.session_state.tg_threshold = st.number_input("通知門檻 (%)", value=st.session_state.tg_threshold)
    
    if st.button("💾 儲存並刷新", use_container_width=True):
        save_data(); st.cache_data.clear(); st.rerun()
    
    st.divider()
    
    # ---【重新加回：測試連線掃描按鈕】---
    if st.button("🚀 手動測試連線並掃描通知", use_container_width=True):
        if not st.session_state.tg_token or not st.session_state.tg_chat_id:
            st.error("請先填寫 Telegram Token 與 Chat ID")
        else:
            st.cache_data.clear() # 強制抓最新數據
            found_count = 0
            with st.spinner("正在掃描清單並嘗試發送通知..."):
                for s in st.session_state.my_stocks:
                    res = fetch_and_analyze(s['id'])
                    # 檢查是否符合漲跌幅門檻
                    if res and abs(res['pct']) >= st.session_state.tg_threshold:
                        msg = (f"🔔 <b>【手動連線測試】</b>\n\n"
                               f"標的：{s['name']} ({s['id']})\n"
                               f"目前漲跌：<b>{res['pct']:+.2f}%</b>\n"
                               f"技術評級：<b>{res['grade']}</b>\n\n"
                               f"符合指標：{', '.join(res['details']) if res['details'] else '無'}")
                        
                        try:
                            url = f"https://api.telegram.org/bot{st.session_state.tg_token}/sendMessage"
                            requests.post(url, json={"chat_id": st.session_state.tg_chat_id, "text": msg, "parse_mode": "HTML"}, timeout=5)
                            found_count += 1
                        except Exception as e:
                            st.error(f"發送失敗: {e}")
            
            if found_count > 0:
                st.success(f"測試完成！已為 {found_count} 檔符合門檻的股票發送通知。")
            else:
                st.warning("掃描完成，但目前清單中沒有股票達到通知門檻。")

# --- 3. 股票清單顯示 ---
st.divider()
for idx, stock in enumerate(st.session_state.my_stocks):
    res = fetch_and_analyze(stock['id'])
    if res:
        with st.container(border=True):
            col_info, col_metric, col_del = st.columns([3, 2, 0.6])
            with col_info:
                st.write(f"### {stock['name']} ({stock['id']})")
                st.write(f"等級：**{res['grade']}**")
            with col_metric:
                st.metric("股價", f"{res['price']:.2f}", f"{res['pct']:+.2f}%", delta_color="inverse")
            with col_del:
                if st.button("🗑️", key=f"del_{stock['id']}"):
                    st.session_state.my_stocks.pop(idx)
                    save_data(); st.rerun()
            with st.expander("符合指標"):
                st.write("、".join(res['details']) if res['details'] else "無指標符合")

if st.button("🔄 全部重新整理"):
    st.cache_data.clear(); st.rerun()
