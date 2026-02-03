"""
StockEasy 종목 분석 도구 - Streamlit View Module

208Week 통합용 UI 뷰 모듈
"""

import streamlit as st
import pandas as pd
from pathlib import Path
import logging
import json
import os
import requests
from io import BytesIO

# Relative imports for package usage
from .stockeasy_scraper import collect_stocks, get_top_stocks_from_208week
from .analyzer import StockAnalyzer, get_recommended_stocks
from .db_manager import get_db
from .ui import (
    render_filter_sidebar,
    render_stock_table,
    render_statistics,
    render_charts,
    render_export_section
)
from . import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 세션 상태 초기화 함수
def init_session_state():
    if "stock_data" not in st.session_state:
        st.session_state.stock_data = None
    if "analyzer" not in st.session_state:
        st.session_state.analyzer = None
    if "collection_method" not in st.session_state:
        st.session_state.collection_method = "selenium"

@st.cache_data
def get_stock_listing():
    """KRX 상장법인 목록을 가져와서 (종목명, 종목코드) 딕셔너리 반환"""
    try:
        url = 'http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        try:
            res = requests.get(url, headers=headers, timeout=5)
            res.raise_for_status()
            df = pd.read_html(BytesIO(res.content), header=0)[0]
        except Exception as e:
            logger.warning(f"1차 KRX 다운로드 실패: {e}")
            return {}

        df['종목코드'] = df['종목코드'].astype(str).str.zfill(6)
        name_to_code = dict(zip(df['회사명'], df['종목코드']))
        
        if len(name_to_code) < 100:
            logger.warning("가져온 종목 수가 너무 적습니다.")
            return {}
            
        return name_to_code
        
    except Exception as e:
        logger.error(f"상장법인 목록 가져오기 최종 실패: {e}")
        return {}

def _save_last_stocks(stock_codes: list):
    """마지막 사용 종목 리스트 저장"""
    # config.DATA_DIR가 아니라 BASE_DIR/last_stocks.json 등을 사용하거나
    # 프로젝트 루트의 last_stocks.json을 사용하는 것이 좋음.
    # 여기서는 프로젝트 루트(실행 위치)에 저장
    cache_file = "last_stocks.json"
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump({"stocks": stock_codes, "count": len(stock_codes)}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"종목 리스트 저장 실패: {e}")

def _load_last_stocks() -> list:
    """마지막 사용 종목 리스트 로드"""
    cache_file = "last_stocks.json"
    if not os.path.exists(cache_file):
        return []
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("stocks", [])
    except Exception as e:
        logger.error(f"종목 리스트 로드 실패: {e}")
        return []

def render_collection_tab(method: str, api_token: str):
    """데이터 수집 탭"""
    st.header("데이터 수집")
    
    last_stocks = _load_last_stocks()
    if last_stocks:
        st.success(f"💾 저장된 종목 리스트: {len(last_stocks)}개")
        if st.button("🔄 이전 종목 리스트 재사용", type="primary", key="btn_reuse_stocks"):
            st.session_state.stock_codes_to_collect = last_stocks
            st.rerun()
    
    st.divider()
    
    stock_codes = []
    if 'stock_codes_to_collect' in st.session_state and st.session_state.stock_codes_to_collect:
        stock_codes = st.session_state.stock_codes_to_collect
        
        col1, col2 = st.columns([3, 1])
        with col1:
            st.info(f"📂 저장된 종목을 불러왔습니다 ({len(stock_codes)}개)")
        with col2:
            if st.button("❌ 취소", help="다시 직접 입력하려면 클릭하세요", key="btn_cancel_reuse"):
                st.session_state.stock_codes_to_collect = None
                st.rerun()
    else:
        input_method = st.radio(
            "종목 입력 방법",
            options=["직접 입력", "CSV 파일 업로드"],
            horizontal=True,
            key="input_method_radio"
        )
        
        if input_method == "직접 입력":
            codes_input = st.text_area(
                "종목 코드 입력 (한 줄에 하나씩)",
                placeholder="035900\n005930\n000660",
                height=150
            )
            if codes_input:
                stock_codes = [code.strip() for code in codes_input.strip().split('\n') if code.strip()]
                
        else:  # CSV 파일 업로드
            uploaded_file = st.file_uploader(
                "CSV 파일 선택",
                type=["csv"],
                help="종목 코드가 포함된 CSV 파일"
            )
            
            if uploaded_file:
                try:
                    df = pd.read_csv(uploaded_file)
                    st.write(f"파일 미리보기 (총 {len(df)}개 종목):")
                    st.dataframe(df, width='stretch', height=400)
                    
                    name_to_code_map = get_stock_listing()
                    
                    default_idx = 0
                    for i, col in enumerate(df.columns):
                        if "code" in col.lower() or "코드" in col:
                            default_idx = i
                            break
                        elif "name" in col.lower() or "종목" in col or "회사" in col:
                            default_idx = i
                    
                    code_column = st.selectbox(
                        "종목 코드(또는 종목명) 컬럼 선택",
                        options=df.columns.tolist(),
                        index=default_idx
                    )
                    
                    if code_column:
                        raw_codes = df[code_column].astype(str).str.strip().tolist()
                        valid_codes = []
                        converted_count = 0
                        
                        for code in raw_codes:
                            if code.isdigit():
                                valid_codes.append(code.zfill(6))
                            else:
                                if code in name_to_code_map:
                                    valid_codes.append(name_to_code_map[code])
                                    converted_count += 1
                                elif code.strip() in name_to_code_map:
                                    valid_codes.append(name_to_code_map[code.strip()])
                                    converted_count += 1
                                elif code.replace("(주)", "").strip() in name_to_code_map:
                                     valid_codes.append(name_to_code_map[code.replace("(주)", "").strip()])
                                     converted_count += 1
                                else:
                                    valid_codes.append(code)
                                    
                        stock_codes = valid_codes
                        if converted_count > 0:
                            st.success(f"📌 {converted_count}개 종목명을 코드로 자동 변환했습니다!")
                except Exception as e:
                    st.error(f"파일 읽기 오류: {e}")
    
    if stock_codes:
        is_suspicious = any(any('\u3131' <= char <= '\u3163' or '\uac00' <= char <= '\ud7a3' for char in code) for code in stock_codes)
        if is_suspicious:
            st.error("⚠️ 종목 코드에 한글이 포함되어 있습니다.")
            if not st.button("🚨 그래도 진행하기"):
                stock_codes = []

    if stock_codes:
        st.info(f"총 {len(stock_codes)}개 종목이 입력되었습니다.")  
        _save_last_stocks(stock_codes)
        
        use_cache = st.checkbox("캐시 사용", value=True, help="체크 해제하면 데이터를 새로 수집합니다", key="chk_use_cache")
        
        if st.button("🚀 데이터 수집 시작", type="primary", key="btn_start_collect"):
            if not use_cache and os.path.exists("stockeasy_cache.json"):
                try:
                    os.remove("stockeasy_cache.json")
                except: pass

            with st.spinner("데이터 수집 중..."):
                try:
                    progress_bar = st.progress(0)
                    stock_data = collect_stocks(
                        stock_codes=stock_codes,
                        method=method,
                        token=api_token if method == "api" else None,
                        use_cache=use_cache
                    )
                    progress_bar.progress(100)
                    
                    st.session_state.stock_data = stock_data
                    st.session_state.analyzer = StockAnalyzer(stock_data)
                    st.success(f"✅ 수집 완료! {len(stock_data)}/{len(stock_codes)}개 종목 성공")
                    
                    failed = set(stock_codes) - set(stock_data.keys())
                    if failed:
                        with st.expander(f"⚠️ 수집 실패 종목 ({len(failed)}개)"):
                            st.write(list(failed))
                except Exception as e:
                    st.error(f"데이터 수집 중 오류: {e}")
                    if "로그인" in str(e) or (stock_data and len(stock_data) == 0):
                         st.warning("⚠️ StockEasy 로그인이 필요할 수 있습니다. login_helper.py를 실행하세요.")
    else:
        st.info("👆 종목 코드를 입력하세요.")

def render_analysis_tab():
    """종목 분석 탭"""
    if st.session_state.analyzer is None:
        st.info("먼저 '📥 데이터 수집' 탭에서 종목 데이터를 수집하세요.")
        return
    
    analyzer = st.session_state.analyzer
    all_df = analyzer._create_dataframe()
    
    if all_df.empty:
        st.error("❌ 수집된 종목 데이터가 없습니다.")
        return
    
    if "composite_score" not in all_df.columns:
        st.error("❌ 종합 점수를 계산할 수 없습니다.")
        return
    
    st.subheader("📋 수집된 종목 데이터")
    st.info(f"총 {len(all_df)}개 종목의 데이터가 수집되었습니다.")
    
    use_filter = st.checkbox("🔍 필터 적용", value=False, key="chk_use_filter")
    
    if use_filter:
        filters = render_filter_sidebar(analyzer)
        filtered_df = analyzer.filter_stocks(filters)
        render_statistics(analyzer, filtered_df)
        
        st.divider()
        
        col1, col2 = st.columns([3, 1])
        with col1: st.subheader("📋 필터링 결과")
        with col2:
            sort_by = st.selectbox("정렬 기준", ["종합점수", "재무점수", "RS"], index=0, key="sb_sort_filter")
        
        sort_map = {"종합점수": "composite_score", "재무점수": "financial_score", "RS": "rs_value"}
        if sort_map[sort_by] in filtered_df.columns:
            sorted_df = filtered_df.sort_values(by=sort_map[sort_by], ascending=False).reset_index(drop=True)
            render_stock_table(sorted_df)
            render_charts(filtered_df)
            render_export_section(analyzer, filtered_df)
    else:
        st.divider()
        col1, col2 = st.columns([3, 1])
        with col1: st.subheader("📊 전체 종목 데이터")
        with col2:
            sort_by = st.selectbox("정렬 기준", ["종합점수", "재무점수", "RS", "종목코드"], index=0, key="sb_sort_all")
        
        sort_map = {"종합점수": "composite_score", "재무점수": "financial_score", "RS": "rs_value", "종목코드": "code"}
        if sort_map[sort_by] in all_df.columns:
            sorted_df = all_df.sort_values(by=sort_map[sort_by], ascending=(sort_by=="종목코드")).reset_index(drop=True)
            render_stock_table(sorted_df)
            render_charts(sorted_df)
            render_export_section(analyzer, sorted_df)

    st.divider()
    st.subheader("⭐ 전략별 추천 종목 TOP 10")
    c1, c2, c3 = st.columns(3)
    
    strategies = {"conservative": "보수적", "balanced": "균형", "aggressive": "공격적"}
    cols = [c1, c2, c3]
    
    for (strat, name), col in zip(strategies.items(), cols):
        with col:
            st.markdown(f"**{name} 전략**")
            recs = get_recommended_stocks(st.session_state.stock_data, strategy=strat, top_n=10)
            if not recs.empty:
                st.dataframe(recs[["code", "name", "composite_score"]].rename(columns={"code":"코드","name":"종목명","composite_score":"점수"}), hide_index=True)
            else:
                st.info("없음")

def render_db_management_tab():
    """DB 관리 탭"""
    from .stockeasy_scraper import StockDataCollector
    st.header("📦 데이터베이스 관리")
    st.markdown("208Weeks 백테스터와 매칭되는 시가총액 상위 종목의 StockEasy 데이터를 관리합니다.")
    
    db = get_db()
    
    try:
        stats = db.get_db_stats()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("전체 종목 수", f"{stats['total_stocks']:,}개")
        c2.metric("스냅샷 수", f"{stats['total_snapshots']}개")
        c3.metric("최신 스냅샷", stats['latest_date'] or "-")
        c4.metric("최신 스냅샷 종목", f"{stats['latest_count']:,}개")
    except Exception as e:
        st.error(f"DB 상태 조회 실패: {e}")
    
    st.divider()
    st.subheader("🔄 208Week 상위 종목 데이터 수집")
    
    c1, c2, c3 = st.columns(3)
    with c1: db_market = st.selectbox("시장 선택", ["KOSPI", "KOSDAQ"], key="db_market")
    with c2: db_n_stocks = st.number_input("수집 종목 수", 10, 500, 200, 10, key="db_n_stocks")
    with c3: db_use_cache = st.checkbox("캐시 사용", value=True, key="db_cache")
    
    if st.button("🚀 상위 종목 데이터 수집 시작", type="primary", key="btn_db_collect"):
        with st.spinner(f"{db_market} 시가총액 상위 {db_n_stocks}개 종목 리스트 가져오는 중..."):
            stock_list_df = get_top_stocks_from_208week(db_market, db_n_stocks)
        
        if stock_list_df is None or stock_list_df.empty:
            st.error("종목 리스트 실패")
        else:
            st.success(f"✅ {len(stock_list_df)}개 종목 리스트 확보")
            stock_codes = stock_list_df['Code'].tolist()
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            collector = StockDataCollector(method="selenium")
            collected_data = {}
            
            for i, code in enumerate(stock_codes, 1):
                status_text.text(f"수집 중... ({i}/{len(stock_codes)}) - {code}")
                try:
                    data = collector.collect_stock_data(code, use_cache=db_use_cache)
                    if data: collected_data[code] = data
                except Exception as e:
                    logging.warning(f"[{code}] 실패: {e}")
                progress_bar.progress(i / len(stock_codes))
            
            status_text.empty()
            if collected_data:
                saved_count = db.save_snapshot(collected_data)
                st.success(f"✅ 저장 완료: {saved_count}개")
            else:
                st.error("수집된 데이터 없음")

    st.divider()
    st.subheader("🔍 저장된 데이터 조회")
    
    view_option = st.radio("조회 방식", ["최신 데이터", "특정 스냅샷"], horizontal=True, key="db_view_opt")
    
    if view_option == "최신 데이터":
        df = db.get_latest_data()
        if not df.empty:
            st.info(f"총 {len(df)}개 최신 데이터")
            st.dataframe(df)
        else:
            st.info("데이터 없음")
    else:
        snapshots = db.get_snapshots_list()
        if snapshots:
            opts = [f"{s['date']} ({s['count']}개)" for s in snapshots]
            sel = st.selectbox("스냅샷 선택", opts, key="sb_snapshot_sel")
            if sel:
                date = sel.split(' ')[0]
                df = db.get_snapshot_by_date(date)
                st.dataframe(df)
        else:
            st.info("저장된 스냅샷 없음")
    
    st.divider()
    with st.expander("🗑️ 데이터 정리"):
        days = st.number_input("보관 기간(일)", 1, 365, 30, key="db_cleanup_days")
        if st.button("오래된 데이터 삭제", key="btn_db_cleanup"):
            count = db.cleanup_old_snapshots(days)
            st.success(f"{count}개 행 삭제 완료")
            st.rerun()

def render_guide_tab():
    st.header("사용 가이드")
    st.markdown("StockEasy 통합 분석 도구입니다. 208Week 백테스트 종목 필터링에 활용하세요.")
    # (내용 생략 for brevity, or keep simple)

def render_main():
    """메인 진입점"""
    init_session_state()
    
    st.title("📊 StockEasy 종목 분석 도구")
    st.markdown("백테스트 결과 종목에 대한 재무지표, 투자지표 분석")
    
    with st.sidebar:
        st.header("⚙️ StockEasy 설정")
        method = st.radio("수집 방법", ["selenium", "api"], index=0, key="se_method")
        st.session_state.collection_method = method
        
        api_token = None
        if method == "api":
            api_token = st.text_input("API Token", type="password", key="se_token")
        
        st.divider()
    
    t1, t2, t3, t4 = st.tabs(["📥 데이터 수집", "🔍 종목 분석", "📦 DB 관리", "📖 가이드"])
    
    with t1: render_collection_tab(method, api_token)
    with t2: render_analysis_tab()
    with t3: render_db_management_tab()
    with t4: render_guide_tab()
