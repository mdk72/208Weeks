"""
Streamlit UI 컴포넌트 모듈
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from typing import Dict, Optional, List

from . import config
from .analyzer import StockAnalyzer


def render_filter_sidebar(analyzer: StockAnalyzer) -> Dict:
    """
    사이드바에 필터 UI를 렌더링합니다.
    
    Args:
        analyzer: StockAnalyzer 인스턴스
        
    Returns:
        필터 딕셔너리
    """
    st.sidebar.header("🔍 필터 설정")
    
    filters = {}
    
    # 재무 건전성 점수
    st.sidebar.subheader("재무 건전성")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        filters["financial_score_min"] = st.number_input(
            "최소 점수",
            min_value=0,
            max_value=100,
            value=config.DEFAULT_FILTERS["financial_score_min"],
            step=5
        )
    with col2:
        filters["financial_score_max"] = st.number_input(
            "최대 점수",
            min_value=0,
            max_value=100,
            value=100,
            step=5
        )
    
    # RS값
    st.sidebar.subheader("RS (Relative Strength)")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        filters["rs_value_min"] = st.number_input(
            "최소 RS",
            min_value=0.0,
            max_value=100.0,
            value=float(config.DEFAULT_FILTERS["rs_value_min"]),
            step=5.0
        )
    with col2:
        filters["rs_value_max"] = st.number_input(
            "최대 RS",
            min_value=0.0,
            max_value=100.0,
            value=100.0,
            step=5.0
        )
    
    # 투자지표 등급
    st.sidebar.subheader("투자지표 등급")
    
    grade_options = ["A", "B", "C", "D", "E", "F"]
    
    filters["growth_grade"] = st.sidebar.multiselect(
        "성장성",
        options=grade_options,
        default=config.DEFAULT_FILTERS["growth_grade"]
    )
    
    filters["profitability_grade"] = st.sidebar.multiselect(
        "수익성",
        options=grade_options,
        default=config.DEFAULT_FILTERS["profitability_grade"]
    )
    
    filters["stability_grade"] = st.sidebar.multiselect(
        "안정성",
        options=grade_options,
        default=config.DEFAULT_FILTERS["stability_grade"]
    )
    
    filters["valuation_grade"] = st.sidebar.multiselect(
        "밸류에이션",
        options=grade_options,
        default=config.DEFAULT_FILTERS["valuation_grade"]
    )
    
    # 종합 점수
    st.sidebar.subheader("종합 점수")
    filters["composite_score_min"] = st.sidebar.slider(
        "최소 종합 점수",
        min_value=0,
        max_value=100,
        value=0,
        step=5
    )
    
    # 프리셋 버튼
    st.sidebar.subheader("전략 프리셋")
    col1, col2, col3 = st.sidebar.columns(3)
    
    if col1.button("보수적"):
        return apply_preset("conservative")
    if col2.button("균형"):
        return apply_preset("balanced")
    if col3.button("공격적"):
        return apply_preset("aggressive")
    
    return filters


def apply_preset(strategy: str) -> Dict:
    """전략 프리셋 적용"""
    presets = {
        "conservative": {
            "financial_score_min": 85,
            "financial_score_max": 100,
            "rs_value_min": 75.0,
            "rs_value_max": 100.0,
            "growth_grade": ["A", "B"],
            "profitability_grade": ["A", "B"],
            "stability_grade": ["A"],
            "valuation_grade": ["A", "B", "C"],
            "composite_score_min": 80
        },
        "balanced": {
            "financial_score_min": 70,
            "financial_score_max": 100,
            "rs_value_min": 65.0,
            "rs_value_max": 100.0,
            "growth_grade": ["A", "B", "C"],
            "profitability_grade": ["A", "B"],
            "stability_grade": ["A", "B"],
            "valuation_grade": ["A", "B", "C"],
            "composite_score_min": 60
        },
        "aggressive": {
            "financial_score_min": 60,
            "financial_score_max": 100,
            "rs_value_min": 70.0,
            "rs_value_max": 100.0,
            "growth_grade": ["A", "B"],
            "profitability_grade": ["A", "B", "C"],
            "stability_grade": ["A", "B", "C"],
            "valuation_grade": ["A", "B", "C", "D"],
            "composite_score_min": 50
        }
    }
    
    st.info(f"{strategy.capitalize()} 전략을 적용했습니다. 필터를 조정하려면 다시 설정하세요.")
    return presets.get(strategy, presets["balanced"])


def render_stock_table(df: pd.DataFrame, show_link: bool = True):
    """
    종목 테이블을 렌더링합니다.
    
    Args:
        df: DataFrame
        show_link: StockEasy 링크 표시 여부
    """
    if df.empty:
        st.warning("필터 조건에 맞는 종목이 없습니다.")
        return
    
    # 표시할 컬럼 선택 및 순서 정렬
    display_df = df[[
        "code", "name", "composite_score", 
        "financial_score", "financial_grade",
        "growth_grade", "profitability_grade", 
        "stability_grade", "valuation_grade",
        "rs_value"
    ]].copy()
    
    # 컬럼명 한글화
    display_df.columns = [
        "종목코드", "종목명", "종합점수",
        "재무점수", "재무등급",
        "성장성", "수익성", "안정성", "밸류", "RS"
    ]
    
    # 숫자 포맷팅
    display_df["종합점수"] = pd.to_numeric(display_df["종합점수"], errors='coerce').fillna(0).round(1)
    display_df["재무점수"] = pd.to_numeric(display_df["재무점수"], errors='coerce').fillna(0).astype(int)
    display_df["RS"] = pd.to_numeric(display_df["RS"], errors='coerce').fillna(0).round(1)
    
    # StockEasy 링크 추가
    if show_link:
        display_df["링크"] = display_df["종목코드"].apply(
            lambda code: f"[StockEasy]({config.STOCKEASY_STOCK_INFO_URL}/{code})"
        )
    
    st.dataframe(
        display_df,
        width='stretch',
        hide_index=True
    )


def render_statistics(analyzer: StockAnalyzer, filtered_df: pd.DataFrame):
    """
    통계 정보를 렌더링합니다.
    
    Args:
        analyzer: StockAnalyzer 인스턴스
        filtered_df: 필터링된 DataFrame
    """
    st.subheader("📊 통계")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "총 종목 수",
            len(analyzer.df),
            delta=f"필터: {len(filtered_df)}"
        )
    
    with col2:
        avg_score = filtered_df["composite_score"].mean() if not filtered_df.empty else 0
        st.metric("평균 종합점수", f"{avg_score:.1f}")
    
    with col3:
        avg_financial = filtered_df["financial_score"].mean() if not filtered_df.empty else 0
        st.metric("평균 재무점수", f"{avg_financial:.1f}")
    
    with col4:
        avg_rs = filtered_df["rs_value"].mean() if not filtered_df.empty else 0
        st.metric("평균 RS", f"{avg_rs:.1f}")


def render_charts(df: pd.DataFrame):
    """
    차트를 렌더링합니다.
    
    Args:
        df: DataFrame
    """
    if df.empty:
        return
    
    st.subheader("📈 시각화")
    
    tab1, tab2, tab3 = st.tabs(["점수 분포", "등급 분포", "상관관계"])
    
    with tab1:
        # 재무 점수 vs RS값 산점도
        fig = px.scatter(
            df,
            x="financial_score",
            y="rs_value",
            size="composite_score",
            color="composite_score",
            hover_data=["code", "name"],
            labels={
                "financial_score": "재무 건전성 점수",
                "rs_value": "RS값",
                "composite_score": "종합점수"
            },
            title="재무 건전성 vs RS값"
        )
        st.plotly_chart(fig, width='stretch')
    
    with tab2:
        # 투자지표 등급 분포
        col1, col2 = st.columns(2)
        
        with col1:
            # 성장성
            growth_counts = df["growth_grade"].value_counts().reindex(
                ["A", "B", "C", "D", "E", "F"], fill_value=0
            )
            fig1 = px.bar(
                x=growth_counts.index,
                y=growth_counts.values,
                labels={"x": "등급", "y": "종목 수"},
                title="성장성 등급 분포"
            )
            st.plotly_chart(fig1, width='stretch')
            
            # 안정성
            stability_counts = df["stability_grade"].value_counts().reindex(
                ["A", "B", "C", "D", "E", "F"], fill_value=0
            )
            fig3 = px.bar(
                x=stability_counts.index,
                y=stability_counts.values,
                labels={"x": "등급", "y": "종목 수"},
                title="안정성 등급 분포"
            )
            st.plotly_chart(fig3, width='stretch')
        
        with col2:
            # 수익성
            profit_counts = df["profitability_grade"].value_counts().reindex(
                ["A", "B", "C", "D", "E", "F"], fill_value=0
            )
            fig2 = px.bar(
                x=profit_counts.index,
                y=profit_counts.values,
                labels={"x": "등급", "y": "종목 수"},
                title="수익성 등급 분포"
            )
            st.plotly_chart(fig2, width='stretch')
            
            # 밸류에이션
            value_counts = df["valuation_grade"].value_counts().reindex(
                ["A", "B", "C", "D", "E", "F"], fill_value=0
            )
            fig4 = px.bar(
                x=value_counts.index,
                y=value_counts.values,
                labels={"x": "등급", "y": "종목 수"},
                title="밸류에이션 등급 분포"
            )
            st.plotly_chart(fig4, width='stretch')
    
    with tab3:
        # 상관관계 히트맵
        numeric_cols = ["financial_score", "rs_value", "composite_score"]
        corr = df[numeric_cols].corr()
        
        fig = px.imshow(
            corr,
            labels=dict(color="상관계수"),
            x=["재무점수", "RS값", "종합점수"],
            y=["재무점수", "RS값", "종합점수"],
            title="지표 간 상관관계",
            color_continuous_scale="RdBu",
            zmin=-1,
            zmax=1
        )
        st.plotly_chart(fig, width='stretch')


def render_collection_progress(total: int, current: int, stock_code: str):
    """
    데이터 수집 진행 상황을 표시합니다.
    
    Args:
        total: 전체 종목 수
        current: 현재 진행 수
        stock_code: 현재 처리 중인 종목 코드
    """
    progress = current / total if total > 0 else 0
    st.progress(progress, text=f"진행: {current}/{total} - {stock_code}")


def render_export_section(analyzer: StockAnalyzer, filtered_df: pd.DataFrame):
    """
    결과 내보내기 섹션을 렌더링합니다.
    
    Args:
        analyzer: StockAnalyzer 인스턴스
        filtered_df: 필터링된 DataFrame
    """
    st.subheader("💾 결과 내보내기")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # CSV 다운로드
        if not filtered_df.empty:
            csv = filtered_df.to_csv(index=False, encoding='utf-8-sig')
            st.download_button(
                "📥 CSV 다운로드",
                data=csv,
                file_name=f"filtered_stocks_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
    
    with col2:
        # 종목 코드만 추출
        if not filtered_df.empty:
            codes = "\n".join(filtered_df["code"].tolist())
            st.download_button(
                "📋 종목 코드만 다운로드",
                data=codes,
                file_name=f"stock_codes_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.txt",
                mime="text/plain"
            )
