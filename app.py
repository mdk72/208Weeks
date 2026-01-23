import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go
import os
import pytz
from concurrent.futures import ThreadPoolExecutor, as_completed
import warnings

# Suppress external library warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated as an API.*")

# Custom Modules
from utils import load_settings, save_settings
from data_loader import init_db, fetch_data, get_stock_list_naver, CACHE_DB
from analyzer import analyze_stock_core, calculate_screener_performance, process_backtest_stock

# --- UI Setup ---
st.set_page_config(page_title="208-Week System", layout="wide")

# [UI] Custom CSS for Minimalist Design
st.markdown("""
<style>
    /* 1. Global Reset & Font */
    html, body, [class*="css"] {
        font-family: 'Pretendard', -apple-system, system-ui, sans-serif;
        color: #212529;
    }
    
    /* 2. Layout & Spacing (Reduce Whitespace) */
    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 2rem !important;
        max-width: 95% !important;
    }
    div[data-testid="stVerticalBlock"] > div {
        gap: 0.8rem !important; /* Tighten vertical spacing */
    }
    
    /* 3. Headers */
    h1 { font-size: 1.8rem !important; font-weight: 700; margin-bottom: 0.5rem !important; letter-spacing: -0.02em; }
    h2 { font-size: 1.4rem !important; font-weight: 600; margin-top: 1.5rem !important; margin-bottom: 0.5rem !important; border-bottom: 1px solid #eee; padding-bottom: 0.3rem; }
    h3 { font-size: 1.1rem !important; font-weight: 600; margin-top: 1rem !important; margin-bottom: 0.3rem !important; color: #495057; }
    
    /* 4. Buttons (Compact & Professional) */
    div.stButton > button {
        background-color: #f8f9fa; 
        border: 1px solid #ced4da;
        color: #495057;
        font-size: 0.9rem;
        padding: 0.3rem 0.8rem;
        border-radius: 4px;
        transition: all 0.2s;
    }
    div.stButton > button:hover {
        background-color: #e9ecef; border-color: #adb5bd; color: #212529;
        box-shadow: none;
    }
    div.stButton > button:active {
        background-color: #dee2e6; transform: translateY(1px);
    }
    
    /* 5. Metrics */
    div[data-testid="stMetricValue"] {
        font-size: 1.6rem !important; font-weight: 600; color: #212529;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.9rem !important; color: #868e96; font-weight: 500;
    }
    
    /* 6. Tabs (Pill Style) */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px; background-color: #f1f3f5; padding: 4px; border-radius: 8px; border-bottom: none;
    }
    .stTabs [data-baseweb="tab"] {
        height: 2.2rem; padding: 0 1.2rem; border-radius: 6px; 
        font-weight: 500; font-size: 0.9rem; color: #868e96; border: none;
        transition: all 0.2s;
    }
    .stTabs [aria-selected="true"] {
        background-color: #ffffff !important; color: #111 !important; 
        box-shadow: 0 1px 3px rgba(0,0,0,0.08); font-weight: 600;
        border-bottom: none; /* Remove underline */
    }
    
    /* 7. Dataframes (Clean Headers) */
    div[data-testid="stDataFrame"] { border: 1px solid #dee2e6; border-radius: 4px; }
    
    /* 8. Alerts & Info (Fix Double Box) */
    .stAlert { padding: 0.5rem 1rem !important; border-radius: 4px; border: none !important; }
    
    /* 9. Divider */
    hr { margin: 1.5rem 0 !important; border-color: #f1f3f5; }
    
    /* 10. Sidebar Branding */
    [data-testid="stSidebar"] {
        background-color: #f8f9fa;
        border-right: 1px solid #dee2e6;
    }
    [data-testid="stSidebar"] h2 {
        font-size: 1.1rem !important; margin-top: 0 !important; border-bottom: none;
        color: #343a40; margin-bottom: 1rem !important;
    }
    [data-testid="stSidebar"] .stRadio > label { font-size: 0.85rem; color: #495057; font-weight: 500; }
    [data-testid="stSidebar"] .stNumberInput > label { font-size: 0.85rem; color: #495057; font-weight: 500; }
    [data-testid="stSidebar"] .stSlider > label { font-size: 0.85rem; color: #495057; font-weight: 500; }
    [data-testid="stSidebar"] button { 
        width: 100%; border: 1px solid #e9ecef; background-color: #fff; color: #868e96; font-size: 0.85rem;
    }
    [data-testid="stSidebar"] button:hover {
        border-color: #adb5bd; color: #495057; background-color: #f1f3f5;
    }
</style>
""", unsafe_allow_html=True)

init_db()

st.title(" 208-Week High-Speed System")

with st.sidebar:
    st.header("설정")
    
    # 설정 불러오기
    saved_settings = load_settings()
    
    # 시장 선택
    market_options = ["KOSPI", "KOSDAQ"]
    try:
        market_idx = market_options.index(saved_settings.get('market', 'KOSPI'))
    except:
        market_idx = 0
    market_sel = st.radio("시장 선택", market_options, index=market_idx)
    
    lookback_sel = st.number_input("조회 기간 (주)", value=saved_settings.get('lookback', 208), step=1, min_value=52)
    n_stocks_sel = st.slider("분석할 상위 종목 수", 50, 500, saved_settings.get('n_stocks', 200))
    bc_breakout_days = st.slider(
        "B/C 돌파 확인 기간 (일)", 
        min_value=5, max_value=60, value=saved_settings.get('bc_breakout_days', 60), step=5,
        help="최근 N일 내 B/C 라인 아래 있었는지 확인. 짧을수록 신선한 돌파만, 길수록 더 많은 종목 포함."
    )
    
    # 설정 변경 시 자동 저장 (세션 상태를 활용해 무한 루프 방지)
    current_settings = {
        'market': market_sel,
        'lookback': lookback_sel,
        'n_stocks': n_stocks_sel,
        'bc_breakout_days': bc_breakout_days
    }
    
    if 'last_settings' not in st.session_state:
        st.session_state['last_settings'] = saved_settings

    if current_settings != st.session_state['last_settings']:
        save_settings(current_settings)
        st.session_state['last_settings'] = current_settings
        st.toast("설정이 저장되었습니다.")
    
    st.divider()
    if st.button("가격 캐시 초기화", help="저장된 가격 데이터를 모두 삭제하고 새로 내려받습니다."):
        try:
            if os.path.exists(CACHE_DB):
                os.remove(CACHE_DB)
                st.success("캐시가 초기화되었습니다. 다시 스캔해 주세요.")
                st.rerun()
        except Exception as e:
            st.error(f"캐시 삭제 실패: {e}")

tab1, tab2 = st.tabs(["실시간 스크리너", "백테스팅"])

with tab1:
    st.markdown("### 실시간 종목 스크린")
    
    kst = pytz.timezone('Asia/Seoul')
    scan_date = st.date_input(
        "검색 기준 날짜",
        value=datetime.now(kst).date(),
        help="이 날짜 기준으로 조건을 만족하는 종목을 검색합니다. 백테스트 결과와 비교 검증 시 유용합니다."
    )
    
    st.caption("**스마트 캐시**: 과거 날짜 분석 시 캐시 활용, 최신 데이터 필요 시 자동 갱신됩니다.")
    
    if st.button("실시간 종목 스캔 시작"):
        stock_list = get_stock_list_naver(market_sel, n_stocks_sel)
        results = []
        pb = st.progress(0)
        st_txt = st.empty()
        
        start_time = datetime.now() # Start timer
        
        # [NEW] 동적 시작 날짜 계산 (필요한 lookback 주수의 1.5배 기간 확보)
        fetch_start_date = (scan_date - pd.Timedelta(weeks=int(lookback_sel * 1.5))).strftime('%Y-%m-%d')
        
        cache_hit = 0
        cache_miss = 0
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_to_stock = {
                executor.submit(fetch_data, row['Code'], market_sel, start_date=fetch_start_date, scan_date=scan_date): row 
                for _, row in stock_list.iterrows()
            }
            
            load_fail = 0
            success_count = 0  # [FIX] Missing initialization
            insufficient_data = 0
            insufficient_history = 0
            
            load_fail_names = []
            skip_before_ipo_names = []
            skip_low_history_names = []
            
            for i, future in enumerate(as_completed(future_to_stock)):
                stock_row = future_to_stock[future]
                try:
                    result = future.result(timeout=30)
                    # [FIX] fetch_data returns (df, from_cache), which is never None. 
                    # Need to check df inside.
                    if result is None or result[0] is None:
                        load_fail += 1
                        load_fail_names.append(f"{stock_row['Name']} (Fetch Error)")
                        continue
                    
                    df, from_cache = result
                    if from_cache: cache_hit += 1
                    else: cache_miss += 1
                    
                    if df is not None and not df.empty:
                        df_full_for_chart = df.copy()
                        
                        target_date = pd.Timestamp(scan_date)
                        df = df[df.index <= target_date]
                        
                        if df.empty:
                            insufficient_data += 1
                            skip_before_ipo_names.append(stock_row['Name'])
                            continue
                        
                        # 데이터 기간 확인 (주봉 기준 최소 lookback 주수 확보 여부)
                        df_weekly_check = df.resample('W').agg({'Close': 'last'})
                        if len(df_weekly_check) < lookback_sel:
                            insufficient_history += 1
                            skip_low_history_names.append(stock_row['Name'])
                            continue

                        # 가격 반영 로직
                        cur_p = stock_row.get('현재가', 0)
                        last_date = df.index[-1]
                        today = pd.Timestamp(datetime.now(kst).date())
                        
                        if scan_date == today.date() and cur_p > 0:
                            if last_date.date() < today.date():
                                new_row = pd.DataFrame({
                                    'Open': [cur_p], 'High': [cur_p], 'Low': [cur_p], 'Close': [cur_p], 'Volume': [0]
                                }, index=[today])
                                df = pd.concat([df, new_row])
                                df_full_for_chart = pd.concat([df_full_for_chart, new_row])
                            elif last_date.date() == today.date():
                                df.at[last_date, 'Close'] = cur_p
                                if cur_p > df.at[last_date, 'High']: df.at[last_date, 'High'] = cur_p
                                if cur_p < df.at[last_date, 'Low']: df.at[last_date, 'Low'] = cur_p
                                
                                df_full_for_chart.at[last_date, 'Close'] = cur_p
                                if cur_p > df_full_for_chart.at[last_date, 'High']: df_full_for_chart.at[last_date, 'High'] = cur_p
                                if cur_p < df_full_for_chart.at[last_date, 'Low']: df_full_for_chart.at[last_date, 'Low'] = cur_p
                        
                        scan_date_ts = pd.Timestamp(scan_date)
                        df_until_scan = df[df.index <= scan_date_ts].copy()
                        
                        res = analyze_stock_core(stock_row['Code'], stock_row['Name'], df_until_scan, lookback_sel, bc_breakout_days)
                        if res:
                            res['df_daily'] = df_full_for_chart
                            res['현재가'] = float(df_full_for_chart['Close'].iloc[-1])
                            
                            entry_date = pd.Timestamp(scan_date)
                            entry_price = res['매수가'] 
                            perf = calculate_screener_performance(df_full_for_chart, entry_date, entry_price, res['segments'])
                            
                            if perf: res.update(perf)
                            results.append(res)
                            success_count += 1
                    else:
                        load_fail += 1
                        load_fail_names.append(stock_row['Name'])
                except Exception as e:
                    load_fail += 1
                    load_fail_names.append(f"{stock_row['Name']} ({str(e)})")
                
                pb.progress((i + 1) / n_stocks_sel)
                total_attempted = cache_hit + cache_miss + load_fail
                cache_rate = (cache_hit / total_attempted * 100) if total_attempted > 0 else 0
                st_txt.text(f"분석 중... ({i+1}/{n_stocks_sel}) | 발견: {len(results)}개 | 실패: {load_fail}건 | 제외: {insufficient_data + insufficient_history}건 | 캐시: {cache_rate:.0f}%")
        
        total_attempted = cache_hit + cache_miss + load_fail
        cache_rate = (cache_hit / total_attempted * 100) if total_attempted > 0 else 0
        
        min_seconds = (datetime.now() - start_time).total_seconds()
        
        if not results:
            st.warning("결과가 없습니다.")
            if load_fail > 0:
                st.error(f"데이터 로드 실패가 {load_fail}건 발생했습니다. 네트워크 상태나 API 제한을 확인해 주세요.")
            
            if insufficient_data > 0 or insufficient_history > 0:
                msg = f"선택하신 날짜({scan_date})에 "
                parts = []
                if insufficient_data > 0: parts.append(f"상장 전 종목({insufficient_data}건)")
                if insufficient_history > 0: parts.append(f"{lookback_sel}주 데이터 부족 종목({insufficient_history}건)")
                msg += " 및 ".join(parts) + "이 제외되었습니다."
                st.info(msg)
        else:
            filtered_results = sorted(results, key=lambda x: x['B/C 상승률'])
            st.session_state['scan_results'] = filtered_results
            st.session_state['scan_market'] = market_sel
            st.session_state['scan_date'] = scan_date
            
            st.success(f"{len(filtered_results)}개 종목 발견! (소요 시간: {min_seconds:.1f}초)")
            
            # 성능 통계 (Screener)
            perf_msg = f"성능 통계 | 캐시 활용: {cache_rate:.1f}% ({cache_hit}/{total_attempted}) | API 호출: {cache_miss}회"
            if load_fail > 0: perf_msg += f" | 로드 실패: {load_fail}건"
            if insufficient_data > 0: perf_msg += f" | 상장 전: {insufficient_data}건"
            if insufficient_history > 0: perf_msg += f" | {lookback_sel}주 데이터 부족: {insufficient_history}건"
            st.info(perf_msg)
            
        # 제외 및 실패 종목 상세 보기
        if load_fail > 0 or insufficient_data > 0 or insufficient_history > 0:
            with st.expander("🔍 분석 제외/실패 종목 리스트 확인", expanded=False):
                c1, c2, c3 = st.columns(3)
                if load_fail > 0:
                    with c1:
                        st.markdown(f"❌ **로드 실패 ({load_fail}건)**")
                        st.caption(", ".join(load_fail_names))
                if insufficient_data > 0:
                    with c2:
                        st.markdown(f"📅 **상장 전 ({insufficient_data}건)**")
                        st.caption(", ".join(skip_before_ipo_names))
                if insufficient_history > 0:
                    with c3:
                        st.markdown(f"⌛ **{lookback_sel}주 데이터 부족 ({insufficient_history}건)**")
                        st.caption(", ".join(skip_low_history_names))
            
            # --- 결과 표시 ---

    if 'scan_results' in st.session_state:
        results = st.session_state['scan_results']
        
        df_disp = pd.DataFrame(results)
        
        if '수익률' in df_disp.columns and '상태' in df_disp.columns:
            df_disp['수익률/상태'] = df_disp.apply(
                lambda row: f"{'+' if row['수익률'] > 0 else ''}{row['수익률']:.1f}% ({row['상태']})" 
                if pd.notna(row['수익률']) and pd.notna(row['상태']) else '-',
                axis=1
            )
        
        if 'Max 수익률' in df_disp.columns and 'Max 날짜' in df_disp.columns:
            df_disp['Max 수익/날짜'] = df_disp.apply(
                lambda row: f"{'+' if row['Max 수익률'] > 0 else ''}{row['Max 수익률']:.1f}% ({row['Max 날짜']})" 
                if pd.notna(row['Max 수익률']) and pd.notna(row['Max 날짜']) else '-', axis=1
            )
        
        if 'Min 수익률' in df_disp.columns and 'Min 날짜' in df_disp.columns:
            df_disp['Min 수익/날짜'] = df_disp.apply(
                lambda row: f"{'+' if row['Min 수익률'] > 0 else ''}{row['Min 수익률']:.1f}% ({row['Min 날짜']})" 
                if pd.notna(row['Min 수익률']) and pd.notna(row['Min 날짜']) else '-', axis=1
            )
            
        preferred_cols = [
            'Code', 'Name', '매수가', '현재가', 'B/C 라인', 'B/C 상승률', 
            '수익률/상태', 'Max 수익/날짜', 'Min 수익/날짜',
            '208주 최저', '208주 최고', '현재 구간', '20일선'
        ]
        
        cols_to_show = [c for c in preferred_cols if c in df_disp.columns]
        df_disp = df_disp[cols_to_show].copy()
        
        # [FIX] Force leading zeros in Excel by prepending '
        if 'Code' in df_disp.columns:
            df_disp['Code'] = df_disp['Code'].apply(lambda x: f"'{str(x).zfill(6)}")
        
        price_cols = ['매수가', '현재가', 'B/C 라인', '208주 최저', '208주 최고']
        for col in price_cols:
            if col in df_disp.columns:
                df_disp[col] = df_disp[col].apply(lambda x: f"{int(x):,}" if pd.notna(x) else x)
        
        if 'B/C 상승률' in df_disp.columns:
            df_disp['B/C 상승률'] = df_disp['B/C 상승률'].apply(lambda x: f"+{x:.1f}%" if x > 0 else f"{x:.1f}%")

        st.dataframe(df_disp, width=1200) # Replaced 'stretch' width
        st.divider()
        
        # 상세 분석
        col_list = [f"{r['Name']} ({r['Code']})" for r in results]
        selected_stock_str = st.selectbox("상세 분석 종목 선택", col_list)
        
        if selected_stock_str:
            sel_idx = col_list.index(selected_stock_str)
            row_sel = results[sel_idx]
            
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("종목명", row_sel['Name'])
            c1.caption(f"Code: {row_sel['Code']}")
            
            c2.metric("매수가 (검색일)", f"{int(row_sel['매수가']):,}원")
            curr_price = row_sel.get('현재가', 0)
            c2.caption(f"현재가: {int(curr_price):,}원")
            
            pnl = row_sel.get('수익률', 0)
            c3.metric("수익률", f"{pnl:+.1f}%")
            if 'Max 수익률' in row_sel:
                c3.caption(f"Max: {row_sel['Max 수익률']:+.1f}% ({row_sel['Max 날짜']})")
                
            c4.metric("현재 상태", row_sel.get('상태', '-'))
            if 'Min 수익률' in row_sel:
                c4.caption(f"Min: {row_sel['Min 수익률']:+.1f}% ({row_sel['Min 날짜']})")

            # 보유일 계산 (검색일 기준)
            s_date = st.session_state.get('scan_date', datetime.now(kst).date())
            status_str = row_sel.get('상태', '')
            
            # 매도일이 있다면 해당 날짜까지, 없으면 오늘까지
            import re
            match = re.search(r'\((\d{4}-\d{2}-\d{2})\)', status_str)
            if match and '매도' in status_str:
                end_date = pd.Timestamp(match.group(1)).date()
            else:
                end_date = datetime.now(kst).date()
            
            duration = (end_date - s_date).days
            c5.metric("보유일", f"{duration}일")
            
            st.markdown("#### 차트 분석")
            df_chart = row_sel['df_daily'].copy()
            df_chart['MA20'] = df_chart['Close'].rolling(window=20).mean()
            
            fig = go.Figure()
            
            # 1. Price Line (Thicker, Darker Blue for visibility on white)
            fig.add_trace(go.Scatter(
                x=df_chart.index, y=df_chart['Close'], 
                name='가격', 
                line=dict(color='#2c3e50', width=2.5) 
            ))
            
            # 2. MA20 (Thinner, Orange)
            fig.add_trace(go.Scatter(
                x=df_chart.index, y=df_chart['MA20'], 
                name='20일선', 
                line=dict(color='#e67e22', width=1.5, dash='dot')
            ))
            
            # 3. Segments (Subtle Grey)
            for i, level in enumerate(row_sel['segments']):
                fig.add_hline(y=level, line_dash="dash", line_color="rgba(150,150,150,0.5)", line_width=1)
            
            # 4. BUY Signal (Vertical Line + Text)
            scan_date_ts = pd.Timestamp(st.session_state.get('scan_date', datetime.now().date()))
            valid_dates = df_chart[df_chart.index <= scan_date_ts].index
            
            if len(valid_dates) > 0:
                buy_date = valid_dates[-1]
                
                # Vertical Line
                fig.add_vline(x=buy_date, line_width=1, line_dash="solid", line_color="#e74c3c")
                
                # Text Label (Bottom)
                fig.add_annotation(
                    x=buy_date, y=0.02, yref="paper",
                    text="<b>BUY</b>",
                    showarrow=False,
                    font=dict(color="#e74c3c", size=14),
                    bgcolor="rgba(255,255,255,0.7)",
                    yanchor="bottom"
                )
            
            # 5. SELL Signal (Vertical Line + Text)
            if '상태' in row_sel and '매도' in row_sel['상태']:
                import re
                match = re.search(r'\((\d{4}-\d{2}-\d{2})\)', row_sel['상태'])
                if match:
                    sell_date_str = match.group(1)
                    sell_date_ts = pd.Timestamp(sell_date_str)
                    valid_sell_dates = df_chart[df_chart.index <= sell_date_ts].index
                    if len(valid_sell_dates) > 0:
                        sell_date = valid_sell_dates[-1]
                        
                        # Vertical Line
                        fig.add_vline(x=sell_date, line_width=1, line_dash="solid", line_color="#3498db")
                        
                        # Text Label (Top)
                        fig.add_annotation(
                            x=sell_date, y=0.98, yref="paper",
                            text="<b>SELL</b>",
                            showarrow=False,
                            font=dict(color="#3498db", size=14),
                            bgcolor="rgba(255,255,255,0.7)",
                            yanchor="top"
                        )
            
            fig.update_layout(
                template="plotly_white", 
                height=600, 
                hovermode='x unified', 
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=20, r=20, t=50, b=20),
                xaxis=dict(showgrid=True, gridcolor='rgba(230,230,230,0.5)'),
                yaxis=dict(showgrid=True, gridcolor='rgba(230,230,230,0.5)')
            )
            st.plotly_chart(fig, width=1200)

with tab2:
    st.subheader("초고속 백테스팅")
    with st.expander("전략 설정", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            bt_brk = st.checkbox("B/C 돌파 필수", value=True)
            bt_ma = st.checkbox("20일선 위 필수", value=True)
            bt_seg = st.selectbox("진입 구간", ["Segment C (B/C~C/D)", "Segment B (A/B~B/C)"])
        with c2:
            bt_tgt = st.selectbox("목표 경계", ["D/E Boundary", "C/D Boundary", "E/F Boundary"])
            bt_met = st.radio("매도 방식", ["목표 도달 후 20일선 이탈", "목표가 도달 시 즉시 매도"])
            bt_sl = st.number_input("손절 (%)", value=0.0)
    
    with st.expander("백테스트 기간 설정", expanded=False):
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            bt_start = st.date_input("시작일", value=datetime(2023, 1, 2), max_value=datetime(2030, 12, 31), key="bt_start_date")
        with col_d2:
            bt_end = st.date_input("종료일", value=datetime.now(), max_value=datetime(2030, 12, 31), key="bt_end_date")
            
    with st.expander("보유 포지션 처리", expanded=False):
        bt_force_liquidate = st.checkbox(
            "종료일 기준 강제 청산", value=False,
            help="체크: 보유 중인 포지션을 종료일 가격으로 강제 청산\n해제: 보유 중인 포지션을 '보유중'으로 표시"
        )

    if st.button("초고속 분석 시작"):
        stock_list = get_stock_list_naver(market_sel, n_stocks_sel)
        
        if 'scan_results' in st.session_state:
            scan_market = st.session_state.get('scan_market', None)
            if scan_market == market_sel:
                existing_codes = set(stock_list['Code'].values)
                new_rows = []
                for res in st.session_state['scan_results']:
                    if res['Code'] not in existing_codes:
                        last_price = 0
                        if 'df_daily' in res and len(res['df_daily']) > 0:
                             last_price = res['df_daily']['Close'].iloc[-1]
                        new_rows.append({'Code': res['Code'], 'Name': res['Name'], '현재가': last_price})
                if new_rows:
                    stock_list = pd.concat([stock_list, pd.DataFrame(new_rows)], ignore_index=True)
                    st.toast(f"스크리너 발견 종목 {len(new_rows)}개를 백테스트 목록에 자동 추가했습니다!")
        
        cfg = {
            'buy_breakout':bt_brk, 'buy_ma20':bt_ma, 'buy_segment':bt_seg, 
            'exit_target':bt_tgt, 'exit_method':bt_met, 'stop_loss_pct':bt_sl,
            'start_date': bt_start.strftime('%Y-%m-%d'),
            'end_date': bt_end.strftime('%Y-%m-%d'),
            'force_liquidate': bt_force_liquidate,
            'lookback': lookback_sel,
            'bc_breakout_days': bc_breakout_days
        }
        
        bt_results = []
        pb_bt = st.progress(0)
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            scan_data_map = {}
            if 'scan_results' in st.session_state:
                for res in st.session_state['scan_results']:
                    if 'df_daily' in res:
                        # [FIX] Ensure clean code for mapping
                        clean_code = str(res['Code']).lstrip("'")
                        scan_data_map[clean_code] = res['df_daily']

            future_to_bt = {
                executor.submit(
                    process_backtest_stock, 
                    r['Code'], r['Name'], market_sel, cfg, r.to_dict(), 
                    scan_data_map.get(r['Code']),
                    bt_end 
                ): r 
                for _, r in stock_list.iterrows()
            }
            
            cache_hit_bt = 0
            cache_miss_bt = 0
            
            for i, future in enumerate(as_completed(future_to_bt)):
                try:
                    r_bt = future.result(timeout=30)
                    if r_bt: 
                        bt_results.append(r_bt)
                        # Backtest result doesn't explicitly return cache status, 
                        # but we can infer based on scan_data_map usage strategy.
                        # Actually, process_backtest_stock calls fetch_data internally if not in map.
                        # For now, simplistic counting isn't easy without return value modification.
                        # We will assume: if code in scan_data_map -> cache hit. 
                        # If not -> fetch_data called -> we need valid return from process function for accurate stats.
                        # Let's count processed items as successful.
                        # **Correction**: process_backtest_stock calls fetch_data. 
                        # To enable stats, we need to modify process_backtest_stock or fetch_data tracking.
                        # Given constraints, we will approximate or leave it for now, 
                        # BUT the user specifically asked for it. 
                        # Let's assume most were hits if we passed pre_fetched_df.
                        # Better approach: We passed pre_fetched_df for all items in scan_results.
                        # So those are hits. Others are misses/fetches.
                        pass
                except: pass
                pb_bt.progress((i+1)/len(future_to_bt))
            
            # [LOGIC IMPROVEMENT] Recalculate stats based on inputs
            total_bt = len(stock_list)
            # scan_data_map contains items already fetched.
            # If we run backtest on the SAME list as screener, they are likely cached.
            # However, `process_backtest_stock` returns `df_daily`.
            # We can't easily count hits inside the future without changing return signature.
            # Workaround: Count how many had `pre_fetched_df` passed.
            for code in stock_list['Code']:
                clean_code = str(code).lstrip("'")
                if clean_code in scan_data_map:
                    cache_hit_bt += 1
                else: 
                    cache_miss_bt += 1 
            
        if bt_results:
            st.session_state['bt_results'] = bt_results
            
            # 성능 통계 (Backtest)
            total_processed_bt = cache_hit_bt + cache_miss_bt
            cache_rate_bt = (cache_hit_bt / total_processed_bt * 100) if total_processed_bt > 0 else 0
            st.info(f"성능 통계 | 캐시 활용(추정): {cache_rate_bt:.1f}% ({cache_hit_bt}/{total_processed_bt}) | 데이터 로드 완료")

    if 'bt_results' in st.session_state:
        bt_res = st.session_state['bt_results']
        
        st.subheader("백테스팅 결과 요약")
        df_summary = pd.DataFrame(bt_res).drop(columns=['df_daily', 'trades'], errors='ignore')
        
        if 'Recent Buy' in df_summary.columns:
            df_summary['Recent Buy'] = pd.to_datetime(df_summary['Recent Buy'], format='%Y-%m-%d', errors='coerce')
        
        start_date_filter = pd.Timestamp(bt_start)
        mask_recent_activity = (
            (df_summary['Recent Buy'] >= start_date_filter) |
            (df_summary['Recent Sell'] == 'New')
        )
        df_summary = df_summary[mask_recent_activity].copy()

        df_summary['_is_new'] = df_summary['Recent Sell'] == 'New'
        df_summary = df_summary.sort_values(by=['_is_new', 'Recent Buy'], ascending=[False, False])
        df_summary.drop(columns=['_is_new'], inplace=True)
        
        df_summary = df_summary.reset_index(drop=True)
        df_summary.insert(0, '#', range(len(df_summary)))
        
        if 'Recent Buy' in df_summary.columns and 'Recent Buy Price' in df_summary.columns:
            df_summary['Recent Buy'] = df_summary.apply(
                lambda row: f"{row['Recent Buy'].strftime('%Y-%m-%d')} ({int(row['Recent Buy Price']):,})" 
                if pd.notna(row['Recent Buy']) and isinstance(row['Recent Buy'], pd.Timestamp) and pd.notna(row['Recent Buy Price'])
                else str(row['Recent Buy']), axis=1
            )
        
        if 'Recent Sell' in df_summary.columns and 'Recent Sell Price' in df_summary.columns:
            df_summary['Recent Sell'] = df_summary.apply(
                lambda row: f"{row['Recent Sell']} ({int(row['Recent Sell Price']):,})" 
                if pd.notna(row['Recent Sell']) and pd.notna(row['Recent Sell Price']) else str(row['Recent Sell']), axis=1
            )
        
        cols_to_drop = ['is_core_buy', 'is_new_signal', 'DebugInfo', 'Log', 'Recent Buy Price', 'Recent Sell Price']
        df_summary.drop(columns=cols_to_drop, errors='ignore', inplace=True)
        
        if 'Max 수익률' in df_summary.columns and 'Max 날짜' in df_summary.columns:
            df_summary['Max 수익/날짜'] = df_summary.apply(
                lambda row: f"+{row['Max 수익률']:.1f}% ({row['Max 날짜']})" if pd.notna(row['Max 수익률']) and row['Max 수익률'] >= 0
                else f"{row['Max 수익률']:.1f}% ({row['Max 날짜']})", axis=1
            )
        
        if 'Min 수익률' in df_summary.columns and 'Min 날짜' in df_summary.columns:
            df_summary['Min 수익/날짜'] = df_summary.apply(
                lambda row: f"{row['Min 수익률']:.1f}% ({row['Min 날짜']})" if pd.notna(row['Min 수익률']) else '-', axis=1
            )
        
        pnl_cols = ['Total PnL (%)', 'Win Rate (%)', 'Current PnL (%)']
        for col in pnl_cols:
            if col in df_summary.columns:
                df_summary[col] = df_summary[col].apply(lambda x: f"{x:.1f}" if pd.notna(x) else '-')
        
        cols = [
            '#', 'Ticker', 'Name', 
            'Recent Buy Price', 'Recent Sell Price',
            'Current PnL (%)', 
            'Max 수익/날짜', 'Min 수익/날짜',
            'Total PnL (%)', 'Trades', 'Win Rate (%)', 
            'Duration',
            'Recent Buy', 'Recent Sell'
        ]
        
        df_summary_display = df_summary.copy()
        df_summary_display = df_summary_display.rename(columns={
            'Ticker': 'Code',
            'Recent Buy Price': '매수가',
            'Recent Sell Price': '현재가',
            'Duration': '보유일'
        })
        
        existing_cols = df_summary_display.columns.tolist()
        renamed_cols = [c if c not in ['Ticker', 'Recent Buy Price', 'Recent Sell Price'] else 
                       ('Code' if c == 'Ticker' else ('매수가' if c == 'Recent Buy Price' else '현재가'))
                       for c in cols]
        final_cols = [c for c in renamed_cols if c in existing_cols] + [c for c in existing_cols if c not in renamed_cols and c not in ['Max 수익률', 'Max 날짜', 'Min 수익률', 'Min 날짜']]
        df_summary_display = df_summary_display[final_cols].copy()
        
        # [FIX] Force leading zeros in Excel
        if 'Code' in df_summary_display.columns:
            df_summary_display['Code'] = df_summary_display['Code'].apply(lambda x: f"'{str(x).zfill(6)}")
        
        if '매수가' in df_summary_display.columns:
            df_summary_display['매수가'] = df_summary_display['매수가'].apply(lambda x: f"{int(x):,}" if pd.notna(x) else '-')
        if '현재가' in df_summary_display.columns:
            df_summary_display['현재가'] = df_summary_display['현재가'].apply(lambda x: f"{int(x):,}" if pd.notna(x) else '-')
        
        st.dataframe(df_summary_display, width=1200, hide_index=True)
        st.divider()
        
        # 상세 분석 UI 복구
        # 테이블 순서와 일치시키기 위해 정렬된 Ticker 리스트 활용
        # df_summary_display는 컬럼명이 변경되었을 수 있으므로 df_summary 기준 (또는 화면에 보이는 순서대로 매핑)
        
        # 1. 화면에 보이는 순서대로 데이터 정렬
        sorted_codes = df_summary_display['Code'].tolist()
        bt_res_map = {r['Ticker']: r for r in bt_res} # Ticker가 Key
        
        rows_ordered = []
        bt_col_list = []
        
        for idx, code in enumerate(sorted_codes):
            clean_code = str(code).lstrip("'")
            if clean_code in bt_res_map:
                row_data = bt_res_map[clean_code]
                rows_ordered.append(row_data)
                # 번호 붙여서 리스트 생성
                bt_col_list.append(f"{idx}. {row_data['Name']} ({clean_code})")
        
        selected_bt_stock = st.selectbox("상세 분석 종목 선택 (백테스트 결과)", bt_col_list)
        
        if selected_bt_stock:
            # 선택된 문자열에서 인덱스 추출하거나, 리스트 인덱스로 접근
            sel_idx = bt_col_list.index(selected_bt_stock)
            bt_row = rows_ordered[sel_idx]
            
            st.markdown(f"### {bt_row['Name']} ({bt_row['Ticker']}) 상세 분석")
            
            # 요약 지표 (스크리너와 동일한 구성)
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("종목명", bt_row['Name'])
            c1.caption(f"Code: {bt_row['Ticker']}")
            
            # 백테스트 결과이므로 '최근 매수가' 기준
            buy_price = bt_row.get('Recent Buy Price', 0)
            c2.metric("매수가 (최근)", f"{int(buy_price):,}원")
            curr_price = bt_row.get('Recent Sell Price', 0) # 매도 안했으면 현재가
            c2.caption(f"현재가: {int(curr_price):,}원")
            
            pnl = bt_row.get('Current PnL (%)', 0)
            c3.metric("수익률", f"{pnl:+.1f}%")
            if 'Max 수익률' in bt_row:
                c3.caption(f"Max: {bt_row['Max 수익률']:+.1f}% ({bt_row['Max 날짜']})")
            
            c4.metric("현재 상태", bt_row.get('Recent Sell', '-'))
            if 'Min 수익률' in bt_row:
                c4.caption(f"Min: {bt_row['Min 수익률']:+.1f}% ({bt_row['Min 날짜']})")

            c5.metric("보유일", f"{int(bt_row.get('Duration', 0))}일")
            
            st.divider()

            
            # 1. 거래 이력
            st.markdown("#### 거래 이력")
            trades = bt_row.get('trades', [])
            df_daily_full = bt_row.get('df_daily')
            
            if trades:
                df_trades = pd.DataFrame(trades)
                
                # Max/Min 수익률 계산 추가
                if df_daily_full is not None and not df_daily_full.empty:
                    max_pnls = []
                    min_pnls = []
                    for _, t_row in df_trades.iterrows():
                        entry_date = t_row['entry_date']
                        entry_price = t_row['entry_price']
                        exit_date = t_row['exit_date']
                        
                        # 기간 필터링
                        subset = df_daily_full[df_daily_full.index >= entry_date]
                        if pd.notna(exit_date):
                            subset = subset[subset.index <= exit_date]
                        
                        if not subset.empty:
                            subset = subset.copy()
                            subset['pnl_temp'] = (subset['Close'] / entry_price - 1) * 100
                            max_val = subset['pnl_temp'].max()
                            min_val = subset['pnl_temp'].min()
                            max_date = subset['pnl_temp'].idxmax().strftime('%Y-%m-%d')
                            min_date = subset['pnl_temp'].idxmin().strftime('%Y-%m-%d')
                            
                            max_str = f"+{max_val:.1f}% ({max_date})" if max_val >= 0 else f"{max_val:.1f}% ({max_date})"
                            min_str = f"{min_val:.1f}% ({min_date})"
                            max_pnls.append(max_str)
                            min_pnls.append(min_str)
                        else:
                            max_pnls.append('-')
                            min_pnls.append('-')
                    
                    df_trades['Max 수익률'] = max_pnls
                    df_trades['Min 수익률'] = min_pnls
                
                # 컬럼 포맷팅
                if 'entry_price' in df_trades.columns:
                    df_trades['매수가'] = df_trades['entry_price'].apply(lambda x: f"{int(x):,}원")
                if 'exit_price' in df_trades.columns:
                    df_trades['매도가'] = df_trades['exit_price'].apply(lambda x: f"{int(x):,}원" if pd.notna(x) else '-')
                if 'entry_date' in df_trades.columns:
                    df_trades['매수일'] = df_trades['entry_date'].apply(lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else '-')
                if 'exit_date' in df_trades.columns:
                    df_trades['매도일'] = df_trades['exit_date'].apply(lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else '보유중')
                if 'pnl' in df_trades.columns:
                    df_trades['수익률'] = df_trades['pnl'].apply(lambda x: f"{x:+.2f}%" if pd.notna(x) else '-')
                
                disp_cols = ['매수일', '매수가', '매도일', '매도가', '수익률', 'Max 수익률', 'Min 수익률', 'duration']
                df_trades_disp = df_trades[disp_cols].rename(columns={'duration': '보유일'})
                st.dataframe(df_trades_disp, width="stretch")
            else:
                st.info("거래 내역이 없습니다.")
                
            # 2. 차트
            st.markdown("#### 매매 시점 차트")
            df_chart = bt_row.get('df_daily')
            
            if df_chart is not None and not df_chart.empty:
                df_chart = df_chart.copy()
                # MA20 계산 (만약 없다면)
                if 'MA20' not in df_chart.columns:
                    df_chart['MA20'] = df_chart['Close'].rolling(window=20).mean()
                    
                fig = go.Figure()
                
                # Price & MA20
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['Close'], name='가격', line=dict(color='#2c3e50', width=2.5)))
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MA20'], name='20일선', line=dict(color='#e67e22', width=1.5, dash='dot')))
                
                # Segments (마지막 기준)
                if trades:
                    last_segments = trades[-1].get('segments')
                    if last_segments:
                        for level in last_segments:
                            fig.add_hline(y=level, line_dash="dash", line_color="rgba(150,150,150,0.5)", line_width=1)
                
                # 매매 시점 표시
                for trade in trades:
                    # 매수
                    buy_date = trade['entry_date']
                    fig.add_vline(x=buy_date, line_width=1, line_dash="solid", line_color="#e74c3c")
                    fig.add_annotation(
                        x=buy_date, y=0.02, yref="paper", text="<b>BUY</b>",
                        showarrow=False, font=dict(color="#e74c3c", size=10),
                        bgcolor="rgba(255,255,255,0.7)", yanchor="bottom"
                    )
                    
                    # 매도
                    if pd.notna(trade['exit_date']):
                        sell_date = trade['exit_date']
                        fig.add_vline(x=sell_date, line_width=1, line_dash="solid", line_color="#3498db")
                        fig.add_annotation(
                            x=sell_date, y=0.98, yref="paper", text="<b>SELL</b>",
                            showarrow=False, font=dict(color="#3498db", size=10),
                            bgcolor="rgba(255,255,255,0.7)", yanchor="top"
                        )
                
                fig.update_layout(
                    template="plotly_white", height=500, hovermode='x unified',
                    margin=dict(l=20, r=20, t=30, b=20),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig, width="stretch")
            else:
                st.warning("차트 데이터가 없습니다.")
