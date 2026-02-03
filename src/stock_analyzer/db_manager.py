"""
StockEasy 데이터베이스 관리 모듈

SQLite를 사용하여 StockEasy에서 수집한 재무 데이터를 저장하고 조회합니다.
"""

import sqlite3
import os
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd

from . import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StockEasyDB:
    """StockEasy 데이터 관리 클래스"""
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Args:
            db_path: DB 파일 경로 (기본: stock_summary/stockeasy_data.db)
        """
        if db_path is None:
            base_dir = Path(__file__).parent.parent
            db_path = base_dir / "data" / "stockeasy_data.db"
        
        self.db_path = str(db_path)
        self._init_db()
    
    def _init_db(self):
        """데이터베이스 초기화"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # WAL 모드 설정 (동시성 향상)
        cursor.execute("PRAGMA journal_mode=WAL;")
        
        # StockEasy 데이터 테이블
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stockeasy_data (
                code TEXT NOT NULL,
                name TEXT,
                snapshot_date TEXT NOT NULL,
                financial_score REAL,
                financial_grade TEXT,
                growth_grade TEXT,
                profitability_grade TEXT,
                stability_grade TEXT,
                valuation_grade TEXT,
                composite_score REAL,
                created_at TEXT,
                PRIMARY KEY (code, snapshot_date)
            )
        ''')
        
        # 인덱스 생성 (조회 성능 향상)
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_snapshot_date 
            ON stockeasy_data(snapshot_date)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_code 
            ON stockeasy_data(code)
        ''')
        
        conn.commit()
        conn.close()
        
        logger.info(f"StockEasy DB 연결 완료: {self.db_path}")
    
    def save_snapshot(self, stock_data: Dict[str, Dict], snapshot_date: Optional[str] = None) -> int:
        """
        종목 데이터 스냅샷 저장
        
        Args:
            stock_data: 종목 코드를 키로 하는 데이터 딕셔너리
            snapshot_date: 스냅샷 날짜 (기본: 오늘)
        
        Returns:
            저장된 종목 수
        """
        if snapshot_date is None:
            snapshot_date = datetime.now().strftime('%Y-%m-%d')
        
        created_at = datetime.now().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        saved_count = 0
        
        for code, data in stock_data.items():
            if not data:
                continue
            
            financial = data.get("financial_health", {})
            indicators = data.get("indicators", {})
            
            # composite_score 계산 (analyzer.py와 동일한 로직)
            composite_score = self._calculate_composite_score(financial, indicators)
            
            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO stockeasy_data
                    (code, name, snapshot_date, financial_score, financial_grade,
                     growth_grade, profitability_grade, stability_grade, valuation_grade,
                     composite_score, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    code,
                    data.get("name", "Unknown"),
                    snapshot_date,
                    financial.get("score"),
                    financial.get("grade"),
                    indicators.get("growth"),
                    indicators.get("profitability"),
                    indicators.get("stability"),
                    indicators.get("valuation"),
                    composite_score,
                    created_at
                ))
                saved_count += 1
            except Exception as e:
                logger.warning(f"[{code}] 저장 실패: {e}")
        
        conn.commit()
        conn.close()
        
        logger.info(f"스냅샷 저장 완료: {snapshot_date}, {saved_count}개 종목")
        return saved_count
    
    def _calculate_composite_score(self, financial: Dict, indicators: Dict) -> Optional[float]:
        """
        종합 점수 계산
        
        Args:
            financial: 재무 건전성 정보
            indicators: 투자지표 정보
        
        Returns:
            종합 점수 (0-100)
        """
        score = 0
        count = 0
        
        # 재무 건전성 점수 (40% 가중치)
        if financial.get("score") is not None:
            score += financial["score"] * 0.4
            count += 0.4
        
        # 투자지표 등급 점수 (40% 가중치, 각 10%)
        for indicator in ["growth", "profitability", "stability", "valuation"]:
            grade = indicators.get(indicator)
            if grade and grade in config.GRADE_SCORES:
                grade_score = config.GRADE_SCORES[grade] * 20  # 5점 만점 -> 100점 만점
                score += grade_score * 0.1
                count += 0.1
        
        # RS값은 사용 안 함 (20% 가중치 제외)
        
        # 평균 계산
        if count > 0:
            return score / count
        return None
    
    def get_latest_data(self, code_list: Optional[List[str]] = None) -> pd.DataFrame:
        """
        최신 스냅샷 데이터 조회
        
        Args:
            code_list: 조회할 종목 코드 리스트 (None이면 전체)
        
        Returns:
            DataFrame
        """
        conn = sqlite3.connect(self.db_path)
        
        if code_list:
            # 특정 종목 리스트
            placeholders = ','.join('?' * len(code_list))
            query = f'''
                SELECT * FROM stockeasy_data
                WHERE (code, snapshot_date) IN (
                    SELECT code, MAX(snapshot_date)
                    FROM stockeasy_data
                    WHERE code IN ({placeholders})
                    GROUP BY code
                )
            '''
            df = pd.read_sql(query, conn, params=code_list)
        else:
            # 전체 최신 데이터
            query = '''
                SELECT * FROM stockeasy_data
                WHERE (code, snapshot_date) IN (
                    SELECT code, MAX(snapshot_date)
                    FROM stockeasy_data
                    GROUP BY code
                )
            '''
            df = pd.read_sql(query, conn)
        
        conn.close()
        return df
    
    def get_snapshot_by_date(self, snapshot_date: str) -> pd.DataFrame:
        """
        특정 날짜의 스냅샷 데이터 조회
        
        Args:
            snapshot_date: 스냅샷 날짜 (YYYY-MM-DD)
        
        Returns:
            DataFrame
        """
        conn = sqlite3.connect(self.db_path)
        query = 'SELECT * FROM stockeasy_data WHERE snapshot_date = ?'
        df = pd.read_sql(query, conn, params=(snapshot_date,))
        conn.close()
        return df
    
    def get_snapshots_list(self) -> List[Dict]:
        """
        저장된 스냅샷 목록 조회
        
        Returns:
            스냅샷 정보 리스트 [{'date': 'YYYY-MM-DD', 'count': N}, ...]
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT snapshot_date, COUNT(*) as count
            FROM stockeasy_data
            GROUP BY snapshot_date
            ORDER BY snapshot_date DESC
        ''')
        
        snapshots = [
            {'date': row[0], 'count': row[1]}
            for row in cursor.fetchall()
        ]
        
        conn.close()
        return snapshots
    
    def cleanup_old_snapshots(self, days: int = 30) -> int:
        """
        오래된 스냅샷 삭제
        
        Args:
            days: 보관 기간 (일)
        
        Returns:
            삭제된 행 수
        """
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            'DELETE FROM stockeasy_data WHERE snapshot_date < ?',
            (cutoff_date,)
        )
        
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        logger.info(f"{days}일 이전 스냅샷 삭제: {deleted_count}개 행")
        return deleted_count
    
    def get_db_stats(self) -> Dict:
        """
        DB 통계 정보 조회
        
        Returns:
            통계 딕셔너리
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 전체 종목 수
        cursor.execute('SELECT COUNT(DISTINCT code) FROM stockeasy_data')
        total_stocks = cursor.fetchone()[0]
        
        # 전체 스냅샷 수
        cursor.execute('SELECT COUNT(DISTINCT snapshot_date) FROM stockeasy_data')
        total_snapshots = cursor.fetchone()[0]
        
        # 최신 스냅샷 날짜
        cursor.execute('SELECT MAX(snapshot_date) FROM stockeasy_data')
        latest_date = cursor.fetchone()[0]
        
        # 최신 스냅샷의 종목 수
        latest_count = 0
        if latest_date:
            cursor.execute(
                'SELECT COUNT(*) FROM stockeasy_data WHERE snapshot_date = ?',
                (latest_date,)
            )
            latest_count = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            'total_stocks': total_stocks,
            'total_snapshots': total_snapshots,
            'latest_date': latest_date,
            'latest_count': latest_count
        }


from functools import lru_cache

# 편의 함수
@lru_cache(maxsize=1)
def get_db() -> StockEasyDB:
    """기본 DB 인스턴스 반환 (싱글톤)"""
    return StockEasyDB()
