import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta, timezone
import re

# ---------------------------------------------------------
# 1. Google Sheets 接続設定
# ---------------------------------------------------------
def get_gspread_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

def load_data(sheet_url):
    client = get_gspread_client()
    sh = client.open_by_url(sheet_url)
    worksheet = sh.get_worksheet(0)
    data = worksheet.get_all_records()
    if not data:
        return pd.DataFrame(columns=['名前', 'ステージ進捗', '戦力', '回答内容', '指定日', '上限回数', '更新日時'])
    return pd.DataFrame(data)

def update_member_data(sheet_url, name, progress, power, answer, specific_dates, max_count):
    client = get_gspread_client()
    sh = client.open_by_url(sheet_url)
    worksheet = sh.get_worksheet(0)
    
    # JST設定
    JST = timezone(timedelta(hours=9), 'JST')
    now_str = datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
    
    dates_str = ",".join(specific_dates)
    
    # A列（名前の列）をすべて取得して検索
    name_list = worksheet.col_values(1)
    
    try:
        # スプレッドシートは1行目が見出し、データは2行目から。col_valuesも1番目が1行目。
        # リストのインデックス(0始まり) + 1 で行番号になる
        row = name_list.index(name) + 1
        
        worksheet.update_cell(row, 2, progress)
        worksheet.update_cell(row, 3, power)
        worksheet.update_cell(row, 4, answer)
        worksheet.update_cell(row, 5, dates_str)
        worksheet.update_cell(row, 6, now_str)
        worksheet.update_cell(row, 7, max_count)
        return "更新"
        
    except ValueError:
        # 見つからない場合は新規登録
        worksheet.append_row([name, progress, power, answer, dates_str, now_str, max_count])
        return "新規登録"

# ---------------------------------------------------------
# 2. 計算・変換ロジック
# ---------------------------------------------------------
def parse_stage(stage_str):
    if not isinstance(stage_str, str): return (0, 0)
    stage_str = stage_str.strip().replace('‐', '-').replace('−', '-')
    match = re.match(r'(\d+)[^0-9]+(\d+)', stage_str)
    if match: return (int(match.group(1)), int(match.group(2)))
    match_single = re.match(r'(\d+)', stage_str)
    if match_single: return (int(match_single.group(1)), 0)
    return (0, 0)

def parse_power(power_val):
    if pd.isna(power_val) or power_val == '': return 0.0
    s = str(power_val).upper().replace(',', '').replace('"', '').strip()
    if 'M' in s: return float(s.replace('M', '')) * 1_000_000
    elif 'K' in s: return float(s.replace('K', '')) * 1_000
    try: return float(s)
    except: return 0.0

def generate_date_range(start_date, end_date):
    """開始日から終了日までの日付リストを生成"""
    delta = end_date - start_date
    dates = []
    for i in range(delta.days + 1):
        d = start_date + timedelta(days=i)
        if d.weekday() != 6: # 6は日曜日。日曜以外を追加
            dates.append(d)
    return dates

# ---------------------------------------------------------
# 3. アプリ画面構成
# ---------------------------------------------------------
st.set_page_config(page_title="聖戦管理App", layout="wide")
st.title("🛡️ 聖戦メンバー管理")

# --- 設定 ---
if "sheet_url" in st.secrets:
    sheet_url = st.secrets["sheet_url"]
else:
    sheet_url = st.sidebar.text_input("スプレッドシートのURLを貼ってください")

if not sheet_url:
    st.warning("スプレッドシートのURLが設定されていません。")
    st.stop()

# 期間設定
col_d1, col_d2 = st.sidebar.columns(2)
start_date = col_d1.date_input("開始日", datetime.today())
end_date = col_d2.date_input("終了日", datetime.today() + timedelta(days=13))

# 日付リスト生成（日曜除外済み）
target_dates = generate_date_range(start_date, end_date)

# --- データ読み込み ---
try:
    df = load_data(sheet_url)
except Exception as e:
    st.error(f"データ読み込みエラー: {e}")
    st.stop()

# --- タブ構成 ---
tab_input, tab_calc, tab_list = st.tabs(["📝 メンバー入力", "🚀 選抜実行", "📊 一覧確認"])

# -----------------
# Tab 1: 入力画面
# -----------------
with tab_input:
    st.header("情報の登録・更新")
    
    existing_names = df['名前'].tolist() if not df.empty and '名前' in df.columns else []
    select_mode = st.radio("モード", ["既存メンバーを編集", "新規メンバー登録"], horizontal=True)
    
    input_name = ""
    current_data = {}
    
    # 既存データ取得
    if select_mode == "既存メンバーを編集":
        if existing_names:
            target_name = st.selectbox("名前を選択", existing_names)
            input_name = target_name
            if not df.empty:
                rows = df[df['名前'] == target_name]
                if not rows.empty:
                    row_data = rows.iloc[0]
                    current_data = {
                        'progress': str(row_data.get('ステージ進捗', '')),
                        'power': str(row_data.get('戦力', '')),
                        'answer': str(row_data.get('回答内容', 'いつでも')),
                        'dates': str(row_data.get('指定日', '')).split(",") if row_data.get('指定日') else [],
                        'max_count': int(row_data.get('上限回数')) if pd.notna(row_data.get('上限回数')) and str(row_data.get('上限回数')).isdigit() else len(target_dates)
                    }
        else:
            st.info("データがありません。「新規メンバー登録」を行ってください。")
    else:
        input_name = st.text_input("新しいメンバー名を入力してください")
        current_data = {'progress': "40-60", 'power': "", 'answer': "いつでも", 'dates': [], 'max_count': len(target_dates)}

    st.markdown("---")
    
    # === 入力フォーム ===
    form_key_suffix = f"_{input_name}" if input_name else "_new"

    c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
    
    new_progress = c1.text_input("ステージ進捗", value=current_data.get('progress', ''), key=f"prog{form_key_suffix}")
    new_power = c2.text_input("戦力", value=current_data.get('power', ''), key=f"pow{form_key_suffix}")
    
    options = ["いつでも", "条件付き", "無理/辞退"]
    current_ans = current_data.get('answer', 'いつでも')
    try:
        idx = options.index(current_ans) if current_ans in options else 0
    except: idx = 0
    new_answer = c3.selectbox("回答タイプ", options, index=idx, key=f"ans{form_key_suffix}")

    # --- 修正箇所 start ---
    # 上限回数のデフォルト値（日曜除外後の日数）
    max_limit = len(target_dates)
    
    # DBから値を取得。なければ max_limit
    raw_max = current_data.get('max_count', max_limit)
    
    # 辞退なら0
    if new_answer == "無理/辞退":
        default_max = 0
    else:
        # DBの値が現在の期間(max_limit)より大きい場合、max_limit に丸める（エラー回避）
        default_max = min(raw_max, max_limit)

    # 入力上限も日曜除外後の日数に合わせる
    new_max_count = c4.number_input("上限回数", min_value=0, max_value=max_limit, value=default_max, key=f"max{form_key_suffix}")
    # --- 修正箇所 end ---
    
    st.caption("※「期間を通して2〜3回」