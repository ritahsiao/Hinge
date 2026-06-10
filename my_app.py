import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from supabase import create_client, Client

# ==========================================
# 1. 初始化 Supabase 連線 (從 Secrets 讀取)
# ==========================================
url: str = st.secrets["SUPABASE_URL"]
key: str = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(url, key)

st.title("🔬 實驗數據上傳與保存系統")

# ==========================================
# 2. 檔案上傳介面
# ==========================================
uploaded_file = st.file_uploader("請上傳您的原始資料 Excel 檔", type=["xlsx", "xls"])

if uploaded_file is not None:
    file_name = uploaded_file.name
    st.success(f"成功偵測到檔案：{file_name}")
    
    # 讀取 Excel (跳過第一列，因為第一列通常是組別 #1#, #2#)
    # 這裡會根據你實際的 Excel 結構微調，以下為標準轉換邏輯
    df_raw = pd.read_excel(uploaded_file)
    
    st.subheader("📊 原始上傳資料預覽")
    st.dataframe(df_raw.head())
    
    # ==========================================
    # 3. 核心：將橫向資料洗成「垂直規格」資料表
    # ==========================================
    # 這裡我們用一小段 Python 自動辨識你的 #1#, #2# 組別並拆解
    parsed_rows = []
    
    # 假設你的 Excel 最左邊是 'No' 欄位
    for index, row in df_raw.iterrows():
        no_val = row.get('No', index) # 如果沒找到 No 就用列索引
        
        # 每 3 欄為一組 (#1# Load, Distance, Time, #2# Load, Distance, Time...)
        # 根據你上傳的圖片，從第 1 欄開始每 3 個一組
        col_idx = 1
        group_num = 1
        
        while col_idx < len(df_raw.columns):
            try:
                # 抓取連續的三個欄位數值
                load_val = row.iloc[col_idx]
                dist_val = row.iloc[col_idx + 1] if (col_idx + 1) < len(df_raw.columns) else None
                time_val = row.iloc[col_idx + 2] if (col_idx + 2) < len(df_raw.columns) else None
                
                # 如果這組資料都是空的，就跳過
                if pd.isna(load_val) and pd.isna(dist_val) and pd.isna(time_val):
                    col_idx += 3
                    group_num += 1
                    continue
                
                # 組裝成符合資料庫的格式
                parsed_rows.append({
                    "file_name": file_name,
                    "no": int(no_val),
                    "group_name": f"#{group_num}#",
                    "load": float(load_val) if not pd.isna(load_val) else None,
                    "distance": float(dist_val) if not pd.isna(dist_val) else None,
                    "time": float(time_val) if not pd.isna(time_val) else None
                })
            except Exception as e:
                pass
            
            col_idx += 3
            group_num += 1

    # 轉成 DataFrame
    df_ready = pd.DataFrame(parsed_rows)
    
    # ==========================================
    # 4. 按下按鈕，將清洗後的資料寫入 Supabase
    # ==========================================
    if st.button("🚀 將數據清洗並保存至 Supabase 資料庫"):
        with st.spinner("正在努力上傳大量數據中，請稍候..."):
            try:
                # 將 dataframe 轉成 json 字典格式，這是 Supabase 接受的批次寫入格式
                data_to_insert = df_ready.to_dict(orient="records")
                
                # 批次寫入名為 'experiment_data' 的 Table 中
                # 注意：如果資料量極大（好幾萬筆），建議分批上傳，這裡先做標準寫入
                response = supabase.table("experiment_data").insert(data_to_insert).execute()
                
                st.balloons()
                st.success("🎉 資料成功清洗並永久保存至 Supabase 資料庫！")
            except Exception as e:
                st.error(f"上傳失敗，錯誤訊息：{e}")

# ==========================================
# 5. 顯示資料庫內的所有資料與繪圖
# ==========================================
st.markdown("---")
st.subheader("🗂️ 目前保存在雲端資料庫的歷史數據")

if st.button("🔄 重新整理並讀取最新資料庫內容"):
    try:
        # 從 Supabase 下載資料 (預設抓最新 1000 筆，你可以移除 limit 抓全部)
        res = supabase.table("experiment_data").select("*").order("uploaded_at", descending=True).limit(1000).execute()
        
        if res.data:
            df_db = pd.DataFrame(res.data)
            
            # 在網頁上顯示資料庫內容
            st.dataframe(df_db)
            
            # 使用 Plotly 畫個簡單的折線圖
            st.subheader("📈 雲端數據即時視覺化 (以 Load 為例)")
            fig = px.line(df_db, x="no", y="load", color="group_name", facet_col="file_name",
                          title="各檔案與組別的 Load 變化趨勢")
            st.plotly_chart(fig)
        else:
            st.info("目前資料庫中還沒有任何數據，請先從上方上傳檔案！")
            
    except Exception as e:
        st.error(f"讀取資料庫時發生錯誤：{e}")
