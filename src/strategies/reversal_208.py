from datetime import datetime
import pandas as pd
import numpy as np
import sys
import os

# root path for relative imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.loader import fetch_data

def calculate_screener_performance(df_daily, entry_date, entry_price, segments):
    """스크리너 검색일 기준 성과 지표 계산"""
    try:
        # 검색일 이후 데이터만 추출
        df_after = df_daily[df_daily.index > entry_date].copy()
        if df_after.empty:
            return None
        
        # 20일 이동평균 계산
        df_after['MA20'] = df_after['Close'].rolling(window=20).mean()
        
        # 매도 시점 찾기 (간단한 전략: D/E 도달 후 20일선 이탈)
        de_line = segments[4]  # D/E 경계
        exit_date = None
        exit_price = None
        target_hit = False
        
        for i in range(len(df_after)):
            curr_price = df_after['Close'].iloc[i]
            curr_ma20 = df_after['MA20'].iloc[i]
            
            if curr_price >= de_line:
                target_hit = True
            
            if target_hit and pd.notna(curr_ma20) and curr_price < curr_ma20:
                exit_date = df_after.index[i]
                exit_price = curr_price
                break
        
        # 매도 시점 결정 (매도 신호 없으면 오늘까지)
        if exit_date is None:
            analysis_end = df_after.index[-1]
            analysis_df = df_after
            status = "보유중"
        else:
            analysis_end = exit_date
            analysis_df = df_after[df_after.index <= exit_date]
            status = f"매도 ({exit_date.strftime('%Y-%m-%d')})"
        
        # 수익률 계산
        if exit_date is None:
            current_pnl = (df_after['Close'].iloc[-1] - entry_price) / entry_price * 100
        else:
            current_pnl = (exit_price - entry_price) / entry_price * 100
        
        # Max/Min 계산
        max_price = analysis_df['High'].max()
        min_price = analysis_df['Low'].min()
        max_pnl = (max_price - entry_price) / entry_price * 100
        min_pnl = (min_price - entry_price) / entry_price * 100
        
        # Max/Min 날짜
        max_date = analysis_df[analysis_df['High'] == max_price].index[0]
        min_date = analysis_df[analysis_df['Low'] == min_price].index[0]
        
        return {
            '수익률': current_pnl,
            'Max 수익률': max_pnl,
            'Max 날짜': max_date.strftime('%Y-%m-%d'),
            'Min 수익률': min_pnl,
            'Min 날짜': min_date.strftime('%Y-%m-%d'),
            '상태': status
        }
    except Exception as e:
        return None

def analyze_stock_core(ticker, name, df, lookback_weeks=208, bc_breakout_days=60, ignore_conditions=False):
    """핵심 분석 로직: 208주 6등분 및 전략 조건 확인"""
    try:
        if df is None or len(df) < lookback_weeks: return None
        df = df.copy()
        df_weekly = df.resample('W').agg({'Open':'first', 'High':'max', 'Low':'min', 'Close':'last'})
        if len(df_weekly) < lookback_weeks: return None
            
        history = df_weekly.tail(lookback_weeks)
        low_208 = history['Low'].min()
        high_208 = history['High'].max()
            
        range_208 = high_208 - low_208
        if range_208 == 0: return None
        
        step = range_208 / 6
        current_price = float(df['Close'].iloc[-1])
        
        # Segments: Low, A/B, B/C, C/D, D/E, E/F, High
        segments = [low_208 + i*step for i in range(7)]
        
        # Determine Current Segment
        if current_price <= segments[1]: curr_seg = "Segment A"
        elif current_price <= segments[2]: curr_seg = "Segment B"
        elif current_price <= segments[3]: curr_seg = "Segment C"
        elif current_price <= segments[4]: curr_seg = "Segment D"
        elif current_price <= segments[5]: curr_seg = "Segment E"
        else: curr_seg = "Segment F"
        
        # 20일선 상태 계산
        df['MA20'] = df['Close'].rolling(window=20).mean()
        curr_ma20 = float(df['MA20'].iloc[-1])
        ma_status = "O (Above)" if current_price >= curr_ma20 else "X (Below)"
        
        # B/C 라인 돌파 확인 (최근 N일)
        bc_line = segments[2]
        recent_low = df['Low'].tail(bc_breakout_days).min()
        
        if not ignore_conditions:
            # Condition 1: Must be in Segment C
            if curr_seg != "Segment C":
                return None 
            
            # Condition 2: Golden Cross over B/C line within last N days
            if recent_low >= bc_line:
                return None 
            
            # Condition 2-2: B/C 라인 근처만 선택 (5% 이내)
            max_rise_from_bc = 0.05
            if current_price > bc_line * (1 + max_rise_from_bc):
                return None
            
            # Condition 3: Above 20MA
            if current_price < curr_ma20:
                 return None
        
        return {
            'Code': ticker, 'Name': name, 
            '매수가': current_price,
            '208주 최저': low_208, '208주 최고': high_208,
            '현재 구간': curr_seg, '20일선': ma_status,
            'df_daily': df, 'segments': segments,
            'B/C 라인': bc_line,
            'B/C 상승률': ((current_price - bc_line) / bc_line * 100),
            'recent_low': recent_low
        }
    except:
        return None
