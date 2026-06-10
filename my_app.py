import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import json
import os
import re
from supabase import create_client, Client  # 🔄 引入 Supabase 官方連線套件

# --- 1. 初始化與路徑設定 ---
st.set_page_config(page_title="Hinge 永久分析系統 v2", layout="wide")
DB_FILE = "hinge_data_v2.json"

CONTROL_LIMITS = {
    "Open 15-75": {"UCL": 13, "LCL": -15},
    "Open 75-120": {"UCL": 11, "LCL": -15},
    "Close 120-35": {"UCL": 19, "LCL": -13},
    "Close 35-15": {"UCL": 19, "LCL": -9}
}

# ==========================================
# 🔄 安全防護：初始化 Supabase 連線 (從雲端 Secrets 讀取)
# ==========================================
try:
    url: str = st.secrets["SUPABASE_URL"]
    key: str = st.secrets["SUPABASE_KEY"]
    supabase_client: Client = create_client(url, key)
    supabase_ready = True
except Exception as e:
    supabase_ready = False
    st.sidebar.warning(f"⚠️ Supabase 尚未連線（本地測試或金鑰未設定）：{e}")

# --- 2. 穩定的資料庫讀寫功能 ---
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
                return {k: pd.DataFrame.from_dict(v) for k, v in raw_data.items()}
        except Exception as e:
            st.error(f"資料庫讀取失敗，已建立新資料庫。錯誤: {e}")
            return {}
    return {}

def save_db(data_dict):
    serialized = {k: v.to_dict(orient='records') for k, v in data_dict.items()}
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(serialized, f, ensure_ascii=False, indent=4)

if 'samples_data' not in st.session_state:
    st.session_state.samples_data = load_db()

# --- 3. 數據處理核心 ---
def process_hinge_data(files):
    all_cycle_data = {}
    for file in files:
        try:
            df_raw = pd.read_csv(file, header=None) if file.name.endswith('.csv') else pd.read_excel(file, header=None)
            for col_idx in range(1, df_raw.shape[1], 3):
                cycle_name = ""
                for offset in [-1, 0, 1]:
                    if col_idx + offset < df_raw.shape[1]:
                        val = str(df_raw.iloc[0, col_idx + offset]).strip()
                        nums = re.findall(r'\d+', val)
                        if nums: 
                            cycle_name = nums[0]
                            break
                if not cycle_name: continue
                
                # 過濾 Cycle (只保留 1~20 以及 100 的倍數)
                cycle_num = int(cycle_name)
                if not ((1 <= cycle_num <= 20) or (cycle_num % 100 == 0)):
                    continue

                data_part = df_raw.iloc[2:, col_idx:col_idx+2]
                
                # 強制將 Load 值轉為絕對值 (.abs()) 確保衰退率計算正確
                load_col = pd.to_numeric(data_part.iloc[:, 0], errors='coerce').abs()
                dist_col = pd.to_numeric(data_part.iloc[:, 1], errors='coerce')
                
                temp_df = pd.DataFrame({'dist': dist_col, 'load': load_col}).dropna()
                temp_df = temp_df.reset_index(drop=True) 
                temp_df['dist_round'] = temp_df['dist'].round(1)
                
                if temp_df.empty: continue
                
                # ==========================================
                # 區分去程(Open)與回程(Close)
                # ==========================================
                max_idx = temp_df['dist'].idxmax()
                
                df_open = temp_df.loc[:max_idx].copy()
                df_open['Direction'] = 'Open'
                
                df_close = temp_df.loc[max_idx:].copy()
                df_close['Direction'] = 'Close'
                
                combined_df = pd.concat([df_open, df_close])
                resampled_df = combined_df[combined_df['dist_round'] % 0.5 == 0].drop_duplicates(subset=['dist_round', 'Direction'])
                all_cycle_data[cycle_name] = resampled_df
        except: continue
    return all_cycle_data

def get_interval_stats(df):
    ints = {
        "Open 15-75": (15, 75, 'Open'), 
        "Open 75-120": (75, 120, 'Open'), 
        "Close 120-35": (35, 120, 'Close'), 
        "Close 35-15": (15, 35, 'Close')
    }
    stats = {}
    for n, (l, h, direct) in ints.items():
        sub = df[(df['Direction'] == direct) & (df['dist_round'] >= l) & (df['dist_round'] <= h)]
        if not sub.empty:
            stats[f"{n}_Max"] = sub['load'].max()
            stats[f"{n}_Min"] = sub['load'].min()
            stats[f"{n}_Avg"] = sub['load'].mean()
        else:
            stats[f"{n}_Max"] = stats[f"{n}_Min"] = stats[f"{n}_Avg"] = 0
    return stats

def calculate_decay_rates(data_dict):
    sorted_cycles = sorted(data_dict.keys(), key=int)
    if not sorted_cycles:
        return pd.DataFrame()
        
    base_stats = get_interval_stats(data_dict[sorted_cycles[0]])
    results = []
    for cycle in sorted_cycles:
        current = get_interval_stats(data_dict[cycle])
        row = {"Cycle": int(cycle)}
        for k in base_stats.keys():
            v = current[k]
            row[k] = round(v, 2)
            bv = base_stats[k]
            row[f"{k}_衰退率%"] = round(((v - bv) / bv * 100), 2) if bv else 0.0
        results.append(row)
    return pd.DataFrame(results)

# --- 4. 介面與功能 ---
st.sidebar.title("📁 樣品資料庫管理")
all_names = list(st.session_state.samples_data.keys())

if all_names:
    st.sidebar.subheader("現有樣品清單")
    for old_name in all_names:
        with st.sidebar.expander(f"📦 {old_name}"):
            new_n = st.text_input("修改名稱", value=old_name, key=f"rename_{old_name}")
            if new_n != old_name and new_n not in st.session_state
