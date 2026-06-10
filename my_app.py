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
            if new_n != old_name and new_n not in st.session_state.samples_data:
                st.session_state.samples_data[new_n] = st.session_state.samples_data.pop(old_name)
                save_db(st.session_state.samples_data)
                st.rerun()
            if st.button("🗑️ 刪除", key=f"del_{old_name}"):
                del st.session_state.samples_data[old_name]
                save_db(st.session_state.samples_data)
                st.rerun()

st.title("🔩 Hinge 壽命測試數據系統")
tab1, tab2 = st.tabs(["📥 數據上傳", "📊 數據看板"])

with tab1:
    st.subheader("新增樣品數據")
    s_name = st.text_input("樣品名稱", value=f"Sample_{len(all_names)+1}")
    files = st.file_uploader("選擇該樣品的 Excel/CSV 檔案", type=["csv", "xlsx"], accept_multiple_files=True)
    
    if st.button("🚀 執行分析並存入資料庫") and files:
        with st.spinner("數據轉換中..."):
            raw_dict = process_hinge_data(files)
            if raw_dict:
                decay_df = calculate_decay_rates(raw_dict)
                
                # 保留原本的本地端的運作流程 (不破壞任何畫面)
                st.session_state.samples_data[s_name] = decay_df
                save_db(st.session_state.samples_data)
                
                # 🔄 【全新擴充】同步上傳一份到 Supabase 雲端資料庫 (拆解為標準垂直規格)
                if supabase_ready:
                    try:
                        parsed_supabase_rows = []
                        all_intervals = ["Open 15-75", "Open 75-120", "Close 120-35", "Close 35-15"]
                        all_metrics = ["Max", "Min", "Avg", "Max_衰退率%", "Min_衰退率%", "Avg_衰退率%"]
                        
                        for index, row in decay_df.iterrows():
                            current_cycle = int(row['Cycle'])
                            
                            for inv in all_intervals:
                                for m in all_metrics:
                                    col_name = f"{inv}_{m}"
                                    if col_name in decay_df.columns:
                                        val = row[col_name]
                                        parsed_supabase_rows.append({
                                            "sample_name": s_name,
                                            "cycle": current_cycle,
                                            "interval_name": inv,
                                            "metric_type": m,
                                            "value": float(val) if pd.notna(val) else None
                                        })
                        
                        # 批次寫入名為 'hinge' 的資料表中
                        if parsed_supabase_rows:
                            supabase_client.table("hinge").insert(parsed_supabase_rows).execute()
                            st.sidebar.success(f"☁️ {s_name} 已同步至 Supabase！")
                            
                    except Exception as e:
                        st.sidebar.error(f"❌ Supabase 同步失敗 (不影響本地運作)：{e}")
                
                st.success(f"✅ {s_name} 已成功存檔！")
                st.rerun()
            else:
                st.error("無法解析檔案內容，請確認檔案格式是否正確。")

with tab2:
    if not st.session_state.samples_data:
        st.warning("目前無數據，請先上傳。")
    else:
        sel_sample = st.selectbox("🔍 檢見樣品詳細趨勢：", all_names)
        df_view = st.session_state.samples_data[sel_sample]
        
        intervals = ["Open 15-75", "Open 75-120", "Close 120-35", "Close 35-15"]
        sel_int = st.selectbox("選擇角度區間：", intervals)
        
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=df_view['Cycle'], y=df_view[f"{sel_int}_Avg_衰退率%"], name='Avg%', line=dict(color='#10B981', width=3)))
        fig1.add_trace(go.Scatter(x=df_view['Cycle'], y=df_view[f"{sel_int}_Max_衰退率%"], name='Max%', line=dict(color='#EF4444', dash='dot')))
        fig1.add_trace(go.Scatter(x=df_view['Cycle'], y=df_view[f"{sel_int}_Min_衰退率%"], name='Min%', line=dict(color='#3B82F6', dash='dot')))
        fig1.add_hline(y=0, line_dash="dash", line_color="gray")
        fig1.update_layout(title=f"{sel_sample} - {sel_int} 衰退趨勢", xaxis_title="Cycles", yaxis_title="變化率 (%)")
        st.plotly_chart(fig1, use_container_width=True)

        st.divider()

        # ==========================================
        # GQC判定表 (各區間全局衰退極值)
        # ==========================================
        st.subheader("📋 GQC判定表 (各區間全局衰退極值)")
        
        summary_rows = []
        all_intervals = ["Open 15-75", "Open 75-120", "Close 120-35", "Close 35-15"]
        all_metrics = ["Max", "Min", "Avg"]

        for sn, sdf in st.session_state.samples_data.items():
            row_data = {"Sample": sn}
            for inv in all_intervals:
                for m in all_metrics:
                    col_name = f"{inv}_{m}_衰退率%"
                    if col_name in sdf.columns:
                        row_data[f"{inv}_{m}_MAX"] = f"{sdf[col_name].max():.2f}%"
                        row_data[f"{inv}_{m}_MIN"] = f"{sdf[col_name].min():.2f}%"
            summary_rows.append(row_data)

        if summary_rows:
            df_summary = pd.DataFrame(summary_rows)
            df_summary.set_index("Sample", inplace=True)
            
            multi_cols = []
            for inv in all_intervals:
                angle = inv.split(' ')[1] 
                for m in all_metrics:
                    group_name = f"T0 Torque data(%)-{m}({angle})"
                    multi_cols.append((group_name, "MAX"))
                    multi_cols.append((group_name, "MIN"))
            
            df_summary.columns = pd.MultiIndex.from_tuples(multi_cols)
            st.dataframe(df_summary, use_container_width=True)

        st.divider()

        # ==========================================
        # SPC 看板
        # ==========================================
        st.subheader("📉 多樣品極值 SPC 管制圖")
        metric = st.radio("檢視指標：", ["Max", "Min", "Avg"], horizontal=True)
        extreme_type = st.radio("極值類型：", ["全局最大值 (MAX)", "全局最小值 (MIN)"], horizontal=True)
        
        col_key = f"{sel_int}_{metric}_衰退率%"
        
        spc_data = []
        for sn, sdf in st.session_state.samples_data.items():
            if col_key in sdf.columns:
                if "MAX" in extreme_type:
                    peak_val = sdf[col_key].max()
                else:
                    peak_val = sdf[col_key].min()
                
                if pd.notna(peak_val):
                    spc_data.append({"Sample": sn, "Peak_Change": peak_val})
                
        if len(spc_data) == 0:
            st.warning(f"⚠️ 找不到對應的數據可繪製，請確認此區間 ({sel_int}) 是否有資料。")
        else:
            spc_df = pd.DataFrame(spc_data)
            spc_df['Peak_Change'] = pd.to_numeric(spc_df['Peak_Change'], errors='coerce')

            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(
                x=spc_df['Sample'], 
                y=spc_df['Peak_Change'], 
                mode='lines+markers+text', 
                name='樣品極值', 
                marker=dict(size=12),
                text=spc_df['Peak_Change'].apply(lambda x: f"{x:.2f}%" if pd.notna(x) else ""),
                textposition="top center"
            ))
            
            limits = CONTROL_LIMITS.get(sel_int, {"UCL": 15, "LCL": -15})
            ucl, lcl = limits.get("UCL", 15), limits.get("LCL", -15)
            
            fig2.add_hline(y=ucl, line_dash="dash", line_color="red", annotation_text=f"UCL +{ucl}%")
            fig2.add_hline(y=lcl, line_dash="dash", line_color="red", annotation_text=f"LCL {lcl}%")
            
            y_max = max(spc_df['Peak_Change'].max() + 3, ucl + 3)
            y_min = min(spc_df['Peak_Change'].min() - 3, lcl - 3)
            
            fig2.update_layout(
                yaxis_title="最大/最小變化率 (%)",
                yaxis=dict(range=[y_min, y_max])
            )
            st.plotly_chart(fig2, use_container_width=True)
