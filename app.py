import streamlit as st
import pandas as pd
from datetime import datetime
import numpy as np

# --- 頁面配置 ---
st.set_page_config(page_title="SOFC 升溫研發夥伴", layout="wide")

# 初始化 session_state (用於存儲歷史數據與日誌)
if 'history' not in st.session_state:
    st.session_state.history = []
if 'config_log' not in st.session_state:
    st.session_state.config_log = []
if 'last_config' not in st.session_state:
    st.session_state.last_config = {}

st.title("🛡️ SOFC 高溫燃料電池：動態升溫決策系統")
st.markdown("針對尾燃器加熱迴路設計，基於 **TC1(尾燃器出口)**、**TC3(陰極出口)** 與 **T2(陰極入口)** 的熱連鎖控制。")

# --- 1. 側邊欄：邊界條件設定與日誌 ---
with st.sidebar:
    st.header("⚙️ 邊界條件設定")
    
    target_slope = st.slider("目標升溫速率 (℃/min)", 0.3, 1.5, 0.7, step=0.1)
    max_stack_dt = st.number_input("電堆出入口最大溫差 |TC3-T2| (℃)", value=100)
    max_ab_dt = st.number_input("尾燃器與陰極最大溫差 (TC1-TC3) (℃)", value=170)
    min_air_flow = st.number_input("空氣最小流量 (lpm)", value=500)

    # 監控邊界條件變動並記錄
    current_config = {
        "目標速率": target_slope,
        "電堆溫差限制": max_stack_dt,
        "尾燃器溫差限制": max_ab_dt
    }
    
    if st.session_state.last_config and current_config != st.session_state.last_config:
        for key in current_config:
            if current_config[key] != st.session_state.last_config.get(key):
                st.session_state.config_log.insert(0, {
                    "時間": datetime.now().strftime("%H:%M:%S"),
                    "變更項目": key,
                    "舊值": st.session_state.last_config.get(key),
                    "新值": current_config[key]
                })
    st.session_state.last_config = current_config

    st.divider()
    st.subheader("📜 邊界變動歷史")
    if st.session_state.config_log:
        st.table(pd.DataFrame(st.session_state.config_log))
    else:
        st.write("目前無變動紀錄")

# --- 2. 核心計算邏輯 (自適應黑盒子模型) ---
def calculate_next_step(curr, last):
    # 計算時間差 (分鐘)
    dt = (curr['time'] - last['time']).total_seconds() / 60.0
    if dt <= 0: return curr['h2'], curr['air'], "等待下一次採樣...", 0
    
    # 物理增益系數 (由 csv 數據初步擬合)
    H2_GAIN = 0.20  # 每 1 lpm H2 對升溫速率的貢獻
    
    # 目前狀態分析
    actual_slope = (curr['tc3'] - last['tc3']) / dt
    stack_dt = abs(curr['tc3'] - curr['t2'])
    ab_dt = curr['tc1'] - curr['tc3']
    
    # A. 氫氣調整：追蹤目標升溫速率
    slope_error = target_slope - actual_slope
    h2_adjustment = slope_error / H2_GAIN
    suggested_h2 = max(0.0, curr['h2'] + h2_adjustment)
    
    # B. 空氣調整：保護溫差限制
    suggested_air = curr['air']
    status_msg = "系統運行穩定，微調氫氣"

    # 邏輯 1: 尾燃器熱應力保護 (TC1-TC3)
    if ab_dt > (max_ab_dt - 10): # 接近 170C
        suggested_h2 = min(suggested_h2, curr['h2'] * 0.95) # 強制壓低 H2
        suggested_air += 50
        status_msg = "🚨 觸發尾燃器溫差保護：調減 H2 並調增空氣"
    
    # 邏輯 2: 電堆內部熱應力保護 (|TC3-T2|)
    if stack_dt > (max_stack_dt - 15):
        suggested_air += 100
        status_msg = "⚠️ 觸發電堆溫差保護：增加空氣流量以均勻溫度"
        
    return round(suggested_h2, 2), round(max(suggested_air, min_air_flow), 1), status_msg, actual_slope

# --- 3. 數據輸入介面 ---
st.subheader("📥 當前系統狀態輸入")
with st.form("manual_input"):
    c1, c2, c3 = st.columns(3)
    with c1:
        in_h2 = st.number_input("燃料氫氣流量 (lpm)", value=10.0, step=0.1)
        in_air = st.number_input("空氣流量 (lpm)", value=800.0, step=10.0)
    with c2:
        in_t2 = st.number_input("電堆陰極入口 T2 (℃)", value=300.0)
        in_tc3 = st.number_input("電堆陰極出口 TC3 (℃)", value=280.0)
    with c3:
        in_tc1 = st.number_input("尾燃器出口 TC1 (℃)", value=430.0)
        in_pa = st.number_input("陽極壓力 (kPa)", value=1.0)
        in_pc = st.number_input("陰極壓力 (kPa)", value=2.0)
    
    btn = st.form_submit_button("⚖️ 執行模型診斷並獲取建議")

# --- 4. 結果輸出 ---
if btn:
    current_entry = {
        'time': datetime.now(),
        'h2': in_h2, 'air': in_air, 
        't2': in_t2, 'tc3': in_tc3, 'tc1': in_tc1
    }
    
    if st.session_state.history:
        last_entry = st.session_state.history[-1]
        next_h2, next_air, msg, a_slope = calculate_next_step(current_entry, last_entry)
        
        st.divider()
        st.subheader("🎯 調整建議 (下階段)")
        r1, r2, r3 = st.columns(3)
        r1.metric("氫氣流量建議", f"{next_h2} lpm", delta=f"{round(next_h2-in_h2, 2)}")
        r2.metric("空氣流量建議", f"{next_air} lpm", delta=f"{round(next_air-in_air, 1)}")
        r3.metric("當前升溫速率", f"{round(a_slope, 2)} ℃/min")
        
        if "🚨" in msg or "⚠️" in msg:
            st.error(msg)
        else:
            st.success(msg)
            
    st.session_state.history.append(current_entry)
    if len(st.session_state.history) > 20: # 僅保留最近 20 筆
        st.session_state.history.pop(0)

# 顯示趨勢提醒
if len(st.session_state.history) > 1:
    st.caption("註：建議值基於黑盒子模型動態擬合，請依現場實際安全狀況操作。")
