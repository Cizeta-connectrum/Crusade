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
    
    try:
        cell = worksheet.find(name)
        row = cell.row
        # 更新
        worksheet.update_cell(row, 2, progress)
        worksheet.update_cell(row, 3, power)
        worksheet.update_cell(row, 4, answer)
        worksheet.update_cell(row, 5, dates_str)
        worksheet.update_cell(row, 6, now_str) # F列: 更新日時
        # G列: 上限回数 (列が存在するか確認せずに書き込む簡易実装。7列目と想定)
        worksheet.update_cell(row, 7, max_count) 
        return "更新"
    except gspread.exceptions.CellNotFound:
        # 新規追加
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
    delta = end_date - start_date
    return [start_date + timedelta(days=i) for i in range(delta.days + 1)]

# ---------------------------------------------------------
# 3. アプリ画面構成
# ---------------------------------------------------------
st.set_page_config(page_title="聖戦管理App", layout="wide")
st.title("🛡️ 聖戦メンバー管理 (多機能版)")

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
                row_data = df[df['名前'] == target_name].iloc[0]
                current_data = {
                    'progress': str(row_data.get('ステージ進捗', '')),
                    'power': str(row_data.get('戦力', '')),
                    'answer': str(row_data.get('回答内容', 'いつでも')),
                    'dates': str(row_data.get('指定日', '')).split(",") if row_data.get('指定日') else [],
                    'max_count': int(row_data.get('上限回数')) if pd.notna(row_data.get('上限回数')) and str(row_data.get('上限回数')).isdigit() else 14
                }
        else:
            st.info("データがありません。「新規メンバー登録」を行ってください。")
    else:
        input_name = st.text_input("新しいメンバー名を入力してください")
        current_data = {'progress': "40-60", 'power': "", 'answer': "いつでも", 'dates': [], 'max_count': 14}

    st.markdown("---")
    
    # === 入力フォーム ===
    # Session Stateを使って一時的なカレンダーチェック状態を管理
    if 'temp_dates' not in st.session_state:
        st.session_state['temp_dates'] = []

    # フォーム外で曜日選択などのインタラクションを行うためのエリア
    c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
    new_progress = c1.text_input("ステージ進捗", value=current_data.get('progress', ''))
    new_power = c2.text_input("戦力", value=current_data.get('power', ''))
    
    # 回答タイプの選択
    options = ["いつでも", "条件付き", "無理/辞退"]
    current_ans = current_data.get('answer', 'いつでも')
    try:
        idx = options.index(current_ans) if current_ans in options else 0
    except: idx = 0
    new_answer = c3.selectbox("回答タイプ", options, index=idx)

    # 回数制限
    default_max = current_data.get('max_count', 14)
    if new_answer == "無理/辞退": default_max = 0
    new_max_count = c4.number_input("上限回数 (2-3回等の場合に入力)", min_value=0, max_value=14, value=default_max)
    st.caption("※「期間を通して2〜3回」の場合は、ここに「3」と入力してください。")

    # === カレンダーUI ===
    selected_dates_result = []
    
    if new_answer == "条件付き":
        st.markdown("##### 📅 参加可能日を選択")
        
        # 曜日一括選択機能
        weekdays_map = {0: "月", 1: "火", 2: "水", 3: "木", 4: "金", 5: "土", 6: "日"}
        selected_weekdays = st.multiselect(
            "曜日で一括チェック (例: 木曜日のみ)", 
            options=list(weekdays_map.values()),
            help="ここを選ぶと、下のカレンダーの該当する曜日が自動でチェックされます"
        )
        
        # 初期値の計算 (DB保存値 OR 曜日選択)
        db_dates = current_data.get('dates', [])
        
        # カレンダーグリッド表示 (7列x2行程度)
        st.write("個別に日付を調整:")
        cols = st.columns(7)
        for i, d in enumerate(target_dates):
            d_str = d.strftime('%Y-%m-%d')
            wd_str = weekdays_map[d.weekday()]
            label = f"{d.strftime('%m/%d')}({wd_str})"
            
            # チェックボックスの初期値判定
            is_checked = False
            # 1. 曜日で指定されているか？
            if wd_str in selected_weekdays:
                is_checked = True
            # 2. 曜日指定がなく、DBに保存されているか？
            elif not selected_weekdays and d_str in db_dates:
                is_checked = True
            
            # グリッド配置
            with cols[i % 7]:
                if st.checkbox(label, value=is_checked, key=f"chk_{d_str}"):
                    selected_dates_result.append(d_str)

    elif new_answer == "いつでも":
        # 全日程を対象にする
        selected_dates_result = [d.strftime('%Y-%m-%d') for d in target_dates]

    # === 保存ボタン ===
    st.markdown("---")
    if st.button("上記の内容で保存して更新", type="primary"):
        if not input_name:
            st.error("エラー: メンバー名が入力されていません。")
        else:
            with st.spinner("スプレッドシートに書き込み中..."):
                try:
                    res = update_member_data(sheet_url, input_name, new_progress, new_power, new_answer, selected_dates_result, new_max_count)
                    st.success(f"完了: {input_name} さんの情報を{res}しました！")
                    st.cache_data.clear()
                except Exception as e:
                    st.error(f"書き込みエラー: {e}")

# -----------------
# Tab 2: 選抜実行
# -----------------
with tab_calc:
    st.header("メンバー選抜")
    mode = st.radio("選抜モード", ["戦力優先", "平等モード"], horizontal=True)
    
    if st.button("計算実行"):
        if df.empty:
            st.error("データがありません。")
        else:
            # 1. データ準備
            members_dict = {}
            for _, row in df.iterrows():
                ans = str(row.get('回答内容', 'いつでも'))
                dates_str = str(row.get('指定日', ''))
                
                # 上限回数の取得
                max_c = 14
                if '上限回数' in row and str(row['上限回数']).isdigit():
                    max_c = int(row['上限回数'])
                
                members_dict[row['名前']] = {
                    'progress': str(row.get('ステージ進捗', '')),
                    'power': str(row.get('戦力', '')),
                    'answer': ans,
                    'specific_dates': dates_str.split(",") if dates_str else [],
                    'max_count': max_c
                }
                
            # 2. ランキング作成 & 参加可能日判定
            ranked_members = []
            for name, data in members_dict.items():
                availability = {}
                for d in target_dates:
                    d_str = d.strftime('%Y-%m-%d')
                    is_ok = False
                    
                    if "無理" in data['answer'] or "辞退" in data['answer']:
                        is_ok = False
                    elif data['answer'] == "いつでも":
                        is_ok = True
                    elif data['answer'] == "条件付き":
                        if d_str in data['specific_dates']:
                            is_ok = True
                    
                    availability[d_str] = is_ok
                
                ranked_members.append({
                    'name': name,
                    'progress_val': parse_stage(data['progress']),
                    'power_val': parse_power(data['power']),
                    'availability': availability,
                    'max_count': data['max_count'],
                    'count': 0,
                    'status': {} 
                })
            
            # ソート: 進捗 > 戦力
            ranked_members.sort(key=lambda x: (x['progress_val'], x['power_val']), reverse=True)
            
            # 3. 固定・変動の振り分け
            fixed_members = []
            variable_candidates = []
            all_dates_keys = [d.strftime('%Y-%m-%d') for d in target_dates]
            
            for m in ranked_members:
                # 固定条件: トップ10以内 かつ 全日参加可能 かつ 上限回数が期間(14)以上
                is_all_ok = all(m['availability'][k] for k in all_dates_keys)
                if len(fixed_members) < 10 and is_all_ok and m['max_count'] >= len(target_dates):
                    fixed_members.append(m)
                else:
                    variable_candidates.append(m)
            
            # 4. 日ごとの選抜処理
            daily_schedule = {}
            
            for d in target_dates:
                d_str = d.strftime('%Y-%m-%d')
                todays_team = []
                
                # (A) 固定メンバー
                for fm in fixed_members:
                    todays_team.append(fm['name'])
                    fm['count'] += 1
                    fm['status'][d_str] = "◎"
                
                # (B) 変動枠
                slots_needed = 20 - len(todays_team)
                
                # その日の候補者抽出
                # 条件: 1.その日がOK  2.現在の上限回数に達していない
                todays_candidates = []
                for m in variable_candidates:
                    if m['availability'][d_str] and m['count'] < m['max_count']:
                        todays_candidates.append(m)
                
                # 選抜漏れ等のステータス初期化
                for m in variable_candidates:
                    if not m['availability'][d_str]:
                        m['status'][d_str] = "✕" # そもそも不可
                    elif m['count'] >= m['max_count']:
                        m['status'][d_str] = "済" # 回数制限到達
                    else:
                        m['status'][d_str] = "△" # 参加可能だが未選出
                
                if slots_needed > 0:
                    if mode == "平等モード":
                        todays_candidates.sort(key=lambda x: (x['count'], -x['progress_val'][0], -x['progress_val'][1], -x['power_val']))
                    
                    for c in todays_candidates[:slots_needed]:
                        todays_team.append(c['name'])
                        c['count'] += 1
                        c['status'][d_str] = "〇"
                
                daily_schedule[d_str] = todays_team

            # 5. 結果表示
            st.subheader("📊 選抜結果マトリクス表")
            st.caption("記号の意味： ◎=固定枠, 〇=変動枠, △=選考漏れ, 済=回数制限到達, ✕=不参加")

            matrix_data = []
            display_order = fixed_members + variable_candidates
            
            for m in display_order:
                row = {"名前": m['name'], "上限": m['max_count']}
                for d in target_dates:
                    d_str = d.strftime('%Y-%m-%d')
                    short_date = d.strftime('%m/%d')
                    row[short_date] = m['status'].get(d_str, "-")
                row["実績"] = m['count']
                matrix_data.append(row)
            
            df_matrix = pd.DataFrame(matrix_data)
            st.dataframe(df_matrix, use_container_width=True)

            # 6. コピー用テキスト
            st.markdown("---")
            st.subheader("📋 告知用コピーテキスト")
            
            fixed_names = [m['name'] for m in fixed_members]
            text_output = f"【固定メンバー】 ({len(fixed_names)}名)\n{', '.join(fixed_names)}\n\n"
            
            for d in target_dates:
                d_str = d.strftime('%Y-%m-%d')
                day_jp = ["月","火","水","木","金","土","日"][d.weekday()]
                mems = daily_schedule.get(d_str, [])
                text_output += f"■ {d.strftime('%m/%d')}({day_jp}) 参加メンバー ({len(mems)}名)\n{','.join(mems)}\n\n"
            
            st.text_area("以下のテキストを全選択してコピーしてください", text_output, height=300)

# -----------------
# Tab 3: 一覧確認
# -----------------
with tab_list:
    st.header("現在の登録状況")
    if st.button("データ再読み込み"):
        st.cache_data.clear()
        st.rerun()
    if not df.empty:
        st.dataframe(df)