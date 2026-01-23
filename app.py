import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go
import os
import pytz
from concurrent.futures import ThreadPoolExecutor, as_completed

# Custom Modules
from utils import load_settings, save_settings
from data_loader import init_db, fetch_data, get_stock_list_naver, CACHE_DB
from analyzer import analyze_stock_core, calculate_screener_performance, process_backtest_stock

# --- UI Setup ---
st.set_page_config(page_title="208-Week System", layout="wide")

# [UI] Custom CSS for Minimalist Design
st.markdown("""
<style>
    /* Global Font */
    html, body, [class*="css"] {
        font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, Roboto, 'Helvetica Neue', 'Segoe UI', 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
    }
    /* Headers */
    h1, h2, h3 { font-weight: 700; letter-spacing: -0.5px; color: #111; }
    
    /* Button Style - Minimalist */
    div.stButton > button {
        background-color: #ffffff; color: #333333; border: 1px solid #e0e0e0;
        border-radius: 6px; padding: 0.4rem 1rem; font-weight: 500;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05); transition: all 0.2s ease;
    }
    div.stButton > button:hover {
        border-color: #333333; background-color: #f8f9fa; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    div.stButton > button:active { background-color: #f1f3f5; transform: translateY(1px); }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] { gap: 1.5rem; }
    .stTabs [data-baseweb="tab"] {
        height: 3rem; white-space: pre-wrap; background-color: transparent;
        border-radius: 4px; color: #868e96; font-weight: 600;
    }
    .stTabs [aria-selected="true"] {
        background-color: transparent !important; color: #111 !important; border-bottom: 2px solid #111;
    }
    
    /* Metrics & Info */
    .stAlert { border: 1px solid #eee; background-color: #fcfcfc; color: #333; }
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
    
    # 설정 변경 시 자동 저장
    current_settings = {
        'market': market_sel,
        'lookback': lookback_sel,
        'n_stocks': n_stocks_sel,
        'bc_breakout_days': bc_breakout_days
    }
    if current_settings != saved_settings:
        save_settings(current_settings)
    
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
        
        cache_hit = 0
        cache_miss = 0
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_to_stock = {
                executor.submit(fetch_data, row['Code'], market_sel, scan_date=scan_date): row 
                for _, row in stock_list.iterrows()
            }
            
            success_count = 0
            fail_count = 0
            
            for i, future in enumerate(as_completed(future_to_stock)):
                stock_row = future_to_stock[future]
                try:
                    result = future.result(timeout=30)
                    if result is None:
                        fail_count += 1
                        continue
                    
                    df, from_cache = result
                    if from_cache: cache_hit += 1
                    else: cache_miss += 1
                    
                    if df is not None and not df.empty:
                        df_full_for_chart = df.copy()
                        
                        target_date = pd.Timestamp(scan_date)
                        df = df[df.index <= target_date]
                        
                        if df.empty:
                            fail_count += 1
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
                        fail_count += 1
                except:
                    fail_count += 1
                
                pb.progress((i + 1) / n_stocks_sel)
                cache_rate = (cache_hit / (cache_hit + cache_miss) * 100) if (cache_hit + cache_miss) > 0 else 0
                st_txt.text(f"분석 중... ({i+1}/{n_stocks_sel}) | 발견: {len(results)}개 | 실패: {fail_count}건 | 캐시: {cache_rate:.0f}%")
        
        total_scanned = cache_hit + cache_miss
        cache_rate = (cache_hit / total_scanned * 100) if total_scanned > 0 else 0
        
        if not results:
            st.warning("결과가 없습니다.")
            if fail_count > 0:
                st.error(f"데이터 로드 실패가 {fail_count}건 발생했습니다. 서버 시간 설정이나 네트워크 문제일 수 있습니다.")
        else:
            filtered_results = sorted(results, key=lambda x: x['B/C 상승률'])
            st.session_state['scan_results'] = filtered_results
            st.session_state['scan_market'] = market_sel
            st.session_state['scan_date'] = scan_date
            st.info(f"**성능 통계** | 캐시 활용: {cache_rate:.1f}% ({cache_hit}/{total_scanned}) | API 호출: {cache_miss}회" + (f" | 데이터 로드 실패: {fail_count}건" if fail_count > 0 else ""))

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
        df_disp = df_disp[cols_to_show]
        
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
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("종목명", row_sel['Name'])
            c1.caption(f"Code: {row_sel['Code']}")
            c2.metric("매수가 (검색일 종가)", f"{int(row_sel['매수가']):,}원")
            curr_price = row_sel.get('현재가', 0)
            c2.caption(f"현재가: {int(curr_price):,}원")
            
            pnl = row_sel.get('수익률', 0)
            c3.metric("수익률", f"{pnl:+.1f}%", delta=f"{pnl:+.1f}%")
            if 'Max 수익률' in row_sel:
                c3.caption(f"Max: {row_sel['Max 수익률']:+.1f}% ({row_sel['Max 날짜']})")
                
            c4.metric("현재 상태", row_sel.get('상태', '-'))
            if 'Min 수익률' in row_sel:
                c4.caption(f"Min: {row_sel['Min 수익률']:+.1f}% ({row_sel['Min 날짜']})")
            
            st.markdown("#### 차트 분석")
            df_chart = row_sel['df_daily']
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['Close'], name='가격', line=dict(color='#26a69a', width=2)))
            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MA20'], name='20일선', line=dict(color='#ff9800', width=1, dash='dot'), opacity=0.7))
            
            scan_date_ts = pd.Timestamp(st.session_state.get('scan_date', datetime.now().date()))
            valid_dates = df_chart[df_chart.index <= scan_date_ts].index
            if len(valid_dates) > 0:
                buy_date = valid_dates[-1]
                buy_price = df_chart.loc[buy_date, 'Close']
                fig.add_trace(go.Scatter(
                    x=[buy_date], y=[buy_price], mode='markers+text', name='매수 시점',
                    marker=dict(color='#00ff00', size=15, symbol='triangle-up'),
                    text=['BUY'], textposition='top center', textfont=dict(size=14, color='#00ff00')
                ))
            
            if '상태' in row_sel and '매도' in row_sel['상태']:
                import re
                match = re.search(r'\((\d{4}-\d{2}-\d{2})\)', row_sel['상태'])
                if match:
                    sell_date_str = match.group(1)
                    sell_date_ts = pd.Timestamp(sell_date_str)
                    valid_sell_dates = df_chart[df_chart.index <= sell_date_ts].index
                    if len(valid_sell_dates) > 0:
                        sell_date = valid_sell_dates[-1]
                        sell_price = df_chart.loc[sell_date, 'Close']
                        fig.add_trace(go.Scatter(
                            x=[sell_date], y=[sell_price], mode='markers+text', name='매도 시점',
                            marker=dict(color='#ff0000', size=15, symbol='triangle-down'),
                            text=['SELL'], textposition='bottom center', textfont=dict(size=14, color='#ff0000')
                        ))
            
            for i, level in enumerate(row_sel['segments']):
                fig.add_hline(y=level, line_dash="dash", line_color="rgba(200,200,200,0.2)")
            
            fig.update_layout(template="plotly_dark", height=600, paper_bgcolor="#131722", plot_bgcolor="#131722", hovermode='x unified', showlegend=True)
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
                        scan_data_map[res['Code']] = res['df_daily']

            future_to_bt = {
                executor.submit(
                    process_backtest_stock, 
                    r['Code'], r['Name'], market_sel, cfg, r.to_dict(), 
                    scan_data_map.get(r['Code']),
                    bt_end 
                ): r 
                for _, r in stock_list.iterrows()
            }
            
            for i, future in enumerate(as_completed(future_to_bt)):
                try:
                    r_bt = future.result(timeout=30)
                    if r_bt: bt_results.append(r_bt)
                except: pass
                pb_bt.progress((i+1)/len(future_to_bt))
                
        if bt_results:
            st.session_state['bt_results'] = bt_results

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
        df_summary_display = df_summary_display[final_cols]
        
        if '매수가' in df_summary_display.columns:
            df_summary_display['매수가'] = df_summary_display['매수가'].apply(lambda x: f"{int(x):,}" if pd.notna(x) else '-')
        if '현재가' in df_summary_display.columns:
            df_summary_display['현재가'] = df_summary_display['현재가'].apply(lambda x: f"{int(x):,}" if pd.notna(x) else '-')
        
        st.dataframe(df_summary_display, width=1200, hide_index=True)
