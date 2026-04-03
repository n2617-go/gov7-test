import streamlit as st
import pandas as pd
import yfinance as yf
from FinMind.data import DataLoader
import requests
import json
import os
import time
from datetime import datetime
from ta.trend import SMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands

# --- 1. 核心資料存取 ---
SAVE_FILE = "user_stocks_v7.json"

def load_data():
    default = {"stocks": [{"id": "2330", "name": "台積電"}], "tg_token": "", "tg_chat_id": "", "tg_threshold": 3.0}
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                content = json.load(f)
                if content and "stocks" in content: return content
        except: pass
    return default

def save_data():
    # 使用 st.session_state 的最新值儲存
    data = {
        "stocks": st.session_state.get('my_stocks', []),
        "tg_token": st.session_state.get('tg_token', ""),
        "tg_chat_id": st.session_state.get('tg_chat_id', ""),
        "tg_threshold": st.session_state.get('tg_threshold', 3.0)
    }
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# 初始化 Session (確保在 UI 渲染前完成)
if 'my_stocks' not in st.session_state:
    conf = load_data()
    st.session_state.my_stocks = conf["stocks"]
    st.session_state.tg_token = conf["tg_token"]
    st.session_state.tg_chat_id = conf["tg_chat_id"]
    st.session_state.tg_threshold = conf["tg_threshold"]

# --- 2. 智慧分析引擎 (強化容錯性) ---
@st.cache_data(ttl=120) # 稍微縮短快取時間
def fetch_smart_data(stock_id):
    now = datetime.now()
    is_open = now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) <= (13, 35)
    
    df = pd.DataFrame()
    source_label = ""

    # 盤中嘗試 FinMind
    if is_open:
        try:
            dl = DataLoader()
            # 增加抓取範圍確保指標計算完整
            df = dl.taiwan_stock_daily(stock_id=stock_id, start_date='2024-11-01')
            if not df.empty:
                df = df.rename(columns={'close': 'Close', 'high': 'High', 'low': 'Low', 'open': 'Open'})
                source_label = "FinMind (即時)"
        except: pass
    
    # 盤後或失敗用 yfinance
    if df.empty:
        time.sleep(1.2) # 防阻擋延遲
        for suffix in [".TW", ".TWO"]:
            try:
                temp = yf.download(f"{stock_id}{suffix}", period="6mo", progress=False)
                if not temp.empty:
                    df = temp
                    # 處理 yfinance 多層索引
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    source_label = "yfinance (延遲)"
                    break
            except: continue

    if df.empty: return None

    # 【數據清理補強】
    try:
        cols = ['Open', 'High', 'Low', 'Close']
        df_num = df[cols].copy()
        # 強制轉數字，無效變 NaN
        for c in cols:
            df_num[c] = pd.to_numeric(df_num[c], errors='coerce')
        
        # 只要有一行是空的就補前值，但不可隨意 dropna 否則資料會變太短
        df_num = df_num.ffill()
        if len(df_num) < 20: return None # 若資料不足計算月線則放棄
        
        close, high, low = df_num['Close'], df_num['High'], df_num['Low']

        # 技術指標 (ta 套件對 numpy 格式容錯較好)
        m1 = SMAIndicator(close, 5).sma_indicator().iloc[-1] > SMAIndicator(close, 10).sma_indicator().iloc[-1] > SMAIndicator(close, 20).sma_indicator().iloc[-1]
        stoch = StochasticOscillator(high, low, close, 9)
        m2 = stoch.stoch().iloc[-1] > stoch.stoch_signal().iloc[-1] and stoch.stoch().iloc[-1] > 20
        m3 = MACD(close).macd_diff().iloc[-1] > 0
        m4 = RSIIndicator(close).rsi().iloc[-1] > 50
        m5 = close.iloc[-1] > BollingerBands(close).bollinger_mavg().iloc[-1]
        
        details = []
        if m1: details.append("✅均線多頭")
        if m2: details.append("✅KD金叉")
        if m3: details.append("✅MACD轉正")
        if m4: details.append("✅RSI強勢")
        if m5: details.append("✅站穩月線")
        
        score = sum([m1, m2, m3, m4, m5])
        d_map = {5:("S","🔥續抱/加碼","red"), 4:("A","🚀偏多持股","orange"), 3:("B","📈轉強試單","green"), 
                 2:("C","⚖️暫時觀望","blue"), 1:("D","📉減碼避險","gray"), 0:("E","🚫觀望不進場","black")}
        grade, action, color = d_map.get(score, ("?","?","black"))
        
        return {"price": float(close.iloc[-1]), "pct": (float(close.iloc[-1])-float(close.iloc[-2]))/float(close.iloc[-2])*100,
                "grade": grade, "action": action, "color": color, "details": details, "source": source_label}
    except: return None

# --- 3. 介面設計 ---
st.set_page_config(page_title="台股智慧監控 V7.1.5", layout="centered")
st.title("📈 台股 AI 智慧監控 (穩定修復版)")

# 新增股票 (使用表單確保資料同步)
with st.container(border=True):
    st.subheader("🔍 管理自選股")
    c1, c2, c3 = st.columns([2, 3, 1.2])
    new_id = c1.text_input("代號", placeholder="例如: 2330", key="ui_id")
    new_name = c2.text_input("名稱", placeholder="例如: 台積電", key="ui_name")
    if c3.button("➕ 新增", use_container_width=True):
        if new_id and new_name:
            st.session_state.my_stocks.append({"id": new_id, "name": new_name})
            save_data()
            st.rerun()

# 側邊欄
with st.sidebar:
    st.header("⚙️ 設定與通知")
    st.session_state.tg_token = st.text_input("Bot Token", value=st.session_state.tg_token, type="password")
    st.session_state.tg_chat_id = st.text_input("Chat ID", value=st.session_state.tg_chat_id)
    st.session_state.tg_threshold = st.number_input("門檻 (%)", value=st.session_state.tg_threshold, step=0.1)
    
    if st.button("💾 儲存並強制刷新"):
        save_data(); st.cache_data.clear(); st.rerun()
    
    st.divider()
    if st.button("🚀 即時掃描通知", use_container_width=True):
        st.cache_data.clear()
        found = 0
        for s in st.session_state.my_stocks:
            res = fetch_smart_data(s['id'])
            if res and abs(res['pct']) >= st.session_state.tg_threshold:
                msg = f"🔔 標的：{s['name']} ({s['id']})\n價：{res['price']:.2f} ({res['pct']:+.2f}%)\n評級：{res['grade']}\n符合：{', '.join(res['details'])}"
                requests.post(f"https://api.telegram.org/bot{st.session_state.tg_token}/sendMessage", 
                              json={"chat_id": st.session_state.tg_chat_id, "text": msg, "parse_mode": "HTML"})
                found += 1
        st.success(f"完成，送出 {found} 則")

# --- 4. 顯示股票清單 ---
st.divider()
if not st.session_state.my_stocks:
    st.info("目前沒有股票，請於上方新增。")
else:
    for idx, s in enumerate(st.session_state.my_stocks):
        res = fetch_smart_data(s['id'])
        if res:
            with st.container(border=True):
                col_i, col_m, col_d = st.columns([3, 2, 0.6])
                with col_i:
                    st.write(f"### {s['name']} ({s['id']})")
                    st.markdown(f"評級：`{res['grade']}` | 數據：`{res['source']}`", unsafe_allow_html=True)
                    st.write(f"📊 {' '.join(res['details']) if res['details'] else '無指標符合'}")
                with col_m:
                    st.metric("當前股價", f"{res['price']:.2f}", f"{res['pct']:+.2f}%", delta_color="inverse")
                with col_d:
                    # 刪除按鈕
                    if st.button("🗑️", key=f"del_{s['id']}_{idx}"):
                        st.session_state.my_stocks.pop(idx)
                        save_data()
                        st.rerun()
        else:
            st.warning(f"無法抓取 {s['name']} ({s['id']}) 的數據，請檢查代號或網路。")

if st.button("🔄 全部手動刷新"):
    st.cache_data.clear(); st.rerun()
