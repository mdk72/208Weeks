"""
설정 관리 모듈
"""

import os
from pathlib import Path
from typing import Dict, Any


# 기본 설정
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data" / "analyzed_stocks"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# StockEasy 설정
STOCKEASY_BASE_URL = "https://stockeasy.intellio.kr"
STOCKEASY_STOCK_INFO_URL = f"{STOCKEASY_BASE_URL}/stock-info"

# API 엔드포인트 (실제 엔드포인트는 사용자가 찾아서 설정)
API_ENDPOINTS = {
    "financial": "/api/stock/{code}/financial",  # 예시, 실제 엔드포인트로 교체 필요
    "indicators": "/api/stock/{code}/indicators",
    "rs": "/api/stock/{code}/rs"
}

# 캐시 설정
CACHE_ENABLED = True
CACHE_EXPIRY_HOURS = 24

# 크롤링 설정
SELENIUM_TIMEOUT = 10
SELENIUM_HEADLESS = True
SELENIUM_WINDOW_SIZE = (1920, 1080)

# 데이터 수집 설정
MAX_RETRIES = 3
RETRY_DELAY = 2  # 초 (재시도 대기 시간)
BATCH_SIZE = 10
RATE_LIMIT_DELAY = 1.0  # API/Selenium 호출 간 대기 시간 (최적화)

# 필터 기본값
DEFAULT_FILTERS = {
    "financial_score_min": 70,
    "rs_value_min": 60,
    "growth_grade": ["A", "B", "C"],
    "profitability_grade": ["A", "B", "C"],
    "stability_grade": ["A", "B", "C"],
    "valuation_grade": ["A", "B", "C"]
}

# 등급 점수 매핑
GRADE_SCORES = {
    "A": 5,
    "B": 4,
    "C": 3,
    "D": 2,
    "E": 1,
    "F": 0
}


def get_env_config() -> Dict[str, Any]:
    """
    환경 변수에서 설정을 가져옵니다.
    
    Returns:
        환경 변수 설정 딕셔너리
    """
    return {
        "stockeasy_token": os.getenv("STOCKEASY_TOKEN"),
        "stockeasy_cookie": os.getenv("STOCKEASY_COOKIE"),
        "api_endpoint_financial": os.getenv("API_ENDPOINT_FINANCIAL", API_ENDPOINTS["financial"]),
        "api_endpoint_indicators": os.getenv("API_ENDPOINT_INDICATORS", API_ENDPOINTS["indicators"]),
        "api_endpoint_rs": os.getenv("API_ENDPOINT_RS", API_ENDPOINTS["rs"])
    }


def get_cache_path(stock_code: str) -> Path:
    """
    종목 코드에 대한 캐시 파일 경로를 반환합니다.
    
    Args:
        stock_code: 종목 코드
        
    Returns:
        캐시 파일 경로
    """
    return DATA_DIR / f"{stock_code}.json"
