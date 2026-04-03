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
    st.session_state.update({'my_stocks': config["stocks"], 'tg_token': config["tg_token"], 'tg_chat_id': config["tg_chat_id"], 'tg_threshold': config["tg_threshold"], 'initialized': True, 'alert_history': {}})

# --- 1. 核心分析與決策引擎 ---
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
        # 指標計算 (自動相容版本)
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
    
    # --- 指標判定邏輯與意義說明 ---
    score = 0
    details = []
    
    if last['MA5'] > last['MA10'] > last['MA20']:
        details.append("✅ **均線多頭**：短中長期趨勢同步向上，市場共識強。")
        score += 1
    if last['K'] > last['D'] and last['K'] > 20:
        details.append("✅ **KD 黃金交叉**：短期攻擊動能轉強，適合尋找切入點。")
        score += 1
    if last['MACD_diff'] > 0:
        details.append("✅ **MACD 柱狀體正**：波段多方控盤，趨勢尚未反轉。")
        score += 1
    if last['RSI'] > 50:
        details.append("✅ **RSI 強勢區**：買方力道強於賣方，股價具備支撐。")
        score += 1
    if last['Close'] > last['BBM']:
        details.append("✅ **站上月線(MA20)**：突破布林中軸，生命線守穩。")
        score += 1
        
    # --- 決策邏輯字典 ---
    decision_map = {
        5: {"grade": "S (極強)", "action": "🔥 續抱 / 回測加碼", "color": "red"},
        4: {"grade": "A (強勢)", "action": "🚀 偏多操作 / 持股續抱", "color": "orange"},
        3: {"grade": "B (轉強)", "action": "📈 少量試單 / 觀察突破", "color": "green"},
        2: {"grade": "C (盤整)", "action": "⚖️ 暫時觀望 / 多空拉鋸", "color": "blue"},
        1: {"grade": "D (弱勢)", "action": "📉 減碼避險 / 找支撐位", "color": "gray"},
        0: {"grade": "E (極弱)", "action": "🚫 觀望不進場 / 嚴設停損", "color": "black"}
    }
    
    result = decision_map.get(score)
    
    return {
        "price": float(last['Close']),
        "pct": (float(last['Close'])-float(prev['Close']))/float(prev['Close'])*100,
        "grade": result["grade"],
        "action": result["action"],
        "color": result["color"],
        "details": details,
        "score": score
    }

# --- 2. 介面設計 ---
st.set_page_config(page_title="台股 AI 決策系統", layout="centered")
st.title("🤖 台股 AI 技術分級與決策支援")

# 功能：新增自選股
with st.container(border=True):
    st.subheader("🔍 新增自選股票")
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

# 側邊欄：通知與測試
with st.sidebar:
    st.header("⚙️ 設定與測試")
    st.session_state.tg_token = st.text_input("Bot Token", type="password", value=st.session_state.tg_token)
    st.session_state.tg_chat_id = st.text_input("Chat ID", value=st.session_state.tg_chat_id)
    st.session_state.tg_threshold = st.number_input("通知門檻 (%)", value=st.session_state.tg_threshold)
    if st.button("💾 儲存並刷新"):
        save_data(); st.cache_data.clear(); st.rerun()
    st.divider()
    if st.button("🚀 測試連線並掃描通知"):
        st.cache_data.clear()
        for s in st.session_state.my_stocks:
            res = fetch_and_analyze(s['id'])
            if res and abs(res['pct']) >= st.session_state.tg_threshold:
                msg = (f"🔔 <b>【決策通知】</b>\n\n標的：{s['name']} ({s['id']})\n"
                       f"評級：{res['grade']}\n建議：{res['action']}\n漲跌：{res['pct']:+.2f}%")
                requests.post(f"https://api.telegram.org/bot{st.session_state.tg_token}/sendMessage", 
                              json={"chat_id": st.session_state.tg_chat_id, "text": msg, "parse_mode": "HTML"})
        st.success("掃描完成")

# --- 3. 股票清單與決策顯示 ---
st.divider()
for idx, stock in enumerate(st.session_state.my_stocks):
    res = fetch_and_analyze(stock['id'])
    if res:
        with st.container(border=True):
            col_info, col_metric, col_del = st.columns([3, 2, 0.6])
            with col_info:
                st.write(f"### {stock['name']} ({stock['id']})")
                # 顯示建議決策 (彩色顯示)
                st.markdown(f"評級：`{res['grade']}`")
                st.markdown(f"**建議決策：<span style='color:{res['color']}'>{res['action']}</span>**", unsafe_allow_html=True)
            with col_metric:
                st.metric("股價", f"{res['price']:.2f}", f"{res['pct']:+.2f}%", delta_color="inverse")
            with col_del:
                if st.button("🗑️", key=f"del_{stock['id']}"):
                    st.session_state.my_stocks.pop(idx); save_data(); st.rerun()
            
            with st.expander("📝 查看詳細指標意義"):
                if res['details']:
                    for d in res['details']: st.write(d)
                else:
                    st.write("🌚 目前無符合的多頭指標，市場信心較弱。")

if st.button("🔄 全部重新整理"):
    st.cache_data.clear(); st.rerun()
