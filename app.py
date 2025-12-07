import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import re

# ---------------------------------------------------------
# 1. Google Sheets 接続設定
# ---------------------------------------------------------
# StreamlitのSecretsから認証情報を取得して接続する関数
def get_gspread_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    # secrets.toml の形式に合わせて辞書を作成
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

# シートのデータを全取得してDataFrameにする関数
def load_data(sheet_url):
    client = get_gspread_client()
    sh = client.open_by_url(sheet_url)
    worksheet = sh.get_worksheet(0) # 1枚目のシート
    data = worksheet.get_all_records()
    return pd.DataFrame(data)

# データを更新・追加する関数
def update_member_data(sheet_url, name, progress, power, answer, specific_dates):
    client = get_gspread_client()
    sh = client.open_by_url(sheet_url)
    worksheet = sh.get_worksheet(0)
    
    # 全データを取得して、該当する名前の行を探す
    records = worksheet.get_all_records()
    cell = worksheet.find(name)
    
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    dates_str = ",".join(specific_dates)
    
    if cell:
        # 更新 (行番号は cell.row)
        row = cell.row
        worksheet.update_cell(row, 2, progress) # B列:進捗
        worksheet.update_cell(row, 3, power)    # C列:戦力
        worksheet.update_cell(row, 4, answer)   # D列:回答
        worksheet.update_cell(row, 5, dates_str)# E列:指定日
        worksheet.update_cell(row, 6, now_str)  # F列:更新日時
        return "更新"
    else:
        # 新規追加
        worksheet.append_row([name, progress, power, answer, dates_str, now_str])
        return "新規登録"

# ---------------------------------------------------------
# 2. 計算ロジック (前回と同じ)
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
    delta = end_date - start_date
    return [start_date + timedelta(days=i) for i in range(delta.days + 1)]

# ---------------------------------------------------------
# 3. アプリ画面構成
# ---------------------------------------------------------
st.set_page_config(page_title="聖戦管理App", layout="wide")
st.title("🛡️ 聖戦メンバー管理 (クラウド版)")

# サイドバー設定
st.sidebar.header("設定")
# シートURLはSecretsから取るか、入力させるか。今回はSecrets推奨だが、簡易的に入力欄へ
# しかし、毎回入力は面倒なのでSecretsに入れておく前提にします。
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
target_dates = generate_date_range(start_date, end_date)

# --- データ読み込み ---
try:
    df = load_data(sheet_url)
    st.toast("最新データを読み込みました", icon="✅")
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
    st.caption("ここで入力すると、Googleスプレッドシートが自動更新されます。")
    
    # 名前選択（新規 or 既存）
    existing_names = df['名前'].tolist() if not df.empty else []
    select_mode = st.radio("モード", ["既存メンバーを編集", "新規メンバー登録"], horizontal=True)
    
    input_name = ""
    current_data = {}
    
    if select_mode == "既存メンバーを編集":
        if existing_names:
            target_name = st.selectbox("名前を選択", existing_names)
            # 既存データの取得
            row_data = df[df['名前'] == target_name].iloc[0]
            input_name = target_name
            current_data = {
                'progress': str(row_data['ステージ進捗']),
                'power': str(row_data['戦力']),
                'answer': str(row_data['回答内容']),
                'dates': str(row_data['指定日']).split(",") if str(row_data['指定日']) else []
            }
        else:
            st.info("データがありません。新規登録してください。")
    else:
        input_name = st.text_input("新しいメンバー名を入力")
        current_data = {'progress': "40-60", 'power': "", 'answer': "いつでも", 'dates': []}

    # 入力フォーム
    if input_name:
        with st.form("entry_form"):
            c1, c2, c3 = st.columns(3)
            new_progress = c1.text_input("ステージ進捗", value=current_data.get('progress', ''))
            new_power = c2.text_input("戦力", value=current_data.get('power', ''))
            new_answer = c3.radio("回答", ["いつでも", "日にち指定", "無理/辞退"], 
                                  index=["いつでも", "日にち指定", "無理/辞退"].index(current_data.get('answer', 'いつでも')))
            
            # 日付選択
            date_options = [d.strftime('%Y-%m-%d') for d in target_dates]
            # 過去に入力された日付が期間外の場合のハンドリングは簡易的に無視
            default_dates = [d for d in current_data.get('dates', []) if d in date_options]
            
            new_dates = []
            if new_answer == "日にち指定":
                new_dates = st.multiselect("参加可能日", date_options, default=default_dates)
            
            submitted = st.form_submit_button("保存して更新")
            
            if submitted:
                with st.spinner("スプレッドシートに書き込み中..."):
                    res = update_member_data(sheet_url, input_name, new_progress, new_power, new_answer, new_dates)
                    st.success(f"{input_name} さんの情報を{res}しました！")
                    st.cache_data.clear() # キャッシュクリアして再読み込みを促す
                    # st.rerun() # 必要に応じて

# -----------------
# Tab 2: 選抜実行
# -----------------
with tab_calc:
    st.header("メンバー選抜")
    mode = st.radio("選抜モード", ["戦力優先", "平等モード"], horizontal=True)
    
    if st.button("計算実行"):
        # データフレームから辞書形式に変換してロジックに渡す
        members_dict = {}
        for _, row in df.iterrows():
            members_dict[row['名前']] = {
                'progress': str(row['ステージ進捗']),
                'power': str(row['戦力']),
                'answer': str(row['回答内容']),
                'specific_dates': str(row['指定日']).split(",") if row['指定日'] else []
            }
            
        # ロジック実行（前回のコードを流用・短縮化）
        ranked_members = []
        for name, data in members_dict.items():
            availability = {}
            for d in target_dates:
                d_str = d.strftime('%Y-%m-%d')
                is_ok = False
                if data['answer'] == "いつでも": is_ok = True
                elif data['answer'] == "無理/辞退": is_ok = False
                elif data['answer'] == "日にち指定" and d_str in data['specific_dates']: is_ok = True
                availability[d_str] = is_ok
            
            ranked_members.append({
                'name': name,
                'progress_val': parse_stage(data['progress']),
                'power_val': parse_power(data['power']),
                'availability': availability,
                'count': 0
            })
        
        # ソート: 進捗 > 戦力
        ranked_members.sort(key=lambda x: (x['progress_val'], x['power_val']), reverse=True)
        
        # 選抜処理
        fixed_members = []
        variable_candidates = []
        all_dates_keys = [d.strftime('%Y-%m-%d') for d in target_dates]
        
        for m in ranked_members:
            if len(fixed_members) < 10 and all(m['availability'][k] for k in all_dates_keys):
                fixed_members.append(m)
            else:
                variable_candidates.append(m)
                
        daily_schedule = {}
        for d in target_dates:
            d_str = d.strftime('%Y-%m-%d')
            todays_team = [fm['name'] for fm in fixed_members]
            for fm in fixed_members: fm['count'] += 1
            
            slots_needed = 20 - len(todays_team)
            if slots_needed > 0:
                cands = [m for m in variable_candidates if m['availability'][d_str]]
                if mode == "平等モード":
                    cands.sort(key=lambda x: (x['count'], -x['progress_val'][0], -x['progress_val'][1], -x['power_val']))
                
                for c in cands[:slots_needed]:
                    todays_team.append(c['name'])
                    c['count'] += 1
            daily_schedule[d_str] = todays_team
            
        # 結果表示
        st.subheader("結果出力")
        text_output = f"固定メンバー: {', '.join([m['name'] for m in fixed_members])}\n\n"
        for d in target_dates:
            d_str = d.strftime('%Y-%m-%d')
            day_jp = ["月","火","水","木","金","土","日"][d.weekday()]
            mems = daily_schedule.get(d_str, [])
            text_output += f"{d.strftime('%m/%d')}({day_jp}) {len(mems)}名\n{','.join(mems)}\n\n"
        
        st.text_area("コピー用", text_output, height=300)

# -----------------
# Tab 3: 一覧確認
# -----------------
with tab_list:
    st.header("現在の登録状況")
    if not df.empty:
        # 見やすいように加工
        show_df = df.copy()
        st.dataframe(show_df)
    else:
        st.warning("データがまだありません。")