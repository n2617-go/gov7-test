import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import time
import random
import requests
import pytz
import json
import os
from datetime import datetime, time as dt_time
from FinMind.data import DataLoader

# --- 0. 基礎設定 ---
tw_tz = pytz.timezone('Asia/Taipei')
SAVE_FILE = "my_stocks_v4_settings.json"

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

# --- 1. 核心技術分析引擎 ---

def get_market_status():
    now_tw = datetime.now(tw_tz)
    if now_tw.weekday() >= 5: return "💤 休市 (週末)", False
    if dt_time(9, 0) <= now_tw.time() <= dt_time(13, 35): return "⚡ 開盤中", True
    return "🌙 休市中", False

@st.cache_data(ttl=60)
def fetch_and_analyze(stock_id):
    """結合長短資料並計算五大指標"""
    # 1. 抓取 yfinance 歷史資料 (100天)
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
    
    # 2. 盤中結合 FinMind 最新價
    status_label, is_open = get_market_status()
    if is_open:
        try:
            dl = DataLoader()
            now_s = datetime.now(tw_tz).strftime('%Y-%m-%d')
            fm_df = dl.taiwan_stock_price(stock_id=stock_id, start_date=now_s, end_date=now_s)
            if not fm_df.empty:
                last_row = fm_df.iloc[-1]
                new_data = pd.DataFrame({
                    'Open': [last_row['open']], 'High': [last_row['max']], 
                    'Low': [last_row['min']], 'Close': [last_row['close']], 
                    'Volume': [last_row['Trading_Volume']]
                }, index=[pd.to_datetime(now_s)])
                df = pd.concat([df, new_data]).drop_duplicates(keep='last')
        except: pass

    # 3. 技術指標運算 (pandas_ta)
    df.ta.ma(length=5, append=True)
    df.ta.ma(length=10, append=True)
    df.ta.ma(length=20, append=True)
    df.ta.kd(append=True)
    df.ta.macd(append=True)
    df.ta.rsi(length=14, append=True)
    df.ta.bbands(length=20, std=2, append=True)
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # 4. 五大指標判定
    results = []
    score = 0
    
    # 指標 1: MA 多頭排列
    if last['MA_5'] > last['MA_10'] > last['MA_20']:
        results.append("✅ 均線：短中長期多頭排列 (助漲力強)"); score += 1
    # 指標 2: KD 向上
    if last['STOCHk_9_3_3'] > last['STOCHd_9_3_3']:
        results.append("✅ KD：K值大於D值 (多方攻擊)"); score += 1
    # 指標 3: MACD 紅柱
    if last['MACDs_12_26_9'] > 0:
        results.append("✅ MACD：位於零軸上方 (波段偏多)"); score += 1
    # 指標 4: RSI 強勢
    if last['RSI_14'] > 50:
        results.append("✅ RSI：站上強勢區 (買盤積極)"); score += 1
    # 指標 5: 布林中軸
    if last['Close'] > last['BBM_20_2.0']:
        results.append("✅ 布林：股價站穩中軸 (支撐確立)"); score += 1
        
    grade = {5: "S (極強)", 4: "A (強勢)", 3: "B (轉強)", 2: "C (盤整)", 1: "D (弱勢)", 0: "E (空方)"}.get(score, "E")
    
    # 策略建議
    strategy = "觀望為宜"
    if score >= 4: strategy = "分批佈局 / 持股續抱"
    elif score == 3: strategy = "少量試單 / 觀察突破"
    elif score <= 1: strategy = "減碼避險 / 找尋支撐"

    return {
        "price": float(last['Close']),
        "pct": (float(last['Close']) - float(prev['Close'])) / float(prev['Close']) * 100,
        "grade": grade,
        "details": results,
        "strategy": strategy,
        "score": score
    }

# --- 2. 介面與通知 ---

st.title("📈 台股 AI 技術分級監控")
status_label, is_open = get_market_status()
st.info(f"當前狀態：{status_label}")

with st.expander("🛠️ 系統設定"):
    # 新增股票
    c1, c2, c3 = st.columns([2,3,1])
    nid = c1.text_input("代號")
    nname = c2.text_input("名稱")
    if c3.button("新增"):
        if nid and nname:
            st.session_state.my_stocks.append({"id": nid, "name": nname})
            save_data(); st.rerun()
    
    st.divider()
    st.session_state.tg_token = st.text_input("Bot Token", type="password", value=st.session_state.tg_token)
    st.session_state.tg_chat_id = st.text_input("Chat ID", value=st.session_state.tg_chat_id)
    st.session_state.tg_threshold = st.number_input("通知門檻 %", value=st.session_state.tg_threshold)
    if st.button("💾 儲存並發送測試"):
        save_data()
        requests.post(f"https://api.telegram.org/bot{st.session_state.tg_token}/sendMessage", 
                      json={"chat_id": st.session_state.tg_chat_id, "text": "🔔 系統設定已更新並連線成功！"})

# --- 3. 監控顯示 ---

for idx, stock in enumerate(st.session_state.my_stocks):
    res = fetch_and_analyze(stock['id'])
    with st.container(border=True):
        if res:
            col1, col2 = st.columns([3, 2])
            with col1:
                st.subheader(f"{stock['name']} ({stock['id']})")
                st.markdown(f"**技術等級：`{res['grade']}`** ({res['score']}/5)")
            with col2:
                st.metric("股價", f"{res['price']:.2f}", f"{res['pct']:+.2f}%", delta_color="inverse")
            
            with st.expander("查看技術面細節"):
                for d in res['details']: st.write(d)
                st.warning(f"💡 策略建議：{res['strategy']}")
            
            if st.button("🗑️", key=f"del_{stock['id']}"):
                st.session_state.my_stocks.pop(idx); save_data(); st.rerun()

            # --- 自動通知邏輯 (方案 A) ---
            if is_open and abs(res['pct']) >= st.session_state.tg_threshold:
                key = f"{stock['id']}_{datetime.now(tw_tz).strftime('%Y%m%d')}"
                if key not in st.session_state.alert_history:
                    msg = (f"🚨 <b>【台股異動通知】</b>\n\n"
                           f"標的：{stock['name']} ({stock['id']})\n"
                           f"成交價：<b>{res['price']:.2f}</b>\n"
                           f"漲跌幅：<b>{res['pct']:+.2f}%</b>\n"
                           f"技術等級：<b>{res['grade']}</b>\n\n"
                           f"📊 <b>符合指標：</b>\n" + "\n".join(res['details']) + "\n\n"
                           f"💡 <b>策略建議：</b>\n{res['strategy']}")
                    
                    url = f"https://api.telegram.org/bot{st.session_state.tg_token}/sendMessage"
                    requests.post(url, json={"chat_id": st.session_state.tg_chat_id, "text": msg, "parse_mode": "HTML"})
                    st.session_state.alert_history[key] = True
                    st.toast(f"已發送 {stock['name']} 通知")
        else:
            st.error(f"無法讀取 {stock['id']}")

st.divider()
if st.button("🔄 立即刷新所有指標"):
    st.cache_data.clear(); st.rerun()
st.caption(f"最後更新：{datetime.now(tw_tz).strftime('%Y-%m-%d %H:%M:%S')}")
