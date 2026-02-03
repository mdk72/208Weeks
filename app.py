import sys
import os

# root path for relative imports
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go
import pytz
from concurrent.futures import ThreadPoolExecutor, as_completed
import warnings
import yfinance as yf

# Suppress external library warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated as an API.*")

import logging

# Configure logging
# Set root level to WARNING to silence noisy library INFO logs (like pykrx)
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    force=True
)

# Enable INFO level for our own project code
logging.getLogger("src").setLevel(logging.INFO)
logging.getLogger("__main__").setLevel(logging.INFO)

# Specifically silence very noisy or buggy external libraries
logging.getLogger("pykrx").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("requests").setLevel(logging.ERROR)
logging.getLogger("yfinance").setLevel(logging.ERROR)
logging.getLogger("selenium").setLevel(logging.ERROR)

# Custom Modules (Refactored paths)
import src.data.utils as utils
import src.data.loader as loader
import src.strategies.reversal_208 as reversal_208
import src.engine.backtester as backtester
import src.stock_analyzer.view as stockeasy_view

from src.data.loader import init_db, fetch_data, get_stock_list_naver, get_historical_market_cap_list, CACHE_DB
from src.strategies.reversal_208 import analyze_stock_core, calculate_screener_performance
from src.engine.backtester import process_backtest_stock
from src.stock_analyzer.db_manager import get_db

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
    saved_settings = utils.load_settings()
    
    # 시장 선택
    market_options = ["KOSPI", "KOSDAQ"]
    try:
        market_idx = market_options.index(saved_settings.get('market', 'KOSPI'))
    except:
        market_idx = 0
    market_sel = st.radio("시장 선택", market_options, index=market_idx)
    
    lookback_sel = st.number_input("조회 기간 (주)", value=saved_settings.get('lookback', 208), step=1, min_value=52)
    n_stocks_sel = st.number_input(
        "분석할 상위 종목 수", 
        min_value=10, 
        max_value=1000, 
        value=saved_settings.get('n_stocks', 200), 
        step=10
    )
    bc_breakout_days = st.number_input(
        "B/C 돌파 확인 기간 (일)", 
        min_value=5, 
        max_value=120, 
        value=saved_settings.get('bc_breakout_days', 60), 
        step=5,
        help="최근 N일 내 B/C 라인 아래 있었는지 확인. 짧을수록 신선한 돌파만, 길수록 더 많은 종목 포함."
    )
    
    # Market Cap Snapshot Section
    st.divider()
    st.caption("**📸 시총 스냅샷 (생존편향 제거)**")
    
    # Show snapshot status
    from src.data import utils, loader
    snapshots = utils.load_market_cap_snapshots()
    snapshot_count = len(snapshots.get('snapshots', {}))
    
    if snapshot_count > 0:
        latest_date = max(snapshots['snapshots'].keys())
        st.info(f"💾 스냅샷 {snapshot_count}개 저장됨 (최신: {latest_date})")
    else:
        st.warning("⚠️ 저장된 스냅샷 없음")
    
    # Snapshot capture button
    if st.button("📸 오늘의 스냅샷 저장", help="지금 시점의 시총 상위 종목을 저장 (생존편향 제거용)"):
        with st.spinner(f"{market_sel} 상위 {n_stocks_sel}종목 가져오는 중..."):
            success, date, result = loader.create_market_cap_snapshot(market_sel, n_stocks_sel)
            
            if success:
                # Save snapshot
                save_ok = utils.save_market_cap_snapshot(result)
                if save_ok:
                    st.success(f"✅ {date} {market_sel} 스냅샷 저장 완료!")
                    st.rerun()
                else:
                    st.error("❌ 스냅샷 저장 실패")
            else:
                st.error(f"❌ 스냅샷 생성 실패: {result}")
    inv_per_stock_sel = st.sidebar.number_input(
        "종목당 투자금 (만원)",
        min_value=100,
        max_value=10000,
        value=saved_settings.get('inv_per_stock', 1000),
        step=100,
        help="개별 종목 진입 시 투자할 금액을 설정합니다."
    )
    
    st.divider()
    if st.button("가격 캐시 초기화", help="저장된 가격 데이터를 모두 삭제하고 새로 내려받습니다."):
        try:
            if os.path.exists(CACHE_DB):
                os.remove(CACHE_DB)
                st.success("캐시가 초기화되었습니다. 다시 스캔해 주세요.")
                st.rerun()
        except Exception as e:
            st.error(f"캐시 삭제 실패: {e}")

tab1, tab2, tab3, tab4 = st.tabs(["실시간 스크리너", "백테스팅", "종목별 상세 분석", "StockEasy 분석"])

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
            load_fail = 0
            cache_hit = 0
            cache_miss = 0
            cache_update = 0 # [NEW] 실시간 업데이트 횟수
            api_calls = 0   # [NEW] 전체 호출 횟수
            insufficient_data = 0
            insufficient_history = 0
            
            load_fail_names = []
            skip_before_ipo_names = []
            skip_low_history_names = []
            
            for i, future in enumerate(as_completed(future_to_stock)):
                stock_row = future_to_stock[future]
                try:
                    result = future.result(timeout=30)
                    # fetch_data returns (df, from_cache), need to check df inside
                    if result is None or result[0] is None:
                        load_fail += 1
                        load_fail_names.append(f"{stock_row['Name']} (Fetch Error)")
                        continue
                    
                    df, status_code = result
                    
                    # [STATISTICS UPDATE] 상세 통계 집계
                    if status_code == "cache_update":
                        cache_update += 1
                        cache_hit += 1 # 캐시 기반이므로 hit로도 집계 (또는 별도 관리)
                    elif status_code == "api":
                        api_calls += 1
                        cache_miss += 1
                    else: # "cache" or True (backward compat)
                        cache_hit += 1
                    
                    # [NEW] Check if today's data is actually present for real-time consistency
                    today_date = datetime.now(kst).date()
                    has_today_data = False
                    if df is not None and not df.empty:
                        last_date = df.index[-1].date()
                        if last_date == today_date:
                            has_today_data = True
                    
                    if status_code == "cache" and not has_today_data:
                         # This implies we had cache but failed to update with Naver intraday
                         # or market is closed/not updated yet.
                         # If market IS open, this is a "Partial Fail" for real-time
                         pass 
                    
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

        # 성능 통계 (Screener)
        perf_msg = f"성능 통계 | 캐시 활용: {cache_rate:.1f}% ({cache_hit}/{total_attempted}) | 네트워크 사용: {api_calls + cache_update}회 (신규: {api_calls}, 갱신: {cache_update})"
        if insufficient_history > 0: perf_msg += f" | {lookback_sel}주 미만(신규상장 등): {insufficient_history}건"
        if load_fail > 0: perf_msg += f" | 로드 실패: {load_fail}건"
        if insufficient_data > 0: perf_msg += f" | 상장 전: {insufficient_data}건"
        
        # [TERMINAL LOG] Summary only (Always print for all markets)
        print(f"\n[Stock Scanner Summary] {perf_msg}")

        if not results:
            st.warning("결과가 없습니다.")
            if load_fail > 0:
                st.error(f"데이터 로드 실패가 {load_fail}건 발생했습니다. 네트워크 상태나 API 제한을 확인해 주세요.")
            
            if insufficient_data > 0 or insufficient_history > 0:
                msg = f"선택하신 날짜({scan_date})에 "
                parts = []
                if insufficient_data > 0: parts.append(f"상장 전 종목({insufficient_data}건)")
                if insufficient_history > 0: parts.append(f"{lookback_sel}주 미만/신규상장({insufficient_history}건)")
                msg += " 및 ".join(parts) + "이 제외되었습니다."

            st.info(perf_msg)
            
        else:
            filtered_results = sorted(results, key=lambda x: x['B/C 상승률'])
            st.session_state['scan_results'] = filtered_results
            st.session_state['scan_market'] = market_sel
            st.session_state['scan_date'] = scan_date
            
            st.success(f"{len(filtered_results)}개 종목 발견! (소요 시간: {min_seconds:.1f}초)")
            
            st.info(perf_msg)
            
            # [TERMINAL LOG] Summary moved up
            
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
                        st.markdown(f"⌛ **{lookback_sel}주 미만 / 신규상장 ({insufficient_history}건)**")
                        st.caption(", ".join(skip_low_history_names))
            
            # --- 결과 표시 ---

    if 'scan_results' in st.session_state:
        # [Fix] 시장 변경 시 이전 결과 숨기기
        if st.session_state.get('scan_market') != market_sel:
            st.warning(f"⚠️ 현재 표시된 결과는 '{st.session_state.get('scan_market')}' 시장의 결과입니다. '{market_sel}' 시장을 분석하려면 '실시간 종목 스캔 시작' 버튼을 눌러주세요.")
        else:
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
            
            if 'Code' in df_disp.columns:
                df_disp['Code'] = df_disp['Code'].apply(lambda x: str(x).zfill(6))
            
            # Define price columns for formatting
            price_cols = ['매수가', '현재가', 'B/C 라인', '208주 최저', '208주 최고']
            for col in price_cols:
                if col in df_disp.columns:
                    df_disp[col] = df_disp[col].apply(lambda x: f"{int(x):,}" if pd.notna(x) else x)
            
            if 'B/C 상승률' in df_disp.columns:
                df_disp['B/C 상승률'] = df_disp['B/C 상승률'].apply(lambda x: f"+{x:.1f}%" if x > 0 else f"{x:.1f}%")

            st.dataframe(df_disp, width='stretch')
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
                
                pnl = row_sel.get('수익률')
                pnl_str = f"{pnl:+.1f}%" if pnl is not None else "-"
                c3.metric("수익률", pnl_str)
                if 'Max 수익률' in row_sel and row_sel['Max 수익률'] is not None:
                    c3.caption(f"Max: {row_sel['Max 수익률']:+.1f}% ({row_sel.get('Max 날짜', '-')})")
                    
                c4.metric("현재 상태", row_sel.get('상태', '-'))
                if 'Min 수익률' in row_sel and row_sel['Min 수익률'] is not None:
                    c4.caption(f"Min: {row_sel['Min 수익률']:+.1f}% ({row_sel.get('Min 날짜', '-')})")
    
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
                st.plotly_chart(fig, width='stretch')

with tab2:
    st.subheader("초고속 백테스팅")
    
    # --- 히스토리 및 비교 섹션 ---
    with st.expander("📊 백테스트 히스토리 분석 및 전략 비교", expanded=False):
        history = utils.load_history()
        if not history:
            st.info("저장된 백테스트 결과가 없습니다. 결과를 실행한 후 하단에서 저장해 주세요.")
        else:
            params_map = {
                "시장 선택": "market",
                "조회 기간 (주)": "lookback",
                "분석할 상위 종목 수": "n_stocks",
                "B/C 돌파 확인 기간 (일)": "bc_breakout_days",
                "B/C 돌파 필수": "buy_breakout",
                "20일선 위 필수": "buy_ma20",
                "진입 구간": "buy_segment",
                "매매 제한 (Cooldown) 기간 (일)": "cooldown_days",
                "목표 경계": "exit_target",
                "익절 방식": "exit_method",
                "익절용 트레일링 스탑 (%)": "profit_trailing_pct",
                "고정 손절 (%)": "stop_loss_pct",
                "방어용 트레일링 스탑 (%)": "defense_trailing_pct",
                "최대 보유 기간 (개월)": "max_holding_months",
                "B/C 라인 이탈 매도 (일)": "bc_exit_days",
                "종료일 기준 강제 청산": "force_liquidate",
                "종목당 투자금": "inv_per_stock",
                "시작일": "start_date",
                "종료일": "end_date"
            }
            # 요약 테이블
            hist_summary = []
            for i, h in enumerate(history):
                m = h['metrics']
                p = h['params']
                record = {
                    "No": i,
                    "라벨": h['label'],
                    "저장시각": h['timestamp'],
                }
                # 파라미터 정보 추가
                for label, key in params_map.items():
                    if key in p:
                        record[label] = p[key]
                
                # 지표 정보 추가
                record.update({
                    "평균누적": f"{m['avg_cum_pnl']:+.1f}%",
                    "승률": f"{m['avg_win_rate']:.1f}%",
                    "MDD": f"{m['avg_mdd']:.1f}%",
                    "CAGR": f"{m['avg_annualized']:.1f}%",
                    "포트CAGR": f"{m['portfolio_cagr']:.1f}%",
                    "포트MDD": f"{m.get('portfolio_mdd', 0):.1f}%",
                    "초기 자본금": f"{m.get('initial_capital', 0)/10000:,.0f}만원"
                })
                hist_summary.append(record)
            
            st.dataframe(pd.DataFrame(hist_summary), hide_index=True, width='stretch')
            
            # 비교 도구
            st.markdown("##### 🔍 전략 상세 비교")
            selected_indices = st.multiselect(
                "비교할 결과들을 선택하세요 (최대 4개 권장)", 
                options=range(len(history)), 
                format_func=lambda x: f"{history[x]['label']} ({history[x]['timestamp']})"
            )
            
            if selected_indices:
                comp_data = []
                metrics_map = {
                    "평균 누적 수익률": "avg_cum_pnl",
                    "평균 승률": "avg_win_rate",
                    "평균 MDD": "avg_mdd",
                    "평균 연환산(CAGR)": "avg_annualized",
                    "포트폴리오 CAGR": "portfolio_cagr",
                    "포트폴리오 MDD": "portfolio_mdd",
                    "평균 수익": "avg_profit",
                    "평균 손실": "avg_loss"
                }
                for label, key in metrics_map.items():
                    row = {"지표": label}
                    for idx in selected_indices:
                        val = history[idx]['metrics'].get(key, 0)
                        suffix = "%" if any(x in label for x in ["수익률", "CAGR", "승률", "MDD", "수익", "손실"]) else ""
                        row[history[idx]['label']] = f"{val:+.1f}{suffix}" if val != 0 else "0.0%"
                    comp_data.append(row)
                
                st.divider()
                for label, key in params_map.items():
                    row = {"지표": f"⚙️ {label}"}
                    for idx in selected_indices:
                        row[history[idx]['label']] = str(history[idx]['params'].get(key, "-"))
                    comp_data.append(row)
                
                st.table(pd.DataFrame(comp_data).set_index("지표"))

            if st.button("🗑️ 히스토리 전체 삭제"):
                if st.session_state.get('confirm_del_all', False):
                    utils.save_history([])
                    st.success("모든 히스토리가 삭제되었습니다.")
                    st.session_state['confirm_del_all'] = False
                    st.rerun()
                else:
                    st.warning("정말로 모든 히스토리를 삭제하시겠습니까? 한 번 더 클릭하면 확정됩니다.")
                    st.session_state['confirm_del_all'] = True

    c1_setup, c2_setup = st.columns(2)
    with c1_setup:
        with st.expander("1. 진입 전략 (Entry)", expanded=True):
            bt_brk = st.checkbox("B/C 돌파 필수", value=True)
            bt_ma = st.checkbox("20일선 위 필수", value=True)
            bt_seg = st.selectbox("진입 구간", ["Segment C (B/C~C/D)", "Segment B (A/B~B/C)"])
            bt_volume_filter = st.checkbox(
                "거래량 돌파 확인",
                value=False,
                help="B/C 라인 돌파일 거래량이 20일 평균의 1.5배 이상인 종목만 선택 (모멘텀 확인)"
            )
            bt_cooldown = st.number_input(
                "매매 제한 (Cooldown) 기간 (일)", 
                min_value=0, max_value=365, 
                value=int(saved_settings.get('cooldown_days', 0)),
                help="매도 후 N일 동안은 동일 종목을 재매수하지 않음 (0은 비활성)"
            )
        
        with st.expander("2. 익절 전략 (Profit Taking)", expanded=True):
            bt_tgt = st.selectbox("목표 경계", ["D/E Boundary", "C/D Boundary", "E/F Boundary"], index=["D/E Boundary", "C/D Boundary", "E/F Boundary"].index(saved_settings.get('exit_target', 'D/E Boundary')))
            
            met_options = ["목표 도달 후 20일선 이탈", "목표가 도달 시 즉시 매도", "목표가 도달 후 트레일링스탑"]
            saved_met = saved_settings.get('exit_method', "목표 도달 후 20일선 이탈")
            try:
                met_idx = met_options.index(saved_met)
            except:
                met_idx = 0
            bt_met = st.radio("익절 방식", met_options, index=met_idx)
            
            # 익절용 트레일링 스톱 (조건부 노출)
            if bt_met == "목표가 도달 후 트레일링스탑":
                bt_profit_ts = st.number_input(
                    "익절용 트레일링 스톱 (%)", 
                    min_value=0.0, max_value=100.0, 
                    value=float(saved_settings.get('profit_trailing_pct', 0.0)), 
                    step=0.5,
                    help="목표가에 도달한 시점부터 고점 대비 N% 하락 시 익절 매도"
                )
            else:
                bt_profit_ts = 0.0

    with c2_setup:
        with st.expander("3. 리스크 관리 (Risk Management)", expanded=True):
            bt_sl_input = st.text_input(
                "고정 손절 (%)", 
                value=str(float(saved_settings.get('stop_loss_pct', 0.0))),
                help="매수가 대비 하락 시 즉시 손절 (0은 비활성)"
            )
            try:
                bt_sl = float(bt_sl_input) if bt_sl_input else 0.0
            except:
                bt_sl = 0.0
            
            bt_defense_ts_input = st.text_input(
                "방어용 트레일링 스톱 (%)", 
                value=str(float(saved_settings.get('defense_trailing_pct', 0.0))),
                help="매수 직후부터 실시간으로 고점 대비 N% 하락 시 원금 보호 매도"
            )
            try:
                bt_defense_ts = float(bt_defense_ts_input) if bt_defense_ts_input else 0.0
            except:
                bt_defense_ts = 0.0
            
            bt_max_months_input = st.text_input(
                "최대 보유 기간 (개월)", 
                value=str(int(saved_settings.get('max_holding_months', 0))),
                help="설정 기간이 지나면 수익 여부와 상관없이 매도 (0은 비활성)"
            )
            try:
                bt_max_months = int(bt_max_months_input) if bt_max_months_input else 0
            except:
                bt_max_months = 0
            bt_bc_exit_days = st.number_input(
                "B/C 라인 이탈 매도 (일)", 
                min_value=0, max_value=30, 
                value=saved_settings.get('bc_exit_days', 0),
                help="주가가 B/C 라인 아래로 내려가서 N일 이상 머무르면 손절 (0은 비활성)"
            )
    
    bt_inv_amount = st.number_input("종목당 투자금 (만원)", min_value=100, max_value=10000, value=int(saved_settings.get('inv_per_stock', 1000)), step=100, key="bt_inv")

    with st.expander("백테스트 기간 설정", expanded=False):
        col_d1, col_d2 = st.columns(2)
        
        # 날짜 설정 불러오기
        saved_start = saved_settings.get('bt_start_date', '2023-01-02')
        saved_end = saved_settings.get('bt_end_date', datetime.now().strftime('%Y-%m-%d'))
        try:
            default_start = datetime.strptime(saved_start, '%Y-%m-%d')
            default_end = datetime.strptime(saved_end, '%Y-%m-%d')
        except:
            default_start = datetime(2023, 1, 2)
            default_end = datetime.now()

        with col_d1:
            bt_start = st.date_input("시작일", value=default_start, max_value=datetime(2030, 12, 31), key="bt_start_date")
        with col_d2:
            bt_end = st.date_input("종료일", value=default_end, max_value=datetime(2030, 12, 31), key="bt_end_date")
            
    with st.expander("보유 포지션 처리", expanded=False):
        bt_force_liquidate = st.checkbox(
            "종료일 기준 강제 청산", value=False,
            help="체크: 보유 중인 포지션을 종료일 가격으로 강제 청산\n해제: 보유 중인 포지션을 '보유중'으로 표시"
        )

    if st.button("초고속 분석 시작"):
        # [Point-in-Time Universe] 백테스트 시작일 기준 시총 리스트 가져오기 (생존편향 제거)
        with st.spinner(f"{bt_start.strftime('%Y-%m-%d')} 기준 {market_sel} 시총 상위 {n_stocks_sel}개 종목 리스트를 구성 중..."):
            stock_list, source = loader.get_stock_universe_for_date(bt_start, market_sel, n_stocks_sel)
        
        # Display source information
        if source.startswith('snapshot_'):
            date_used = source.split('_')[1]
            st.success(f"✅ {date_used} 스냅샷 사용 (생존편향 제거됨)")
        elif source == 'historical_pykrx':
            st.success(f"✅ {bt_start.strftime('%Y-%m-%d')} pykrx 데이터 사용 (생존편향 제거됨)")
        else:
            st.warning(
                f"{bt_start.strftime('%Y-%m-%d')} 이전 스냅샷 없음. 현재 시점 리스트를 사용합니다.",
                icon="⚠️"
            )
            st.info(
                "**참고**: 지금부터 스냅샷을 저장하면 미래 백테스트에서 생존편향을 제거할 수 있습니다!",
                icon="💡"
            )
        
        # [NOTE] 과거 시점 유니버스일 경우, 현재 스크리너 결과를 합치는 것은 논리적으로 맞지 않을 수 있음
        # 하지만 사용자가 "현재 관심 종목"의 과거 성과도 보고 싶을 수 있으므로 옵션으로 유지하거나
        # 명확히 구분하는 것이 좋음. 여기서는 생존편향 제거가 목적이므로, 과거 유니버스에 집중하기 위해 자동 병합은 생략하거나 경고.
        # 일단 사용자 요청에 따라 "유니버스 구성" 자체에 집중.
        
        cfg = {
            'buy_breakout':bt_brk, 'buy_ma20':bt_ma, 'buy_segment':bt_seg, 
            'exit_target':bt_tgt, 'exit_method':bt_met, 'stop_loss_pct':bt_sl,
            'start_date': bt_start.strftime('%Y-%m-%d'),
            'end_date': bt_end.strftime('%Y-%m-%d'),
            'force_liquidate': bt_force_liquidate,
            'lookback': lookback_sel,
            'bc_breakout_days': bc_breakout_days,
            'max_holding_months': bt_max_months,
            'defense_trailing_pct': bt_defense_ts,
            'profit_trailing_pct': bt_profit_ts,
            'bc_exit_days': bt_bc_exit_days,
            'cooldown_days': bt_cooldown,
            'inv_per_stock': bt_inv_amount,
            'volume_filter': bt_volume_filter
        }
        
        bt_results = []
        pb_bt = st.progress(0)
        
        excluded_no_data = 0
        excluded_short_history = 0
        delisted_count = 0
        active_count = 0
        
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
            
            cache_hit_bt = 0
            cache_miss_bt = 0
            
            error_count = 0
            for i, future in enumerate(as_completed(future_to_bt)):
                stock_row = future_to_bt[future]
                try:
                    r_bt = future.result(timeout=60) # Increased timeout
                    if r_bt: 
                        status = r_bt.get('status', 'active')
                        
                        if status == 'excluded_no_data':
                            excluded_no_data += 1
                        elif status == 'excluded_short_history':
                            excluded_short_history += 1
                        elif status == 'delisted':
                            delisted_count += 1
                            bt_results.append(r_bt)
                        elif status == 'error':
                            error_count += 1
                            bt_results.append(r_bt)
                        else: # active or no_trades
                            active_count += 1
                            bt_results.append(r_bt)
                            
                        if r_bt.get('from_cache'):
                            cache_hit_bt += 1
                        else:
                            cache_miss_bt += 1
                    else:
                        error_count += 1
                        bt_results.append({
                            'Ticker': stock_row['Code'], 'Name': stock_row['Name'],
                            'status': 'error', 'exit_reason': '분석 결과 없음 (None)'
                        })
                except Exception as e:
                    error_count += 1
                    bt_results.append({
                        'Ticker': stock_row['Code'], 'Name': stock_row['Name'],
                        'status': 'error', 'exit_reason': f"Thread Error: {str(e)}"
                    })
                pb_bt.progress((i+1)/len(future_to_bt))
            
            # [LOGIC IMPROVED] No longer using manual estimation loop
            total_bt = len(bt_results)
            
        if bt_results:
            st.session_state['bt_results'] = bt_results
            
            # 성능 통계 (Backtest)
            total_processed_bt = cache_hit_bt + cache_miss_bt
            cache_rate_bt = (cache_hit_bt / total_processed_bt * 100) if total_processed_bt > 0 else 0
            
            stats_msg = f"분석 완료 | 유효: {active_count}개 | 상장폐지: {delisted_count}개 | 오류: {error_count}개"
            if excluded_no_data > 0 or excluded_short_history > 0:
                stats_msg += f" | 제외: {excluded_no_data + excluded_short_history}건 (데이터부족 등)"
            
            st.info(stats_msg)
            st.caption(f"캐시 활용: {cache_rate_bt:.1f}%")

    if 'bt_results' in st.session_state:
        bt_res = st.session_state['bt_results']
        
        st.subheader("백테스팅 결과 요약")
        df_summary = pd.DataFrame(bt_res).drop(columns=['df_daily', 'trades'], errors='ignore')
        
        # [UI OPTION] Allow users to toggle between filtered and full view
        show_all_filter = st.checkbox(
            "거래 없는 종목 포함 (전체 보기)", 
            value=False,
            help="체크: 모든 종목 표시 / 해제: 거래가 있는 종목만 표시"
        )
        
        if 'status' in df_summary.columns:
            if not show_all_filter:
                # Filter to show only stocks with trades or new signals
                mask_relevant = (df_summary['Trades'] > 0) | (df_summary['Recent Sell'] == 'New') | (df_summary['status'] == 'error')
                df_relevant = df_summary[mask_relevant].copy()
                
                if df_relevant.empty and not df_summary.empty:
                    st.warning("경고: 거래가 있는 종목이 없습니다. 전체 보기로 전환하세요.")
                    df_relevant = df_summary.copy()
                
                df_summary = df_relevant

        # Ensure sorting works by using a hidden datetime column
        if not df_summary.empty and 'Recent Buy' in df_summary.columns and 'Recent Sell' in df_summary.columns:
            df_summary['_is_new'] = df_summary['Recent Sell'] == 'New'
            
            # Robust date conversion for sorting
            def to_dt(x):
                try: 
                    # Extract date part if it's formatted string "YYYY-MM-DD (...)"
                    if isinstance(x, str): return pd.to_datetime(x[:10], errors='coerce')
                    return pd.to_datetime(x, errors='coerce')
                except: return pd.NaT
                
            df_summary['_sort_date'] = df_summary['Recent Buy'].apply(to_dt)
            
            # Sort: New signals first, then by most trades, then by most recent buy date
            df_summary = df_summary.sort_values(by=['_is_new', 'Trades', '_sort_date'], ascending=[False, False, False])
            
            df_summary.drop(columns=['_is_new', '_sort_date'], inplace=True, errors='ignore')
        
        df_summary = df_summary.reset_index(drop=True)
        df_summary.insert(0, 'No.', range(len(df_summary)))
        
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
        
        # [NOTE] We delay dropping columns until after the renaming and display selection logic.
        
        if 'Max 수익률' in df_summary.columns and 'Max 날짜' in df_summary.columns:
            def format_max_pnl(row):
                val = row['Max 수익률']
                dt = row['Max 날짜']
                if pd.isna(val) or val is None: return '-'
                prefix = "+" if val >= 0 else ""
                return f"{prefix}{val:.1f}% ({dt})"
            df_summary['Max 수익/날짜'] = df_summary.apply(format_max_pnl, axis=1)
        
        if 'Min 수익률' in df_summary.columns and 'Min 날짜' in df_summary.columns:
            def format_min_pnl(row):
                val = row['Min 수익률']
                dt = row['Min 날짜']
                if pd.isna(val) or val is None: return '-'
                return f"{val:.1f}% ({dt})"
            df_summary['Min 수익/날짜'] = df_summary.apply(format_min_pnl, axis=1)
        
        pnl_cols = ['Total PnL (%)', 'Win Rate (%)', 'Current PnL (%)', 'Realized PnL (%)']
        for col in pnl_cols:
            if col in df_summary.columns:
                df_summary[col] = df_summary[col].apply(lambda x: f"{x:.1f}" if pd.notna(x) else '-')
        
        # [ROBUST] Ensure all key columns exist in df_summary
        for c_req in ['Ticker', 'Name', 'Recent Buy Price', 'Recent Sell Price', 'Current PnL (%)', 
                     'Realized PnL (%)', 'Max 수익/날짜', 'Min 수익/날짜', 'Total PnL (%)', 
                     'Trades', 'Win Rate (%)', 'Duration', 'exit_reason', 'Recent Buy', 'Recent Sell']:
            if c_req not in df_summary.columns:
                df_summary[c_req] = '-'

        df_summary_display = df_summary.copy()
        
        # Rename for user-friendly display
        df_summary_display = df_summary_display.rename(columns={
            'Ticker': 'Code',
            'Recent Buy Price': '매수가',
            'Recent Sell Price': '현재가/매도가',
            'Current PnL (%)': '보유 수익률 (%)',
            'Realized PnL (%)': '실현 수익률 (%)',
            'Total PnL (%)': '누적 수익률 (%)',
            'Duration': '보유일',
            'exit_reason': '상태/메모'
        })
        
        # Explicit order for presentation
        final_cols = [
            'No.', 'Code', 'Name', '매수가', '현재가/매도가', 
            '보유 수익률 (%)', '실현 수익률 (%)', 
            'Max 수익/날짜', 'Min 수익/날짜', 
            '누적 수익률 (%)', 'Trades', 'Win Rate (%)', 
            '보유일', '상태/메모', 'Recent Buy', 'Recent Sell'
        ]
        
        # Filter only existing ones
        final_cols = [c for c in final_cols if c in df_summary_display.columns]
        df_summary_display = df_summary_display[final_cols].copy()
        
        if 'Code' in df_summary_display.columns:
            df_summary_display['Code'] = df_summary_display['Code'].apply(lambda x: str(x).zfill(6))
        
        # Add status info for transparency
        if 'status' in df_summary.columns and '상태/메모' in df_summary_display.columns:
            df_summary_display['상태'] = df_summary['status'].apply(
                lambda x: {
                    'active': '정상',
                    'no_trades': '거래없음',
                    'error': '오류',
                    'excluded_no_data': '데이터없음',
                    'excluded_short_history': '부족',
                    'delisted': '상장폐지'
                }.get(x, x)
            )
        
        if '매수가' in df_summary_display.columns:
            df_summary_display['매수가'] = df_summary_display['매수가'].apply(lambda x: f"{int(x):,}" if pd.notna(x) and x != '-' else x)
        if '현재가/매도가' in df_summary_display.columns:
            df_summary_display['현재가/매도가'] = df_summary_display['현재가/매도가'].apply(lambda x: f"{int(x):,}" if pd.notna(x) and x != '-' else x)

        # [NEW] StockEasy 데이터 통합
        try:
            # 1. DB에서 최신 데이터 가져오기
            codes = df_summary['Ticker'].tolist()
            se_df = get_db().get_latest_data(codes)
            
            # 2. 컬럼 기본값으로 초기화 (항상 표시되도록)
            se_columns = ['종합점수', '재무점수', '재무', '성장', '수익성', '안정성', '밸류']
            for col in se_columns:
                df_summary_display[col] = '-'
            
            if not se_df.empty:
                # 3. 사용 가능한 컬럼 매핑
                rename_map = {
                    'composite_score': '종합점수',
                    'financial_score': '재무점수', 
                    'financial_grade': '재무',
                    'growth_grade': '성장',
                    'profitability_grade': '수익성',
                    'stability_grade': '안정성',
                    'valuation_grade': '밸류'
                }
                
                available_cols = [c for c in rename_map.keys() if c in se_df.columns]
                
                if available_cols:
                    se_subset = se_df[['code'] + available_cols].copy()
                    se_subset = se_subset.rename(columns={'code': 'Code', **rename_map})
                    
                    # 병합 (기존 기본값 덮어쓰기)
                    df_summary_display = df_summary_display.drop(columns=[rename_map[c] for c in available_cols], errors='ignore')
                    df_summary_display = pd.merge(df_summary_display, se_subset, on='Code', how='left')
                
                # 4. 포맷팅 (점수는 정수로, 등급은 그대로)
                for col in ['종합점수', '재무점수']:
                    if col in df_summary_display.columns:
                        df_summary_display[col] = df_summary_display[col].apply(
                            lambda x: f"{int(x)}" if pd.notna(x) and x != '-' else "-"
                        )
                        
                for col in ['재무', '성장', '수익성', '안정성', '밸류']:
                    if col in df_summary_display.columns:
                        df_summary_display[col] = df_summary_display[col].fillna("-")

            # 5. 컬럼 순서 재배치 (Name 뒤에 StockEasy 데이터 위치)
            curr_cols = df_summary_display.columns.tolist()
            base_cols_head = ['No.', 'Code', 'Name']
            
            head_exist = [c for c in base_cols_head if c in curr_cols]
            se_exist = [c for c in se_columns if c in curr_cols]
            others = [c for c in curr_cols if c not in head_exist and c not in se_exist]
            
            final_order = head_exist + se_exist + others
            df_summary_display = df_summary_display[final_order]
                
        except Exception as e:
            # 통합 실패해도 백테스트 결과는 보여줘야 함
            print(f"StockEasy data merge failed: {e}")
            import traceback
            traceback.print_exc()
            pass

        st.dataframe(df_summary_display, width='stretch', hide_index=True)
        
        # --- Summary Section ---
        st.markdown("#### 백테스팅 종합 요약")
        
        # Calculate summary metrics
        # Filter for rows that actually have trades to make summary more meaningful
        df_trades_only = df_summary[df_summary['Trades'] > 0].copy()
        
        if not df_trades_only.empty:
            # 1. Basic Stats
            def to_float(x):
                try: return float(x)
                except: return 0.0
                
            avg_cum_pnl = df_trades_only['Total PnL (%)'].apply(to_float).mean()
            avg_win_rate = df_trades_only['Win Rate (%)'].apply(to_float).mean()
            total_trades = df_trades_only['Trades'].sum()
            
            # 2. Advanced Metrics (Average of per-stock metrics)
            all_tradeds = []
            for r in bt_res:
                if r.get('Trades', 0) > 0 and 'trades' in r:
                    all_tradeds.append(r)
            
            if all_tradeds:
                all_pnls = []
                winning_pnls = []
                losing_pnls = []
                mdds = []
                sharpes = []
                annualized_returns = []
                
                # Backtest period in years for CAGR
                bt_period_days = (pd.Timestamp(bt_end) - pd.Timestamp(bt_start)).days
                bt_years = bt_period_days / 365.25 if bt_period_days > 0 else 1.0
                
                for r in all_tradeds:
                    stock_trades = r['trades']
                    stock_pnls = [t['pnl'] for t in stock_trades]
                    all_pnls.extend(stock_pnls)
                    winning_pnls.extend([p for p in stock_pnls if p > 0])
                    losing_pnls.extend([p for p in stock_pnls if p < 0])
                    
                    # MDD calculation for this stock
                    # Better: calculate MDD from equity curve starting at 1.0
                    equity_curve = pd.concat([pd.Series([1.0]), (1 + pd.Series(stock_pnls) / 100).cumprod()])
                    peak = equity_curve.cummax()
                    drawdown = (equity_curve - peak) / peak
                    mdds.append(drawdown.min() * 100)
                    
                    # Sharpe Ratio (Simple version: mean/std of trade returns)
                    if len(stock_pnls) > 1:
                        std_pnl = pd.Series(stock_pnls).std()
                        sharpes.append(pd.Series(stock_pnls).mean() / std_pnl if std_pnl > 0 else 0.0)
                    
                    # Annualized Return (CAGR)
                    total_ret = (1 + r['Total PnL (%)'] / 100)
                    cagr = (total_ret ** (1 / bt_years) - 1) * 100 if bt_years > 0 else 0.0
                    annualized_returns.append(cagr)

                avg_profit = np.mean(winning_pnls) if winning_pnls else 0.0
                avg_loss = np.mean(losing_pnls) if losing_pnls else 0.0
                avg_mdd = np.mean(mdds) if mdds else 0.0
                avg_sharpe = np.mean(sharpes) if sharpes else 0.0
                avg_annualized = np.mean(annualized_returns) if annualized_returns else 0.0
                
                # First Row
                c_sum1, c_sum2, c_sum3 = st.columns(3)
                c_sum1.metric("종목당 평균 누적 수익률", f"{avg_cum_pnl:+.1f}%")
                c_sum2.metric("평균 승률", f"{avg_win_rate:.1f}%")
                c_sum3.metric("전체 거래 횟수", f"{int(total_trades)}회")
                
                # Second Row (Advanced)
                c_adv1, c_adv2, c_adv3 = st.columns(3)
                c_adv1.metric("평균 수익 / 손실", f"{avg_profit:+.1f}% / {avg_loss:.1f}%")
                p_l_ratio = abs(avg_profit / avg_loss) if avg_loss != 0 else 0
                c_adv1.caption(f"손익비: {p_l_ratio:.2f}")
                
                c_adv2.metric("평균 MDD", f"{avg_mdd:.1f}%")
                c_adv2.caption("종목별 최대 낙폭 평균")
                
                c_adv3.metric(
                    "평균 연환산 수익률", 
                    f"{avg_annualized:+.1f}%",
                    help=f"백테스트 전체 기간({bt_years:.1f}년) 기준 기하평균 수익률입니다. 누적 수익률을 연단위로 환산한 수치입니다."
                )
                if sharpes:
                    c_adv3.caption(f"평균 샤프 지수: {avg_sharpe:.2f}")
                
                # --- Portfolio Asset Trend Simulation ---
                st.markdown("#### 포트폴리오 자산 추이 (현금 vs 주식)")
                
                # Get full date range
                all_dates = pd.date_range(start=bt_start, end=bt_end, freq='D')
                
                # Initialize daily metrics
                # For simplicity, assume initial capital is enough to cover all trades (infinite pool)
                # or calculate based on 10M * max simultaneous trades.
                # Let's show "Investment Scale" and "Total Asset Progress"
                
                daily_data = pd.DataFrame(index=all_dates)
                daily_data['Invested'] = 0.0  # Current market value of held stocks
                daily_data['Realized'] = 0.0  # Cumulative profit/loss from closed trades
                
                # Track concurrent trades to show "Used Capital"
                daily_data['Used_Capital'] = 0.0
                
                for r in all_tradeds:
                    s_df = r.get('df_daily')
                    if s_df is None or s_df.empty: continue
                    
                    # Reindex to full range for this stock
                    s_df = s_df.reindex(all_dates).ffill()
                    
                    for t in r['trades']:
                        entry_dt = pd.Timestamp(t['entry_date']).floor('D')
                        if all_dates.empty:
                            exit_dt = entry_dt # Fallback if dates are messed up
                        else:
                            exit_dt = pd.Timestamp(t['exit_date']).floor('D') if t['exit_date'] else all_dates[-1]
                        
                        entry_price = t['entry_price']
                        inv_amount = bt_inv_amount * 10000
                        shares = inv_amount / entry_price
                        
                        # Apply to timeline
                        mask = (daily_data.index >= entry_dt) & (daily_data.index <= exit_dt)
                        
                        # Market Value (Stock Asset)
                        prices = s_df.loc[mask, 'Close']
                        daily_data.loc[mask, 'Invested'] += (shares * prices).fillna(value=inv_amount)
                        
                        # Used Capital tracking
                        daily_data.loc[mask, 'Used_Capital'] += inv_amount
                        
                        # Realized Profit (Add to 'Realized' after exit)
                        if t['exit_date']:
                            exit_proceeds = shares * t['exit_price']
                            profit = exit_proceeds - inv_amount
                            daily_data.loc[daily_data.index > exit_dt, 'Realized'] += profit
                
                # Calculate Total Asset and Cash
                # Let's assume Initial Capital = Max Used Capital (or at least 300M)
                initial_capital = max(daily_data['Used_Capital'].max(), 200000000)
                
                daily_data['Cash'] = initial_capital - daily_data['Used_Capital'] + daily_data['Realized']
                daily_data['Total_Asset'] = daily_data['Cash'] + daily_data['Invested']
                
                # Display Summary Metrics for Portfolio
                p_total_ret = (daily_data['Total_Asset'].iloc[-1] / initial_capital - 1) * 100
                p_cagr = ((daily_data['Total_Asset'].iloc[-1] / initial_capital) ** (1/bt_years) - 1) * 100 if bt_years > 0 else 0
                
                # Calculate Portfolio MDD
                rolling_max = daily_data['Total_Asset'].cummax()
                drawdown = (daily_data['Total_Asset'] - rolling_max) / rolling_max * 100
                p_mdd = drawdown.min()
                
                col_p1, col_p2, col_p3, col_p4 = st.columns(4)
                col_p1.metric("포트폴리오 총 누적 수익률", f"{p_total_ret:+.1f}%", help=f"초기 자본금 {initial_capital/100000000:.1f}억원 대비 수익률")
                col_p2.metric("포트폴리오 연환산 수익률", f"{p_cagr:+.1f}%")
                col_p3.metric("포트폴리오 MDD", f"{p_mdd:.1f}%")
                col_p4.metric("초기 자본금", f"{initial_capital/10000:,.0f}만원")
                
                # Prepared for Chart
                chart_data = daily_data[['Cash', 'Invested']].copy()
                chart_data.columns = ['현금 자산', '주식 자산']
                
                st.area_chart(chart_data)
                
                st.line_chart(daily_data['Total_Asset'], width='stretch')
                st.caption("위 차트는 종목당 투자 금액을 가정한 포트폴리오 전체 자산 합계(현금 + 평가금액) 추이입니다.")

                # --- NEW: Market Comparison Analysis ---
                st.divider()
                st.markdown("#### 📈 시장 지수 대비 자산 비중 분석")
                
                with st.spinner("시장 지수 데이터 로드 및 분석 중..."):
                    # Use correct ticker symbols: ^KQ11 for KOSDAQ, ^KS11 for KOSPI
                    idx_ticker = "^KQ11" if market_sel == "KOSDAQ" else "^KS11"
                    try:
                        idx_df = yf.download(idx_ticker, start=bt_start.strftime('%Y-%m-%d'), end=bt_end.strftime('%Y-%m-%d'), progress=False, auto_adjust=True)
                        if not idx_df.empty:
                            if isinstance(idx_df.columns, pd.MultiIndex):
                                idx_df.columns = idx_df.columns.get_level_values(0)
                            
                            # Align and Normalize
                            comp_df = pd.DataFrame(index=daily_data.index)
                            comp_df['Portfolio'] = daily_data['Total_Asset']
                            comp_df['Market'] = idx_df['Close'].reindex(comp_df.index).ffill()
                            comp_df['Stock_Weight'] = (daily_data['Invested'] / daily_data['Total_Asset']) * 100
                            
                            # Normalize to start at 100
                            p_start = comp_df['Portfolio'].iloc[0]
                            m_start = comp_df['Market'].dropna().iloc[0] if not comp_df['Market'].dropna().empty else 1
                            
                            comp_df['Portfolio_Norm'] = (comp_df['Portfolio'] / p_start) * 100
                            comp_df['Market_Norm'] = (comp_df['Market'] / m_start) * 100
                            
                            # Create Dual-Axis Chart
                            from plotly.subplots import make_subplots
                            fig_comp = make_subplots(specs=[[{"secondary_y": True}]])
                            
                            # Portfolio & Market (Primary Y)
                            fig_comp.add_trace(
                                go.Scatter(x=comp_df.index, y=comp_df['Portfolio_Norm'], name="포트폴리오 (Normalized)", line=dict(color="#3498db", width=2)),
                                secondary_y=False,
                            )
                            fig_comp.add_trace(
                                go.Scatter(x=comp_df.index, y=comp_df['Market_Norm'], name=f"시장지수 ({idx_ticker})", line=dict(color="rgba(150,150,150,0.5)", width=1.5, dash='dot')),
                                secondary_y=False,
                            )
                            
                            # Stock Weight (Secondary Y)
                            fig_comp.add_trace(
                                go.Scatter(
                                    x=comp_df.index, y=comp_df['Stock_Weight'], name="주식 비중 (%)", 
                                    line=dict(color="#e67e22", width=1), fill='tozeroy', fillcolor='rgba(230, 126, 34, 0.1)'
                                ),
                                secondary_y=True,
                            )
                            
                            fig_comp.update_layout(
                                title_text="시장 지수 vs 포트폴리오 수익률 및 주식 비중",
                                template="plotly_white", height=500, hovermode='x unified',
                                margin=dict(l=20, r=20, t=50, b=20),
                                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                            )
                            fig_comp.update_yaxes(title_text="수익률 지수 (시작점=100)", secondary_y=False)
                            fig_comp.update_yaxes(title_text="주식 비중 (%)", secondary_y=True, range=[0, 100])
                            
                            st.plotly_chart(fig_comp, width='stretch')
                            
                            # Reasoning Analysis
                            st.info("💡 **전략 합리성 분석**")
                            
                            # Calculate correlation between Index movement and Weight
                            m_returns = comp_df['Market_Norm'].pct_change(20) # 20일 수익률
                            w_change = comp_df['Stock_Weight'].diff(20)      # 20일 비중 변화
                            
                            # Correlation check logic
                            if not m_returns.dropna().empty and not w_change.dropna().empty:
                                corr = m_returns.corr(w_change)
                                
                                # 208-Week 전략은 본질적으로 역발상 전략입니다
                                # 음수 상관관계가 정상이며, 이는 가치 투자 원칙과 일치합니다
                                if corr < -0.2:
                                    st.success(f"✅ **역발상 가치 전략**: 시장 하락기에 낙폭과대주를 매수하고, 상승기에 목표가 도달 시 익절하는 건전한 패턴입니다. 이는 208-Week 전략의 핵심 원리와 일치합니다. (상관계수: {corr:.2f})")
                                elif corr > 0.2:
                                    st.warning(f"⚠️ **추세 추종형**: 시장 상승기에 비중을 늘리는 경향이 있습니다. 208-Week 역발상 전략의 본질과 다소 상충될 수 있으니, 진입 시점이 과도하게 늦어지지 않는지 점검이 필요합니다. (상관계수: {corr:.2f})")
                                else:
                                    st.write(f"ℹ️ **중립/독자 행보**: 시장 지수와 주식 비중 간의 뚜렷한 연관성이 낮습니다. 개별 종목의 역발상 모멘텀에 더 집중하는 전략입니다. (상관계수: {corr:.2f})")
                            
                            # Descriptive Analysis
                            st.markdown(f"""
                            **📊 208-Week 전략의 특성 (역발상 가치 투자)**
                            - **시장 하락기**: 많은 종목이 208주 최저점 근처로 하락 → B/C 라인 돌파 → 동시다발 매수 → **주식 비중 증가** (주황색 영역 확대)
                            - **시장 상승기**: 보유 종목들이 목표가(D/E 등) 도달 → 익절 매도 → **현금 확보** (주황색 영역 축소)
                            - **시장 고점**: 대부분 익절 완료 → 현금 비중 최대 → 다음 하락장 대기 (위험 회피)
                            - **누적 수익률**: 파란색 선(포트폴리오)이 회색 점선(시장)보다 위에 머문다면 시장 대비 초과 수익(Alpha)을 창출하고 있는 것입니다.
                            
                            > 💡 **핵심**: 음의 상관관계(-0.2 이하)는 "싸게 사서 비싸게 판다"는 가치 투자 원칙의 증거입니다.
                            """)
                        else:
                            st.warning("시장 지수 데이터를 불러올 수 없어 분석을 건너뜁니다.")
                    except Exception as e:
                        st.error(f"지수 분석 중 오류: {e}")

                # --- Save Results Section ---
                st.divider()
                st.markdown("#### 💾 백테스트 결과 저장")
                save_col1, save_col2 = st.columns([3, 1])
                res_label = save_col1.text_input("결과 라벨 (예: 208주 전략_보유24개월)", placeholder="라벨을 입력해 주세요")
                if save_col2.button("현재 결과 저장", width='stretch'):
                    if not res_label:
                        st.error("라벨을 입력해 주세요.")
                    else:
                        history = utils.load_history()
                        current_record = {
                            'label': res_label,
                            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            'params': {
                                'market': market_sel,
                                'lookback': lookback_sel,
                                'n_stocks': n_stocks_sel,
                                'buy_breakout': bt_brk,
                                'buy_ma20': bt_ma,
                                'buy_segment': bt_seg,
                                'exit_target': bt_tgt,
                                'exit_method': bt_met,
                                'stop_loss_pct': bt_sl,
                                'start_date': bt_start.strftime('%Y-%m-%d'),
                                'end_date': bt_end.strftime('%Y-%m-%d'),
                                'cooldown_days': bt_cooldown,
                                'bc_breakout_days': bc_breakout_days,
                                'max_holding_months': bt_max_months,
                                'defense_trailing_pct': bt_defense_ts,
                                'profit_trailing_pct': bt_profit_ts,
                                'bc_exit_days': bt_bc_exit_days,
                                'force_liquidate': bt_force_liquidate,
                                'inv_per_stock': bt_inv_amount
                            },
                            'metrics': {
                                'avg_cum_pnl': avg_cum_pnl,
                                'avg_win_rate': avg_win_rate,
                                'total_trades': total_trades,
                                'avg_profit': avg_profit,
                                'avg_loss': avg_loss,
                                'avg_mdd': avg_mdd,
                                'avg_annualized': avg_annualized,
                                'portfolio_total_ret': p_total_ret,
                                'portfolio_cagr': p_cagr,
                                'portfolio_mdd': p_mdd,
                                'initial_capital': initial_capital
                            }
                        }
                        history.append(current_record)
                        utils.save_history(history)
                        st.success(f"'{res_label}' 결과가 저장되었습니다.")
                        st.rerun()

        else:
            st.info("거래가 발생한 종목이 없어 요약 통계를 표시할 수 없습니다.")
            
        st.divider()
        
        # 상세 분석 UI 복구
        # 테이블 순서와 일치시키기 위해 정렬된 Ticker 리스트 활용
        # df_summary_display는 컬럼명이 변경되었을 수 있으므로 df_summary 기준 (또는 화면에 보이는 순서대로 매핑)
        
        # 1. 화면에 보이는 순서대로 데이터 정렬
        # df_summary는 정렬된 상태이며 'Ticker' 컬럼을 가지고 있음
        sorted_tickers = df_summary['Ticker'].tolist()
        bt_res_map = {r['Ticker']: r for r in bt_res} # Ticker가 Key
        
        rows_ordered = []
        bt_col_list = []
        
        for idx, ticker in enumerate(sorted_tickers):
            if ticker in bt_res_map:
                row_data = bt_res_map[ticker]
                rows_ordered.append(row_data)
                # 번호 붙여서 리스트 생성
                bt_col_list.append(f"{idx}. {row_data['Name']} ({ticker})")
        
        selected_bt_stock = st.selectbox("상세 분석 종목 선택 (백테스트 결과)", bt_col_list)
        
        if selected_bt_stock:
            # 선택된 문자열에서 인덱스 추출하거나, 리스트 인덱스로 접근
            sel_idx = bt_col_list.index(selected_bt_stock)
            bt_row = rows_ordered[sel_idx]
            
            st.markdown(f"### {selected_bt_stock} 상세 분석")
            
            # 요약 지표 (스크리너와 동일한 구성)
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("종목명", bt_row['Name'])
            c1.caption(f"Code: {bt_row['Ticker']}")
            
            # 백테스트 결과이므로 '최근 매수가' 기준
            buy_price = bt_row.get('Recent Buy Price', 0)
            c2.metric("매수가 (최근)", f"{int(buy_price):,}원")
            curr_price = bt_row.get('Recent Sell Price', 0) # 매도 안했으면 현재가
            c2.caption(f"현재가: {int(curr_price):,}원")
            
            pnl = bt_row.get('Current PnL (%)')
            pnl_str = f"{pnl:+.1f}%" if pnl is not None else "-"
            c3.metric("보유 수익률", pnl_str) # Renamed label
            
            # Caption logic for Max/Realized info
            caption_parts = []
            if 'Max 수익률' in bt_row and bt_row['Max 수익률'] is not None:
                caption_parts.append(f"Max: {bt_row['Max 수익률']:+.1f}%")
            
            realized_pnl = bt_row.get('Realized PnL (%)')
            if realized_pnl is not None:
                caption_parts.append(f"최근 실현: {realized_pnl:+.1f}%")
            
            if caption_parts:
                c3.caption(" | ".join(caption_parts))
            
            c4.metric("현재 상태", bt_row.get('Recent Sell', '-'))
            if 'Min 수익률' in bt_row and bt_row['Min 수익률'] is not None:
                c4.caption(f"Min: {bt_row['Min 수익률']:+.1f}% ({bt_row.get('Min 날짜', '-')})")

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
                
                if 'exit_reason' in df_trades.columns:
                    df_trades['사유'] = df_trades['exit_reason']
                else:
                    df_trades['사유'] = '-'
                
                disp_cols = ['매수일', '매수가', '매도일', '매도가', '수익률', 'Max 수익률', 'Min 수익률', 'duration', '사유']
                df_trades_disp = df_trades[disp_cols].rename(columns={'duration': '보유일'})
                st.dataframe(df_trades_disp, width='stretch')
            else:
                st.info("거래 내역이 없습니다.")
                
            # 2. 차트
            st.markdown("#### 매매 시점 차트")
            col_chart1, col_chart2 = st.columns([3, 1])
            with col_chart2:
                show_dynamic = st.checkbox("동적 경계선 보기", value=False, help="각 날짜별 실제 208주 최고/최저가를 기준으로 선을 그립니다. 과거 시점의 정확한 경계를 확인하실 수 있습니다.")
            df_chart = bt_row.get('df_daily')
            
            if df_chart is not None and not df_chart.empty:
                df_chart = df_chart.copy()
                # MA20 계산 (만약 없다면)
                if 'MA20' not in df_chart.columns:
                    df_chart['MA20'] = df_chart['Close'].rolling(window=20).mean()
                
                # 백테스트 시작 시점 기준으로 차트 범위 제한 (6개월 버퍼)
                chart_start_date = pd.Timestamp(bt_start) - pd.DateOffset(months=6)
                df_chart = df_chart[df_chart.index >= chart_start_date].copy()
                    
                fig = go.Figure()
                
                # Price & MA20
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['Close'], name='가격', line=dict(color='#2c3e50', width=2.5)))
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MA20'], name='20일선', line=dict(color='#e67e22', width=1.5, dash='dot')))
                
                # Segments
                if show_dynamic:
                    # 동적 경계선 (Rolling)
                    if 'RollHigh' in df_chart.columns and 'RollLow' in df_chart.columns:
                        r_high = df_chart['RollHigh']
                        r_low = df_chart['RollLow']
                        r_step = (r_high - r_low) / 6
                        
                        # 모든 경계선 그리기
                        boundary_names = ["A/B (1/6)", "B/C (2/6)", "C/D (3/6)", "D/E (4/6)", "E/F (5/6)"]
                        for j in range(1, 6):
                            line_val = r_low + j * r_step
                            name = boundary_names[j-1]
                            
                            # 색상 로직
                            is_target = False
                            if bt_tgt == "C/D Boundary" and j == 3: is_target = True
                            elif bt_tgt == "E/F Boundary" and j == 5: is_target = True
                            elif bt_tgt == "D/E Boundary" and j == 4: is_target = True
                            
                            is_entry = False
                            if bt_seg == "Segment C (B/C~C/D)" and j == 2: is_entry = True
                            elif bt_seg == "Segment B (A/B~B/C)" and j == 1: is_entry = True
                            
                            if is_target:
                                color = 'rgba(231,76,60,0.9)' # Red
                                width = 2.5
                                dash = 'dot'
                                label_suffix = "(Target/Sell)"
                            elif is_entry:
                                color = 'rgba(52,152,219,0.9)' # Blue
                                width = 2.5
                                dash = 'dot'
                                label_suffix = "(Entry/Buy)"
                            else:
                                color = 'rgba(150,150,150,0.3)'
                                width = 1
                                dash = 'dash'
                                label_suffix = ""
                            
                            fig.add_trace(go.Scatter(
                                x=df_chart.index, y=line_val, 
                                name=f"{name} {label_suffix}".strip(),
                                line=dict(color=color, width=width, dash=dash),
                                hoverinfo='skip'
                            ))
                        
                        fig.add_trace(go.Scatter(x=df_chart.index, y=r_high, name='208주 최고', line=dict(color='rgba(100,100,100,0.5)', width=1, dash='solid')))
                        fig.add_trace(go.Scatter(x=df_chart.index, y=r_low, name='208주 최저', line=dict(color='rgba(100,100,100,0.5)', width=1, dash='solid')))
                else:
                    # 고정 경계선 (마지막 기준 - 기존 로직)
                    if trades:
                        last_segments = trades[-1].get('segments')
                        if last_segments:
                            for idx, level in enumerate(last_segments):
                                name = ["최저", "A/B", "B/C", "C/D", "D/E", "E/F", "최고"][idx]
                                
                                # 색상 결정
                                is_target = (bt_tgt == "C/D Boundary" and idx == 3) or \
                                            (bt_tgt == "E/F Boundary" and idx == 5) or \
                                            (bt_tgt == "D/E Boundary" and idx == 4)
                                is_entry = (bt_seg == "Segment C (B/C~C/D)" and idx == 2) or \
                                           (bt_seg == "Segment B (A/B~B/C)" and idx == 1)
                                
                                if is_target:
                                    color, width, dash = 'rgba(231,76,60,0.9)', 2, "dot"
                                elif is_entry:
                                    color, width, dash = 'rgba(52,152,219,0.9)', 2, "dot"
                                else:
                                    color, width, dash = 'rgba(150,150,150,0.5)', 1, "dash"
                                    
                                fig.add_hline(
                                    y=level, line_dash=dash, line_color=color, line_width=width,
                                    annotation_text=name if idx in [0, 6] else "",
                                    annotation_position="bottom right"
                                )
                
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
                st.plotly_chart(fig, width='stretch')
            else:
                st.warning("차트 데이터가 없습니다.")

with tab3:
    st.subheader("🔍 종목별 상세 분석")
    st.markdown("스크리너에 포착되지 않았더라도, 관심 있는 종목의 208주 역발상 상태를 직접 분석합니다.")
    
    search_col1, search_col2 = st.columns([3, 1])
    with search_col1:
        search_name = st.text_input("분석할 종목명 또는 코드를 입력하세요", placeholder="예: 삼성전자, 005930")
    
    if search_name:
        with st.spinner(f"'{search_name}' 분석 데이터 로드 중..."):
            # 1. 종목 코드 찾기
            # 현재 선택된 시장에서 먼저 찾기
            stock_list = get_stock_list_naver(market_sel, 2000) 
            target_row = None
            
            def find_in_df(df, query):
                # 이름 매칭
                m = df[df['Name'] == query]
                if not m.empty: return m.iloc[0]
                # 코드 매칭
                if query.isdigit() and len(query) == 6:
                    m = df[df['Code'] == query]
                    if not m.empty: return m.iloc[0]
                return None

            target_row = find_in_df(stock_list, search_name)
            
            # 만약 못 찾았으면 다른 시장에서도 검색
            if target_row is None:
                other_market = "KOSDAQ" if market_sel == "KOSPI" else "KOSPI"
                other_stock_list = get_stock_list_naver(other_market, 2000)
                target_row = find_in_df(other_stock_list, search_name)
                if target_row is not None:
                    # 시장이 변경되었음을 알리는 메시지 (선택 사항)
                    # st.caption(f"ℹ️ {other_market} 시장에서 종목을 찾았습니다.")
                    actual_market = other_market
                else:
                    actual_market = market_sel
            else:
                actual_market = market_sel

            if target_row is not None:
                ticker = target_row['Code']
                name = target_row['Name']
                
                # 2. 데이터 페칭
                fetch_start_date = (datetime.now() - pd.Timedelta(weeks=int(lookback_sel * 1.5))).strftime('%Y-%m-%d')
                result = fetch_data(ticker, actual_market, start_date=fetch_start_date)
                
                if result and result[0] is not None:
                    df = result[0]
                    # 3. 분석
                    res = analyze_stock_core(ticker, name, df, lookback_sel, bc_breakout_days, ignore_conditions=True)
                    
                    if res:
                        # 요약 지표 표시
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("종목명", name)
                        m1.caption(f"코드: {ticker}")
                        
                        curr_p = float(df['Close'].iloc[-1])
                        m2.metric("현재가", f"{int(curr_p):,}원")
                        
                        bc_line = res['B/C 라인']
                        dist_bc = ((curr_p / bc_line) - 1) * 100
                        m3.metric("B/C 라인 대비", f"{dist_bc:+.1f}%")
                        m3.caption(f"라인가: {int(bc_line):,}원")
                        
                        m4.metric("현재 구간", res['현재 구간'])
                        
                        # 차트 그리기
                        st.markdown("#### 208주 역발상 차트")
                        df_chart = df.copy()
                        df_chart['MA20'] = df_chart['Close'].rolling(window=20).mean()
                        
                        fig = go.Figure()
                        # 가격
                        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['Close'], name='가격', line=dict(color='#2c3e50', width=2)))
                        # 20일선
                        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MA20'], name='20일선', line=dict(color='#e67e22', width=1, dash='dot')))
                        
                        # 경계선
                        colors = ['#f1f3f5', '#d0ebff', '#a5d8ff', '#ffd8a8', '#ffc078', '#ff922b']
                        labels = ['A/B (1/6)', 'B/C (2/6)', 'C/D (3/6)', 'D/E (4/6)', 'E/F (5/6)', '208주 최고']
                        for i, level in enumerate(res['segments']):
                            fig.add_hline(y=level, line_dash="dash", line_color="rgba(150,150,150,0.3)", annotation_text=labels[i] if i < len(labels) else "")

                        fig.update_layout(
                            template="plotly_white", height=600, hovermode='x unified',
                            margin=dict(l=20, r=20, t=30, b=20),
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                        )
                        st.plotly_chart(fig, width='stretch')
                        
                        # 상세 데이터 테이블
                        with st.expander("분석 데이터 상세 보기"):
                            st.write(res)
                    else:
                        st.error("종목 분석 중 오류가 발생했습니다.")
                else:
                    st.error("가격을 가져올 수 없습니다. 코드나 시장 설정을 확인해 주세요.")
            else:
                st.warning(f"'{search_name}' 종목을 찾을 수 없습니다. 정확한 명칭이나 코드를 입력해 주세요.")

with tab4:
    stockeasy_view.render_main()

# --- 설정 자동 저장 (맨 마지막에 배치하여 모든 위젯 값 수집) ---
all_current_settings = {
    'market': market_sel,
    'lookback': lookback_sel,
    'n_stocks': n_stocks_sel,
    'bc_breakout_days': bc_breakout_days,
    'max_holding_months': bt_max_months,
    'defense_trailing_pct': bt_defense_ts,
    'profit_trailing_pct': bt_profit_ts,
    'bc_exit_days': bt_bc_exit_days,
    'exit_target': bt_tgt,
    'exit_method': bt_met,
    'stop_loss_pct': bt_sl,
    'bt_start_date': bt_start.strftime('%Y-%m-%d'),
    'bt_end_date': bt_end.strftime('%Y-%m-%d'),
    'cooldown_days': bt_cooldown,
    'inv_per_stock': bt_inv_amount
}

if 'last_settings' not in st.session_state:
    st.session_state['last_settings'] = saved_settings

if all_current_settings != st.session_state['last_settings']:
    utils.save_settings(all_current_settings)
    st.session_state['last_settings'] = all_current_settings
    st.toast("설정이 저장되었습니다.")
