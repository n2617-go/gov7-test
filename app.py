import streamlit as st
import yfinance as yf
import pandas as pd
import time
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
SAVE_FILE = "my_stocks_v4_final.json"

def load_data():
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {"stocks": [{"id": "2330", "name": "台積電"}], "tg_token": "", "tg_chat_id": "", "tg_threshold": 3.0}

def save_data():
    data = {
        "stocks": st.session_state.my_stocks,
        "tg_token": st.session_state.get('tg_token', ''),
        "tg_chat_id": st.session_state.get('tg_chat_id', ''),
        "tg_threshold": st.session_state.get('tg_threshold', 3.0)
    }
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

if 'initialized' not in st.session_state:
    saved_config = load_data()
    st.session_state.update({
        'my_stocks': saved_config["stocks"],
        'tg_token': saved_config["tg_token"],
        'tg_chat_id': saved_config["tg_chat_id"],
        'tg_threshold': saved_config["tg_threshold"],
        'initialized': True,
        'alert_history': {}
    })

# --- 1. 核心引擎 ---
def get_market_status():
    now_tw = datetime.now(tw_tz)
    if now_tw.weekday() >= 5: return "💤 休市 (週末)", False
    if dt_time(9, 0) <= now_tw.time() <= dt_time(13, 35): return "⚡ 開盤中", True
    return "🌙 休市中", False

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
    
    status_label, is_open = get_market_status()
    if is_open:
        try:
            dl = DataLoader()
            now_s = datetime.now(tw_tz).strftime('%Y-%m-%d')
            fm_df = dl.taiwan_stock_price(stock_id=stock_id, start_date=now_s, end_date=now_s)
            if not fm_df.empty:
                last_row = fm_df.iloc[-1]
                new_data = pd.DataFrame({'Open':[float(last_row['open'])],'High':[float(last_row['max'])],'Low':[float(last_row['min'])],'Close':[float(last_row['close'])],'Volume':[float(last_row['Trading_Volume'])]}, index=[pd.to_datetime(now_s)])
                df = pd.concat([df, new_data]).drop_duplicates(keep='last')
        except: pass

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
    except Exception as e:
        return None
    
    last = df.iloc[-1]; prev = df.iloc[-2]
    results = []; score = 0
    if last['MA5'] > last['MA10'] > last['MA20']: results.append("✅ 均線：多頭排列"); score += 1
    if last['K'] > last['D'] and last['K'] > 20: results.append("✅ KD：黃金交叉"); score += 1
    if last['MACD_diff'] > 0: results.append("✅ MACD：柱狀體轉正"); score += 1
    if last['RSI'] > 50: results.append("✅ RSI：強勢區"); score += 1
    if last['Close'] > last['BBM']: results.append("✅ 布林：站穩中軸"); score += 1
    grade = {5:"S", 4:"A", 3:"B", 2:"C", 1:"D", 0:"E"}.get(score, "E")
    
    return {"price": float(last['Close']), "pct": (float(last['Close'])-float(prev['Close']))/float(prev['Close'])*100, "grade": grade, "details": results, "score": score}

# --- 2. 介面 ---
st.set_page_config(page_title="台股 AI 技術分級", layout="centered")
st.title("📈 台股 AI 技術分級監控")

with st.sidebar:
    st.header("⚙️ 系統設定")
    st.session_state.tg_token = st.text_input("Bot Token", type="password", value=st.session_state.tg_token)
    st.session_state.tg_chat_id = st.text_input("Chat ID", value=st.session_state.tg_chat_id)
    st.session_state.tg_threshold = st.number_input("通知門檻 (%)", value=st.session_state.tg_threshold, step=0.1)
    if st.button("💾 儲存設定"):
        save_data(); st.success("設定已儲存！")
    
    st.divider()
    # --- 這裡就是你找的按鈕 ---
    if st.button("🚀 手動測試連線並掃描通知"):
        st.cache_data.clear()
        found_any = False
        for stock in st.session_state.my_stocks:
            res = fetch_and_analyze(stock['id'])
            if res and abs(res['pct']) >= st.session_state.tg_threshold:
                found_any = True
                msg = (f"🔔 <b>【手動連線測試】</b>\n\n標的：{stock['name']} ({stock['id']})\n漲跌：{res['pct']:+.2f}%\n等級：{res['grade']}\n符合：{', '.join(res['details'])}")
                requests.post(f"https://api.telegram.org/bot{st.session_state.tg_token}/sendMessage", json={"chat_id": st.session_state.tg_chat_id, "text": msg, "parse_mode": "HTML"})
        if not found_any: st.warning("目前無股票達門檻，建議暫時調低門檻進行測試。")
        else: st.success("符合門檻股票已發送通知！")

# --- 3. 主畫面顯示 ---
for idx, stock in enumerate(st.session_state.my_stocks):
    res = fetch_and_analyze(stock['id'])
    if res:
        with st.container(border=True):
            col1, col2 = st.columns([3, 2])
            with col1:
                st.subheader(f"{stock['name']} ({stock['id']})")
                st.write(f"評級：{res['grade']} ({res['score']}/5)")
            with col2:
                st.metric("股價", f"{res['price']:.2f}", f"{res['pct']:+.2f}%", delta_color="inverse")
            if st.button("🗑️", key=f"del_{stock['id']}"):
                st.session_state.my_stocks.pop(idx); save_data(); st.rerun()

st.divider()
if st.button("🔄 刷新頁面"): st.cache_data.clear(); st.rerun()
