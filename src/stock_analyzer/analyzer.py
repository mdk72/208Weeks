"""
수집된 데이터 필터링 및 분석 모듈
"""

import logging
from typing import Dict, List, Optional, Callable
import pandas as pd

from . import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StockAnalyzer:
    """종목 데이터 필터링 및 분석 클래스"""
    
    def __init__(self, stock_data: Dict[str, Dict]):
        """
        Args:
            stock_data: 종목 코드를 키로 하는 데이터 딕셔너리
        """
        self.stock_data = stock_data
        self.df = self._create_dataframe()
        
    def _create_dataframe(self) -> pd.DataFrame:
        """데이터를 DataFrame으로 변환"""
        rows = []
        
        for code, data in self.stock_data.items():
            if not data:
                continue
                
            financial = data.get("financial_health", {})
            indicators = data.get("indicators", {})
            
            row = {
                "code": code,
                "name": data.get("name", "Unknown"),
                "financial_score": financial.get("score"),
                "financial_grade": financial.get("grade"),
                "financial_percentile": financial.get("percentile"),
                "growth_grade": indicators.get("growth"),
                "profitability_grade": indicators.get("profitability"),
                "stability_grade": indicators.get("stability"),
                "valuation_grade": indicators.get("valuation"),
                "rs_value": data.get("rs_value"),
                "collected_at": data.get("collected_at")
            }
            
            # 종합 점수 계산
            row["composite_score"] = self._calculate_composite_score(row)
            
            rows.append(row)
            
        return pd.DataFrame(rows)
        
    def _calculate_composite_score(self, row: Dict) -> float:
        """
        종합 점수를 계산합니다.
        
        Args:
            row: 종목 데이터
            
        Returns:
            종합 점수 (0-100)
        """
        score = 0
        count = 0
        
        # 재무 건전성 점수 (40% 가중치)
        if row["financial_score"] is not None:
            score += row["financial_score"] * 0.4
            count += 0.4
            
        # 투자지표 등급 점수 (40% 가중치, 각 10%)
        for indicator in ["growth_grade", "profitability_grade", "stability_grade", "valuation_grade"]:
            grade = row.get(indicator)
            if grade and grade in config.GRADE_SCORES:
                grade_score = config.GRADE_SCORES[grade] * 20  # 5점 만점 -> 100점 만점 변환
                score += grade_score * 0.1
                count += 0.1
                
        # RS값 (20% 가중치)
        if row["rs_value"] is not None:
            score += row["rs_value"] * 0.2
            count += 0.2
            
        # 평균 계산
        if count > 0:
            return score / count
        return 0
        
    def filter_stocks(self, filters: Dict) -> pd.DataFrame:
        """
        필터 조건에 맞는 종목을 반환합니다.
        
        Args:
            filters: 필터 딕셔너리
                - financial_score_min: 최소 재무 건전성 점수
                - financial_score_max: 최대 재무 건전성 점수
                - growth_grade: 성장성 등급 리스트
                - profitability_grade: 수익성 등급 리스트
                - stability_grade: 안정성 등급 리스트
                - valuation_grade: 밸류에이션 등급 리스트
                - rs_value_min: 최소 RS값
                - rs_value_max: 최대 RS값
                - composite_score_min: 최소 종합 점수
                
        Returns:
            필터링된 DataFrame
        """
        df = self.df.copy()
        
        # 재무 건전성 점수 필터
        if "financial_score_min" in filters and filters["financial_score_min"] is not None:
            df = df[df["financial_score"] >= filters["financial_score_min"]]
            
        if "financial_score_max" in filters and filters["financial_score_max"] is not None:
            df = df[df["financial_score"] <= filters["financial_score_max"]]
            
        # 투자지표 등급 필터
        for indicator in ["growth", "profitability", "stability", "valuation"]:
            filter_key = f"{indicator}_grade"
            if filter_key in filters and filters[filter_key]:
                allowed_grades = filters[filter_key]
                df = df[df[filter_key].isin(allowed_grades)]
                
        # RS값 필터
        if "rs_value_min" in filters and filters["rs_value_min"] is not None:
            df = df[df["rs_value"] >= filters["rs_value_min"]]
            
        if "rs_value_max" in filters and filters["rs_value_max"] is not None:
            df = df[df["rs_value"] <= filters["rs_value_max"]]
            
        # 종합 점수 필터
        if "composite_score_min" in filters and filters["composite_score_min"] is not None:
            df = df[df["composite_score"] >= filters["composite_score_min"]]
            
        return df
        
    def rank_stocks(self, by: str = "composite_score", ascending: bool = False) -> pd.DataFrame:
        """
        종목을 정렬합니다.
        
        Args:
            by: 정렬 기준 컬럼
            ascending: 오름차순 여부
            
        Returns:
            정렬된 DataFrame
        """
        return self.df.sort_values(by=by, ascending=ascending).reset_index(drop=True)
        
    def get_statistics(self) -> Dict:
        """
        데이터 통계를 반환합니다.
        
        Returns:
            통계 딕셔너리
        """
        return {
            "total_stocks": len(self.df),
            "avg_financial_score": self.df["financial_score"].mean(),
            "avg_rs_value": self.df["rs_value"].mean(),
            "avg_composite_score": self.df["composite_score"].mean(),
            "grade_distribution": {
                "growth": self.df["growth_grade"].value_counts().to_dict(),
                "profitability": self.df["profitability_grade"].value_counts().to_dict(),
                "stability": self.df["stability_grade"].value_counts().to_dict(),
                "valuation": self.df["valuation_grade"].value_counts().to_dict()
            }
        }
        
    def get_top_stocks(self, n: int = 10, by: str = "composite_score") -> pd.DataFrame:
        """
        상위 N개 종목을 반환합니다.
        
        Args:
            n: 반환할 종목 수
            by: 정렬 기준
            
        Returns:
            상위 N개 종목 DataFrame
        """
        return self.rank_stocks(by=by, ascending=False).head(n)
        
    def compare_stocks(self, stock_codes: List[str]) -> pd.DataFrame:
        """
        특정 종목들을 비교합니다.
        
        Args:
            stock_codes: 비교할 종목 코드 리스트
            
        Returns:
            비교 DataFrame
        """
        return self.df[self.df["code"].isin(stock_codes)]
        
    def export_to_csv(self, filepath: str, filtered: bool = False, filters: Optional[Dict] = None):
        """
        데이터를 CSV로 내보냅니다.
        
        Args:
            filepath: 저장 경로
            filtered: 필터 적용 여부
            filters: 필터 딕셔너리
        """
        if filtered and filters:
            df = self.filter_stocks(filters)
        else:
            df = self.df
            
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        logger.info(f"CSV 저장 완료: {filepath} ({len(df)}개 종목)")
        
    def apply_custom_filter(self, filter_func: Callable) -> pd.DataFrame:
        """
        사용자 정의 필터 함수를 적용합니다.
        
        Args:
            filter_func: 행을 입력받아 bool을 반환하는 함수
            
        Returns:
            필터링된 DataFrame
        """
        return self.df[self.df.apply(filter_func, axis=1)]


# 편의 함수
def analyze_stocks(stock_data: Dict[str, Dict], filters: Optional[Dict] = None) -> pd.DataFrame:
    """
    종목 데이터를 분석하고 필터링하는 편의 함수
    
    Args:
        stock_data: 종목 데이터
        filters: 필터 조건
        
    Returns:
        필터링된 DataFrame
    """
    analyzer = StockAnalyzer(stock_data)
    
    if filters:
        return analyzer.filter_stocks(filters)
    else:
        return analyzer.df


def get_recommended_stocks(stock_data: Dict[str, Dict], 
                          strategy: str = "balanced",
                          top_n: int = 10) -> pd.DataFrame:
    """
    전략별 추천 종목을 반환합니다.
    
    Args:
        stock_data: 종목 데이터
        strategy: 'conservative', 'balanced', 'aggressive'
        top_n: 반환할 종목 수
        
    Returns:
        추천 종목 DataFrame
    """
    analyzer = StockAnalyzer(stock_data)
    
    # 전략별 필터
    strategy_filters = {
        "conservative": {
            "financial_score_min": 85,
            "growth_grade": ["A", "B"],
            "profitability_grade": ["A", "B"],
            "stability_grade": ["A"],
            "rs_value_min": 75
        },
        "balanced": {
            "financial_score_min": 70,
            "growth_grade": ["A", "B", "C"],
            "profitability_grade": ["A", "B"],
            "rs_value_min": 65
        },
        "aggressive": {
            "financial_score_min": 60,
            "growth_grade": ["A", "B"],
            "rs_value_min": 70
        }
    }
    
    filters = strategy_filters.get(strategy, strategy_filters["balanced"])
    filtered = analyzer.filter_stocks(filters)
    
    return filtered.sort_values("composite_score", ascending=False).head(top_n)
