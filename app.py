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

# 引入 ta 套件核心模組
try:
    from ta.trend import SMAIndicator, MACD
    from ta.momentum import RSIIndicator, StochasticOscillator
    from ta.volatility import BollingerBands
except ImportError:
    st.error("請確保已在 requirements.txt 加入 'ta' 套件")

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

# --- 1. 核心引擎：時區與數據處理 ---
def get_market_status():
    now_tw = datetime.now(tw_tz)
    if now_tw.weekday() >= 5: return "💤 休市 (週末)", False
    current_time = now_tw.time()
    if dt_time(9, 0) <= current_time <= dt_time(13, 35): return "⚡ 開盤中", True
    return "🌙 休市中", False

@st.cache_data(ttl=60)
def fetch_and_analyze(stock_id):
    df = pd.DataFrame()
    # 抓取歷史資料
    for suffix in [".TW", ".TWO"]:
        try:
            temp_df = yf.download(f"{stock_id}{suffix}", period="6mo", progress=False)
            if not temp_df.empty:
                df = temp_df
                break
        except: continue
    
    if df.empty: return None

    # 資料清洗：處理 MultiIndex 並統一轉為 float
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.astype(float).ffill()
    
    # 盤中結合 FinMind 最新價
    status_label, is_open = get_market_status()
    if is_open:
        try:
            dl = DataLoader()
            now_s = datetime.now(tw_tz).strftime('%Y-%m-%d')
            fm_df = dl.taiwan_stock_price(stock_id=stock_id, start_date=now_s, end_date=now_s)
            if not fm_df.empty:
                last_row = fm_df.iloc[-1]
                new_data = pd.DataFrame({
                    'Open': [float(last_row['open'])], 'High': [float(last_row['max'])], 
                    'Low': [float(last_row['min'])], 'Close': [float(last_row['close'])], 
                    'Volume': [float(last_row['Trading_Volume'])]
                }, index=[pd.to_datetime(now_s)])
                df = pd.concat([df, new_data]).drop_duplicates(keep='last')
        except: pass

    # 強制壓平數據為 Series，確保 ta 套件可讀取
    close = pd.Series(df['Close'].values.flatten(), index=df.index).astype(float)
    high = pd.Series(df['High'].values.flatten(), index=df.index).astype(float)
    low = pd.Series(df['Low'].values.flatten(), index=df.index).astype(float)
    
    # --- 關鍵修正：相容性技術指標運算 ---
    try:
        # 嘗試新版參數 (window) 或 舊版參數 (n) 或 直接傳參
        try:
            df['MA5'] = SMAIndicator(close, window=5).sma_indicator()
            df['MA10'] = SMAIndicator(close, window=10).sma_indicator()
            df['MA20'] = SMAIndicator(close, window=20).sma_indicator()
            stoch = StochasticOscillator(high, low, close, window=9, fillna=True)
            df['K'] = stoch.stoch(); df['D'] = stoch.stoch_signal()
            df['MACD_diff'] = MACD(close, window_slow=26, window_fast=12, window_sign=9).macd_diff()
            df['RSI'] = RSIIndicator(close, window=14).rsi()
            df['BBM'] = BollingerBands(close, window=20).bollinger_mavg()
        except TypeError:
            # 備援方案：嘗試使用 'n' 作為參數名
            df['MA5'] = SMAIndicator(close, n=5).sma_indicator()
            df['MA10'] = SMAIndicator(close, n=10).sma_indicator()
            df['MA20'] = SMAIndicator(close, n=20).sma_indicator()
            stoch = StochasticOscillator(high, low, close, n=9)
            df['K'] = stoch.stoch(); df['D'] = stoch.stoch_signal()
            df['MACD_diff'] = MACD(close, n_slow=26, n_fast=12, n_sign=9).macd_diff()
            df['RSI'] = RSIIndicator(close, n=14).rsi()
            df['BBM'] = BollingerBands(close, n=20).bollinger_mavg()
    except Exception as e:
        st.error(f"技術指標運算失敗: {e}")
        return None
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # --- 4. 評分邏輯 (S/A/B/C/D) ---
    results = []; score = 0
    if last['MA5'] > last['MA10'] > last['MA20']:
        results.append("✅ 均線：多頭排列 (趨勢極強)"); score += 1
    if last['K'] > last['D'] and last['K'] > 20:
        results.append("✅ KD：黃金交叉/向上 (動能轉強)"); score += 1
    if last['MACD_diff'] > 0:
        results.append("✅ MACD：柱狀體轉正 (多方佔優)"); score += 1
    if last['RSI'] > 50:
        results.append("✅ RSI：站上50強勢區 (買盤積極)"); score += 1
    if last['Close'] > last['BBM']:
        results.append("✅ 布林：站穩中軸 MA20 (支撐確立)"); score += 1
        
    grade = {5: "S (極強)", 4: "A (強勢)", 3: "B (偏多)", 2: "C (震盪)", 1: "D (弱勢)", 0: "E (極弱)"}.get(score, "E")
    
    # 策略建議
    strategy = "觀望為宜"
    if score >= 4: strategy = "分批進場 / 持股續抱"
    elif score == 3: strategy = "少量試單 / 觀察突破"
    elif score <= 1: strategy = "減碼避險 / 尋找支撐"

    return {
        "price": float(last['Close']),
        "pct": (float(last['Close']) - float(prev['Close'])) / float(prev['Close']) * 100,
        "grade": grade,
        "details": results,
        "strategy": strategy,
        "score": score
    }

# --- 2. 介面設計 ---
st.set_page_config(page_title="台股 AI 技術分級", layout="centered")
st.title("📈 台股 AI 技術分級監控")
status_label, is_open = get_market_status()
st.info(f"系統狀態：{status_label}")

with st.sidebar:
    st.header("⚙️ 系統設定")
    st.session_state.tg_token = st.text_input("Telegram Token", type="password", value=st.session_state.tg_token)
    st.session_state.tg_chat_id = st.text_input("Telegram Chat ID", value=st.session_state.tg_chat_id)
    st.session_state.tg_threshold = st.number_input("通知門檻 (%)", value=st.session_state.tg_threshold, step=0.1)
    if st.button("💾 儲存並清除快取"):
        save_data(); st.cache_data.clear(); st.success("已更新設定")

with st.expander("➕ 新增自選股"):
    c1, c2, c3 = st.columns([2,3,1])
    nid = c1.text_input("代號 (例: 2330)")
    nname = c2.text_input("名稱 (例: 台積電)")
    if c3.button("新增"):
        if nid and nname:
            st.session_state.my_stocks.append({"id": nid, "name": nname})
            save_data(); st.rerun()

# --- 3. 監控主畫面 ---
for idx, stock in enumerate(st.session_state.my_stocks):
    res = fetch_and_analyze(stock['id'])
    if res:
        with st.container(border=True):
            col1, col2 = st.columns([3, 2])
            with col1:
                st.subheader(f"{stock['name']} ({stock['id']})")
                st.write(f"📊 **技術評級：{res['grade']}**")
            with col2:
                st.metric("當前成交價", f"{res['price']:.2f}", f"{res['pct']:+.2f}%", delta_color="inverse")
            
            with st.expander("💡 分析詳情與策略建議"):
                for d in res['details']: st.write(d)
                st.warning(f"策略建議：{res['strategy']}")
            
            if st.button("🗑️ 移除此檔", key=f"del_{stock['id']}"):
                st.session_state.my_stocks.pop(idx); save_data(); st.rerun()

            # --- 自動通知 (方案 A) ---
            if is_open and abs(res['pct']) >= st.session_state.tg_threshold:
                key = f"alert_v4_{stock['id']}_{datetime.now(tw_tz).strftime('%Y%m%d')}"
                if key not in st.session_state.alert_history:
                    msg = (f"🚨 <b>【台股異動通知】</b>\n\n"
                           f"標的：{stock['name']} ({stock['id']})\n"
                           f"價格：<b>{res['price']:.2f}</b> ({res['pct']:+.2f}%)\n"
                           f"技術等級：<b>{res['grade']}</b>\n\n"
                           f"📊 <b>符合指標：</b>\n" + "\n".join(res['details']) + "\n\n"
                           f"💡 <b>策略建議：</b>\n{res['strategy']}")
                    
                    try:
                        url = f"https://api.telegram.org/bot{st.session_state.tg_token}/sendMessage"
                        requests.post(url, json={"chat_id": st.session_state.tg_chat_id, "text": msg, "parse_mode": "HTML"}, timeout=5)
                        st.session_state.alert_history[key] = True
                    except: pass

st.divider()
if st.button("🔄 全域手動重新整理"):
    st.cache_data.clear(); st.rerun()
st.caption(f"數據最後更新時間: {datetime.now(tw_tz).strftime('%H:%M:%S')}")
