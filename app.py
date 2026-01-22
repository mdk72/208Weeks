import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go
import requests
import sqlite3
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import threading
import traceback

# --- 상수 및 초기 설정 ---
CACHE_DB = "price_cache.db"
db_lock = threading.Lock()

def init_db():
    with db_lock:
        conn = sqlite3.connect(CACHE_DB)
        cursor = conn.cursor()
        # WAL 모드 설정 (동시성 향상)
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_data (
                ticker TEXT,
                date TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                PRIMARY KEY (ticker, date)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cache_meta (
                ticker TEXT PRIMARY KEY,
                last_updated TEXT
            )
        ''')
        conn.commit()
        conn.close()

def get_cached_data(ticker, requested_start_date):
    if not os.path.exists(CACHE_DB): return None
    try:
        with db_lock:
            conn = sqlite3.connect(CACHE_DB)
            cursor = conn.cursor()
            
            # [HOTFIX] Check the earliest date cached for this ticker
            cursor.execute("SELECT MIN(date) FROM price_data WHERE ticker = ?", (ticker,))
            min_date_row = cursor.fetchone()
            
            if min_date_row and min_date_row[0]:
                cached_min_date_str = min_date_row[0]
                cached_min_date = datetime.strptime(cached_min_date_str, '%Y-%m-%d').date()
                requested_start_date_obj = datetime.strptime(requested_start_date, '%Y-%m-%d').date()
                
                # [FIX] Allow 7-day grace period for holidays/weekends
                # If cached data starts more than 7 days AFTER requested, we need more history
                if cached_min_date > (requested_start_date_obj + timedelta(days=7)):
                    conn.close()
                    return None

            cursor.execute("SELECT last_updated FROM cache_meta WHERE ticker = ?", (ticker,))
            row = cursor.fetchone()
            
            today_str = datetime.now().strftime('%Y-%m-%d')
            if row and row[0] == today_str:
                df = pd.read_sql_query("SELECT * FROM price_data WHERE ticker = ? AND date >= ?", conn, params=(ticker, requested_start_date))
                conn.close()
                if not df.empty:
                    df['date'] = pd.to_datetime(df['date'])
                    
                    # [NEW] Data completeness check
                    last_data_date = df['date'].max()
                    current_time = datetime.now()
                    
                    # If after market close (15:30), today's data should exist
                    market_close = current_time.replace(hour=15, minute=30, second=0, microsecond=0)
                    
                    if current_time > market_close:
                        # Check if today's data exists
                        today_date = pd.Timestamp(today_str)
                        if last_data_date < today_date:
                            # [FIX] Instead of just returning None (which might hit cache again), 
                            # we should probably continue to fetch_data to update it.
                            return None  # Invalidate cache
                    
                    df.set_index('date', inplace=True)
                    df.columns = [c.capitalize() for c in df.columns]
                    return df
            conn.close()
    except Exception as e:
        print(f"Cache Read Error ({ticker}): {e}")
    return None

def save_to_cache(ticker, df):
    if df is None or df.empty: return
    try:
        df_to_save = df.reset_index()
        target_cols = ['Open', 'High', 'Low', 'Close']
        
        # 컬럼 인덱스 찾기
        date_col = 'Date' if 'Date' in df_to_save.columns else ('date' if 'date' in df_to_save.columns else ('index' if 'index' in df_to_save.columns else None))
        if date_col is None: return

        today_str = datetime.now().strftime('%Y-%m-%d')
        
        with db_lock:
            conn = sqlite3.connect(CACHE_DB)
            for _, row in df_to_save.iterrows():
                try:
                    d = row[date_col]
                    date_str = d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d)[:10]
                    conn.execute("INSERT OR REPLACE INTO price_data (ticker, date, open, high, low, close) VALUES (?, ?, ?, ?, ?, ?)",
                                 (ticker, date_str, float(row['Open']), float(row['High']), float(row['Low']), float(row['Close'])))
                except: continue
            
            conn.execute("INSERT OR REPLACE INTO cache_meta (ticker, last_updated) VALUES (?, ?)", (ticker, today_str))
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"Cache Write Error ({ticker}): {e}")

import time
import random

def fetch_data(ticker, market, start_date="2010-01-01"):
    # Rate Limit 방지: 랜덤 딜레이 (0.2~0.4초)
    time.sleep(random.uniform(0.2, 0.4))
    
    yf_ticker = ticker + (".KS" if market == "KOSPI" else ".KQ")
    cached_df = get_cached_data(ticker, start_date)
    if cached_df is not None:
        return cached_df, True  # (데이터, 캐시_사용_여부)
    
    try:
        # yfinance 호출 실패 시 재시도 로직 없이 바로 실패 처리 (쓰로틀링 우선)
        # threads=False로 설정하여 내부 스레딩 비활성화 (외부 ThreadPoolExecutor 충돌 방지)
        df = yf.download(yf_ticker, start=start_date, progress=False, timeout=10, threads=False, auto_adjust=False)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        save_to_cache(ticker, df)
        return df, False  # (데이터, 캐시_사용_여부)
    except Exception as e:
        # print(f"Fetch Error ({ticker}): {e}") # 로그 과다 방지
        return None, False


def calculate_screener_performance(df_daily, entry_date, entry_price, segments):
    """
    스크리너 검색일 기준 성과 지표 계산
    - 검색일에 매수했다고 가정
    - 전략 조건에 따라 매도 시점 계산
    - Max/Min 수익률 및 날짜 반환
    """
    try:
        # 검색일 이후 데이터만 추출
        df_after = df_daily[df_daily.index > entry_date].copy()
        print(f"[DEBUG] Entry Date: {entry_date}, Data After: {len(df_after)} rows, Last Date: {df_daily.index[-1] if len(df_daily) > 0 else 'N/A'}")
        if df_after.empty:
            print(f"[DEBUG] No data after entry_date {entry_date}. Returning None.")
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
        print(f"[DEBUG] Performance calculation error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None



def analyze_stock_core(ticker, name, df, lookback_weeks=208, bc_breakout_days=60):
    try:
        if df is None or len(df) < lookback_weeks: return None
        df_weekly = df.resample('W').agg({'Open':'first', 'High':'max', 'Low':'min', 'Close':'last'})
        if len(df_weekly) < lookback_weeks: return None
            
        history = df_weekly.tail(lookback_weeks)
        low_208 = history['Low'].min()
        high_208 = history['High'].max()
            
        range_208 = high_208 - low_208
        if range_208 == 0: return None
        
        step = range_208 / 6
        current_price = float(df['Close'].iloc[-1])
        
        # Segments
        segments = [low_208 + i*step for i in range(7)]
        # Segments: Low, A/B, B/C, C/D, D/E, E/F, High
        
        # Condition 1: Current Price in Segment C (B/C < Price <= C/D)
        bc_line = segments[2]
        cd_line = segments[3]
        
        if not (bc_line < current_price <= cd_line):
            return None # Skip if not in Segment C
            
        curr_seg = "Segment C"
        
        # Condition 2: Golden Cross over B/C line within last N days (Rising Logic)
        # 하락하다가 멈춘게 아니라, "밑에서 치고 올라온" 종목이어야 함.
        # 최근 N일 내에 최저가가 B/C 라인보다 낮았어야 함 (돌파 발생 확인)
        recent_low = df['Low'].tail(bc_breakout_days).min()
        if recent_low >= bc_line:
            return None # 최근에 B/C 밑에 있었던 적이 없으면(계속 위에 있었거나 위에서 내려옴) 탈락
        
        # Condition 2-2: B/C 라인 근처만 선택 (과도하게 상승한 종목 제외)
        # B/C 돌파 후 5% 이내 종목만 스크린
        max_rise_from_bc = 0.05  # 5% 제한 (조정 가능)
        if current_price > bc_line * (1 + max_rise_from_bc):
            return None  # B/C + 5% 초과 시 탈락
        
        # Condition 3: Above 20MA
        df_temp = df.tail(30).copy()
        df_temp['MA20'] = df_temp['Close'].rolling(window=20).mean()
        curr_ma20 = float(df_temp['MA20'].iloc[-1])
        
        if current_price < curr_ma20:
             return None # Skip if below 20MA
        
        ma_status = "O (Above)"
        
        return {
            'Code': ticker, 'Name': name, 
            '매수가': current_price,  # 검색일 종가
            '208주 최저': low_208, '208주 최고': high_208,
            '현재 구간': curr_seg, '20일선': ma_status,
            'df_daily': df, 'segments': segments,
            'B/C 라인': bc_line,  # B/C 라인 추가
            'B/C 상승률': ((current_price - bc_line) / bc_line * 100),  # B/C 대비 상승률
            'recent_low': recent_low # 디버깅용
        }
    except:
        return None

def process_backtest_stock(ticker, name, market, config, current_row=None, pre_fetched_df=None):
    try:
        if pre_fetched_df is not None:
            df_daily = pre_fetched_df.copy()
        else:
            result = fetch_data(ticker, market)
            if result is None:
                df_daily = None
            else:
                df_daily, _ = result  # 캐시 여부는 무시
            
        lookback_days = config.get('lookback', 208)
        # [Sync] 스크리너와 동일한 최소 길이 조건 적용 (기존 1000일 -> lookback일)
        # 1000일로 하드코딩하면 LG엔솔 같은 신규 상장주(약 4년)가 휴장일 등으로 1000일 미달 시 탈락함
        if df_daily is None or len(df_daily) < lookback_days:
             return {
                'Ticker': ticker, 'Name': name, 'Total PnL (%)': 0.0,
                'Trades': 0, 'Win Rate (%)': 0.0,
                'Recent Buy': '-', 'Recent Sell': '-',
                'df_daily': None, 'trades': []
            }
        
        # 실시간 데이터 반영 (캐시된 데이터가 오늘짜가 아닐 경우 또는 업데이트)
        log_txt = ""
        debug_msg = "No Update"
        if current_row is not None:
            last_date = df_daily.index[-1]
            today = pd.Timestamp(datetime.now().date())
            curr_price = float(current_row.get('현재가', 0))
            
            if curr_price > 0:
                if last_date.date() < today.date():
                    try:
                        new_row = pd.DataFrame({
                            'Open': [curr_price], 
                            'High': [curr_price], 
                            'Low': [curr_price], 
                            'Close': [curr_price],
                            'Volume': [0]
                        }, index=[today])
                        df_daily = pd.concat([df_daily, new_row])
                        debug_msg = f"Added Today {curr_price}"
                        # 추가된 행에 대한 지표 계산을 위해 원본 df_daily 갱신 필요
                    except Exception as e:
                         debug_msg = f"Add Fail: {e}"
                elif last_date.date() == today.date():
                    # 오늘 데이터가 이미 있지만, 실시간 가격으로 갱신 (종가 업데이트)
                    try:
                        df_daily.at[last_date, 'Close'] = curr_price
                        if curr_price > df_daily.at[last_date, 'High']:
                            df_daily.at[last_date, 'High'] = curr_price
                        if curr_price < df_daily.at[last_date, 'Low']:
                            df_daily.at[last_date, 'Low'] = curr_price
                        debug_msg = f"Updated Today {curr_price}"
                    except Exception as e:
                        debug_msg = f"Update Fail: {e}"
            
        buy_breakout = config['buy_breakout']
        buy_ma20 = config['buy_ma20']
        buy_segment = config['buy_segment']
        exit_target = config['exit_target']
        exit_method = config['exit_method']
        stop_loss_pct = config['stop_loss_pct']
        start_date = config.get('start_date', '2020-01-01')
        end_date = config.get('end_date', None)
        force_liquidate = config.get('force_liquidate', False)
        
        df_daily = df_daily.copy()
        df_daily['MA20'] = df_daily['Close'].rolling(window=20).mean()
        # 1040일 롤링으로 208주 고저가 근사 (벡터화 속도 개선)
        # [Sync] 스크리너와 동일하게 오늘 데이터 포함 (shift 제거)
        # 스크리너는 df_weekly.tail(208) (오늘 포함)을 사용하므로, 백테스트도 shift 없이 오늘 포함해야 함.
        df_daily['RollLow'] = df_daily['Low'].rolling(window=1040).min()
        df_daily['RollHigh'] = df_daily['High'].rolling(window=1040).max()
        
        trades = []
        position = None
        target_hit = False
        # 설정된 날짜 범위로 필터링
        df_test = df_daily[df_daily.index >= pd.Timestamp(start_date)].copy()
        if end_date:
            df_test = df_test[df_test.index <= pd.Timestamp(end_date)]
        
        for i in range(len(df_test)):
            low_208 = df_test['RollLow'].iloc[i]
            high_208 = df_test['RollHigh'].iloc[i]
            if pd.isna(low_208): continue
            
            curr_date = df_test.index[i]
            curr_price = float(df_test['Close'].iloc[i])
            ma20 = float(df_test['MA20'].iloc[i])
            step = (high_208 - low_208) / 6
            bounds = [low_208 + j*step for j in range(7)]
            
            if exit_target == "C/D Boundary": target_boundary = bounds[3]
            elif exit_target == "E/F Boundary": target_boundary = bounds[5]
            else: target_boundary = bounds[4]
            
            if position is None:
                is_buy = True
                if buy_segment == "Segment B (A/B~B/C)":
                    if not (bounds[1] < curr_price <= bounds[2]): is_buy = False
                else: 
                    if not (bounds[2] < curr_price <= bounds[3]): is_buy = False
                    
                if is_buy and buy_breakout:
                    bnd = bounds[2] if buy_segment == "Segment C (B/C~C/D)" else bounds[1]
                    # [FIX] 스크리너와 동기화: config의 bc_breakout_days 사용
                    bc_days = config.get('bc_breakout_days', 60)
                    was_below = float(df_test['Close'].iloc[max(0, i-bc_days):i].min()) <= bnd
                    if not was_below: is_buy = False
                    
                if is_buy and buy_ma20 and curr_price < ma20: is_buy = False
                    
                if is_buy:
                    position = {'entry_date': curr_date, 'entry_price': curr_price, 'segments': bounds}
                    target_hit = False
            else:
                sell_sig = False
                if curr_price >= target_boundary: target_hit = True
                if exit_method == "목표가 도달 시 즉시 매도":
                    if target_hit: sell_sig = True
                else:
                    if target_hit and curr_price < ma20: sell_sig = True
                if not sell_sig and stop_loss_pct > 0:
                    if curr_price < position['entry_price'] * (1 - stop_loss_pct / 100): sell_sig = True
                
                if sell_sig:
                    trades.append({
                        'entry_date': position['entry_date'], 'entry_price': position['entry_price'],
                        'exit_date': curr_date, 'exit_price': curr_price,
                        'pnl': (curr_price / position['entry_price'] - 1) * 100,
                        'duration': (curr_date - position['entry_date']).days,
                        'segments': position['segments']
                    })
                    position = None
                    target_hit = False
        
        # 보유 중인 포지션 처리
        if position is not None:
            if force_liquidate:
                # 옵션 2: 종료일 기준 강제 청산
                final_price = float(df_test['Close'].iloc[-1])
                final_date = df_test.index[-1]
                trades.append({
                    'entry_date': position['entry_date'], 'entry_price': position['entry_price'],
                    'exit_date': final_date, 'exit_price': final_price,
                    'pnl': (final_price / position['entry_price'] - 1) * 100,
                    'duration': (final_date - position['entry_date']).days,
                    'segments': position['segments']
                })
            else:
                # 옵션 1: 보유 중인 포지션 별도 표시
                current_price = float(df_test['Close'].iloc[-1])
                trades.append({
                    'entry_date': position['entry_date'], 'entry_price': position['entry_price'],
                    'exit_date': None,  # 보유중 표시
                    'exit_price': current_price,
                    'pnl': (current_price / position['entry_price'] - 1) * 100,
                    'duration': (df_test.index[-1] - position['entry_date']).days,
                    'segments': position['segments']
                })
        
        
        # 디버깅: 종료일 기준 매수 조건 체크 (모든 종목에 대해 로그 남김)
        if len(df_test) > 0:
            last_idx = len(df_test) - 1
            low_208 = df_test['RollLow'].iloc[last_idx]
            high_208 = df_test['RollHigh'].iloc[last_idx]
            curr_price = float(df_test['Close'].iloc[last_idx])
            ma20 = float(df_test['MA20'].iloc[last_idx])
            
            # 로그 데이터 강화 (Data Proof)
            log_txt += f"Chk:{df_test.index[-1].date()} C:{curr_price} H:{high_208:.0f} L:{low_208:.0f}"
            
            if not pd.isna(low_208):
                 step = (high_208 - low_208) / 6
                 bounds = [low_208 + j*step for j in range(7)]
                 
                 is_buy = True
                 if buy_segment == "Segment B (A/B~B/C)":
                     if not (bounds[1] < curr_price <= bounds[2]): is_buy = False
                 else: 
                     if not (bounds[2] < curr_price <= bounds[3]): is_buy = False
                 log_txt += f" Seg:{is_buy}"
                 
                 if is_buy and buy_breakout:
                    bnd = bounds[2] if buy_segment == "Segment C (B/C~C/D)" else bounds[1]
                    # [Sync] 스크리너(12주)와 로직 일치: 5일 -> 60일, Close -> Low
                    check_start = max(0, last_idx-60)
                    was_below = float(df_test['Low'].iloc[check_start:last_idx].min()) <= bnd if last_idx > 0 else False
                    if not was_below: is_buy = False
                    log_txt += f"Brk:{was_below}"
                 
                 if is_buy and buy_ma20 and curr_price < ma20: 
                     is_buy = False
                     log_txt += f" MA20:False"
                 
                 if is_buy: log_txt += " -> BUY!"
                 else: log_txt += " -> NO"
                 if position is not None: log_txt += "(Held)"

        # 종료일 기준 신규 매수 신호 체크 (position이 None인 경우에만 실제 매수 처리)
        if position is None and len(df_test) > 0:
            last_idx = len(df_test) - 1
            low_208 = df_test['RollLow'].iloc[last_idx]
            high_208 = df_test['RollHigh'].iloc[last_idx]
            
            if not pd.isna(low_208):
                curr_date = df_test.index[last_idx]
                curr_price = float(df_test['Close'].iloc[last_idx])
                ma20 = float(df_test['MA20'].iloc[last_idx])
                step = (high_208 - low_208) / 6
                bounds = [low_208 + j*step for j in range(7)]
                
                # 매수 조건 체크
                is_buy = True
                if buy_segment == "Segment B (A/B~B/C)":
                    if not (bounds[1] < curr_price <= bounds[2]): is_buy = False
                else: 
                    if not (bounds[2] < curr_price <= bounds[3]): is_buy = False
                
                if is_buy and buy_breakout:
                    bnd = bounds[2] if buy_segment == "Segment C (B/C~C/D)" else bounds[1]
                    # [FIX] 여기도 60일로 수정해야 실제 매수가 됨
                    check_start = max(0, last_idx-60)
                    was_below = float(df_test['Low'].iloc[check_start:last_idx].min()) <= bnd if last_idx > 0 else False
                    if not was_below: is_buy = False
                    
                if is_buy and buy_ma20 and curr_price < ma20: 
                    is_buy = False
                
                if is_buy:
                    trades.append({
                        'entry_date': curr_date,
                        'entry_price': curr_price,
                        'exit_date': None,
                        'exit_price': curr_price,
                        'pnl': 0.0,
                        'duration': 0,
                        'segments': bounds,
                        'is_new_signal': True
                    })

        # [Validation] 스크리너 로직(analyze_stock_core)으로 최종 검증 (The Silver Bullet)
        # 루프 방식(approximation)과 resample 방식(exact)의 오차를 없애기 위해
        # "시뮬레이션 종료일" 기준으로 스크리너와 동일한 함수를 직접 호출하여 확인
        try:
            lookback = config.get('lookback', 208)
            end_date_ts = pd.Timestamp(config.get('end_date'))
            
            # [CRITICAL FIX] df_test가 아닌 df_daily 전체를 end_date까지 필터링해서 사용
            # df_test는 start_date부터 시작하므로 짧은 기간(15일 등) 설정 시 데이터 부족으로 검증 실패
            # 스크리너는 전체 히스토리를 사용하므로, 백테스트도 동일하게 충분한 히스토리 제공 필요
            df_for_core = df_daily[df_daily.index <= end_date_ts]
            
            core_res = analyze_stock_core(ticker, name, df_for_core, lookback)
            if core_res:
                log_txt += " [Core:BUY]"
                # 만약 Core는 Buy인데 trades에 신규 신호가 없다면? -> 강제 추가
                has_new_signal = any(t.get('is_new_signal') for t in trades)
                if not has_new_signal:
                    if position is None: # 보유 중이 아닐 때만
                        log_txt += "(Added by Core)"
                        trades.append({
                            # 종료일 기준 데이터 사용
                            'entry_date': df_for_core.index[-1],
                            'entry_price': float(df_for_core['Close'].iloc[-1]),
                            'exit_date': None,
                            'exit_price': float(df_for_core['Close'].iloc[-1]),
                            'pnl': 0.0,
                            'duration': 0,
                            'segments': core_res['segments'],
                            'is_new_signal': True
                        })
                    else:
                        log_txt += "(Held)"
            else:
                 log_txt += " [Core:NO]"
        except Exception as e:
            # df_for_core가 비어있거나 하면 에러 날 수 있음
            log_txt += f" [CoreErr:{str(e)[:30]}]"
                    
        # trades가 있거나, 디버그 메시지가 "Added" 또는 "Updated"를 포함하면 반환
        if trades:
            # Screener Date: 현재 보유 중인 포지션의 최초 매수일
            # 보유 중이면 마지막 거래의 entry_date, 매도 완료면 trade 중 exit_date=None인 것 찾기
            last_trade = trades[-1]
            if last_trade['exit_date'] is None or last_trade.get('is_new_signal', False):
                # 보유중 또는 신규: 마지막 거래의 매수일
                last_buy = last_trade['entry_date'].strftime('%Y-%m-%d')
            else:
                # 매도 완료: 마지막으로 보유했던 거래 찾기 (없으면 마지막 거래)
                held_trades = [t for t in trades if t['exit_date'] is None]
                if held_trades:
                    last_buy = held_trades[-1]['entry_date'].strftime('%Y-%m-%d')
                else:
                    last_buy = last_trade['entry_date'].strftime('%Y-%m-%d')
            
            # 현재 수익률 계산 (보유중/신규일 경우만)
            current_pnl = trades[-1]['pnl'] if (trades[-1]['exit_date'] is None or trades[-1].get('is_new_signal', False)) else None
            
            # 신규 매수 신호인지 확인
            if trades[-1].get('is_new_signal', False):
                last_sell = '🆕 신규'
            elif trades[-1]['exit_date'] is None:
                last_sell = '보유중'
            else:
                last_sell = trades[-1]['exit_date'].strftime('%Y-%m-%d')
            
            return {
                'Ticker': ticker, 'Name': name, 'Total PnL (%)': sum(t['pnl'] for t in trades),
                'Trades': len(trades), 'Win Rate (%)': (len([t for t in trades if t['pnl'] > 0]) / len(trades)) * 100,
                'Recent Buy': last_buy, 
                'Recent Buy Price': last_trade['entry_price'],
                'Recent Sell': last_sell,
                'Recent Sell Price': last_trade['exit_price'],
                'Current PnL (%)': current_pnl,  # 현재 수익률 추가
                'df_daily': df_daily, 'trades': []
            }
        # Removed: elif block for debug messages (no longer needed)
    except Exception as e:
        return {
            'Ticker': ticker, 'Name': name, 'Total PnL (%)': 0.0,
            'Trades': 0, 'Win Rate (%)': 0.0,
            'Recent Buy': '-', 'Recent Sell': '-',
            'Current PnL (%)': None,
            'df_daily': None, 'trades': []
        }
    return None
    return None

# --- UI Setup ---
st.set_page_config(page_title="208주 6등분 스크리너", layout="wide")
init_db()

import io

from bs4 import BeautifulSoup

@st.cache_data
def get_stock_list_naver(market_type, top_n=200):
    # 네이버 금융 시가총액 상위 리스트 크롤링 (BeautifulSoup 사용)
    sosok = 0 if market_type == "KOSPI" else 1
    stocks = []
    
    try:
        pages = (top_n // 50) + 2
        for page in range(1, pages):
            url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
            res.encoding = 'cp949'
            
            soup = BeautifulSoup(res.text, 'lxml')
            table = soup.find('table', {'class': 'type_2'})
            
            if not table: continue
            
            for tr in table.find_all('tr'):
                tds = tr.find_all('td')
                if len(tds) <= 1: continue # 구분선 등 건너뜀
                
                # N(순위) 확인
                try:
                    rank = tds[0].text.strip()
                    if not rank.isdigit(): continue
                except: continue
                
                # 종목명 및 코드 추출 (2번째 td의 a 태그)
                try:
                    a_tag = tds[1].find('a')
                    if not a_tag: continue
                    
                    name = a_tag.text.strip()
                    href = a_tag['href'] # e.g., /item/main.naver?code=005930
                    code = href.split('=')[-1].zfill(6)
                    
                    # 현재가 추출 (3번째 td)
                    try:
                        price_txt = tds[2].text.strip().replace(',', '')
                        current_price = int(price_txt)
                    except:
                        current_price = 0
                    
                    stocks.append({'Code': code, 'Name': name, '현재가': current_price})
                except: continue
                
            if len(stocks) >= top_n:
                break
                
        return pd.DataFrame(stocks).head(top_n)
    except Exception as e:
        st.error(f"네이버 금융 크롤링 실패: {e}")
        # fallback
        return pd.DataFrame([
            {'Code':'005930', 'Name':'삼성전자'}, {'Code':'000660', 'Name':'SK하이닉스'},
            {'Code':'373220', 'Name':'LG에너지솔루션'}, {'Code':'207940', 'Name':'삼성바이오로직스'},
            {'Code':'005380', 'Name':'현대차'}, {'Code':'000270', 'Name':'기아'}
        ])

# --- 설정 저장/불러오기 ---
import json
import os # Added this import for os.path.exists

SETTINGS_FILE = "user_settings.json"

def load_settings():
    """이전 설정값 불러오기"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    # 기본값
    return {
        'market': 'KOSPI',
        'lookback': 208,
        'n_stocks': 200,
        'bc_breakout_days': 60
    }

def save_settings(settings):
    """현재 설정값 저장"""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Settings save error: {e}")

st.title(" 208-Week High-Speed System")


with st.sidebar:
    st.header("🔍 설정")
    
    # 설정 불러오기
    saved_settings = load_settings()
    
    # 시장 선택 (인덱스로 변환)
    market_options = ["KOSPI", "KOSDAQ"]
    market_idx = market_options.index(saved_settings.get('market', 'KOSPI'))
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
    if st.button("🗑️ 가격 캐시 초기화", help="저장된 가격 데이터를 모두 삭제하고 새로 내려받습니다."):
        try:
            if os.path.exists(CACHE_DB):
                # DB 연결이 열려 있을 수 있으므로 연결 종료 시도는 못하지만, 파일 삭제 시도
                os.remove(CACHE_DB)
                st.success("캐시가 초기화되었습니다. 다시 스캔해 주세요.")
                st.rerun()
        except Exception as e:
            st.error(f"캐시 삭제 실패: {e}")



tab1, tab2 = st.tabs(["📊 실시간 스크리너", "🧪 백테스팅"])

with tab1:
    st.markdown("### 📍 실시간 종목 스크린")
    
    # [New] 검색 날짜 선택 (백테스트 검증용)
    scan_date = st.date_input(
        "검색 기준 날짜",
        value=datetime.now().date(),
        help="이 날짜 기준으로 조건을 만족하는 종목을 검색합니다. 백테스트 결과와 비교 검증 시 유용합니다."
    )
    
    if st.button("� 실시간 종목 스캔 시작"):
        stock_list = get_stock_list_naver(market_sel, n_stocks_sel)
        results = []
        pb = st.progress(0)
        st_txt = st.empty()
        
        # 병렬 처리 최적화 (6 workers)
        cache_hit = 0
        cache_miss = 0
        with ThreadPoolExecutor(max_workers=6) as executor:
            future_to_stock = {executor.submit(fetch_data, row['Code'], market_sel): row for _, row in stock_list.iterrows()}
            
            success_count = 0
            fail_count = 0
            
            for i, future in enumerate(as_completed(future_to_stock)):
                stock_row = future_to_stock[future]
                try:
                    result = future.result()
                    if result is None:
                        fail_count += 1
                        continue
                    
                    df, from_cache = result
                    if from_cache:
                        cache_hit += 1
                    else:
                        cache_miss += 1
                    
                    if df is not None and not df.empty:
                        # [Chart] 차트용 원본 데이터 보존 (전체 기간 표시)
                        df_full_for_chart = df.copy()
                        
                        # [New] 선택된 날짜 기준으로 데이터 필터링 (분석용)
                        target_date = pd.Timestamp(scan_date)
                        df = df[df.index <= target_date]
                        
                        if df.empty:
                            fail_count += 1
                            continue
                        
                        # [FIX] 가격 반영 로직 (선택 날짜 기준)
                        cur_p = stock_row.get('현재가', 0)
                        last_date = df.index[-1]
                        today = pd.Timestamp(datetime.now().date())
                        
                        # 오늘 날짜를 선택한 경우: 실시간 가격 사용
                        if scan_date == today.date() and cur_p > 0:
                            # 데이터가 과거면 Append (새로운 주봉 생성 가능)
                            if last_date.date() < today.date():
                                new_row = pd.DataFrame({
                                    'Open': [cur_p], 'High': [cur_p], 'Low': [cur_p], 'Close': [cur_p], 'Volume': [0]
                                }, index=[today])
                                df = pd.concat([df, new_row])
                                df_full_for_chart = pd.concat([df_full_for_chart, new_row])  # 차트용도 업데이트
                            # 오늘 데이터면 Update
                            elif last_date.date() == today.date():
                                df.at[last_date, 'Close'] = cur_p
                                if cur_p > df.at[last_date, 'High']: df.at[last_date, 'High'] = cur_p
                                if cur_p < df.at[last_date, 'Low']: df.at[last_date, 'Low'] = cur_p
                                # 차트용도 동일하게 업데이트
                                df_full_for_chart.at[last_date, 'Close'] = cur_p
                                if cur_p > df_full_for_chart.at[last_date, 'High']: df_full_for_chart.at[last_date, 'High'] = cur_p
                                if cur_p < df_full_for_chart.at[last_date, 'Low']: df_full_for_chart.at[last_date, 'Low'] = cur_p
                        # 과거 날짜 선택: 해당 날짜의 종가 사용 (실시간 가격 무시)

                        # [FIX] 검색일 기준으로 분석하도록 데이터 자르기
                        scan_date_ts = pd.Timestamp(scan_date)
                        df_until_scan = df[df.index <= scan_date_ts].copy()
                        
                        res = analyze_stock_core(stock_row['Code'], stock_row['Name'], df_until_scan, lookback_sel, bc_breakout_days)
                        if res:
                            # 차트는 전체 기간 표시하도록 원본 데이터로 교체
                            res['df_daily'] = df_full_for_chart
                            
                            # 현재가 추가 (오늘 종가)
                            res['현재가'] = float(df_full_for_chart['Close'].iloc[-1])
                            
                            # 성과 지표 계산 (검색일 기준)
                            entry_date = pd.Timestamp(scan_date)
                            entry_price = res['매수가']  # 검색일 종가
                            perf = calculate_screener_performance(df_full_for_chart, entry_date, entry_price, res['segments'])
                            
                            if perf:
                                res.update(perf)  # 수익률, Max/Min, 상태 추가
                            
                            results.append(res)
                            success_count += 1
                        else:
                            # 조건 불만족 (이유는 다양함: 데이터 부족, 전략 미달성 등)
                            pass
                    else:
                        fail_count += 1
                except Exception as e:
                    fail_count += 1
                
                # 진행률 및 상태 표시 업데이트
                pb.progress((i + 1) / n_stocks_sel)
                cache_rate = (cache_hit / (cache_hit + cache_miss) * 100) if (cache_hit + cache_miss) > 0 else 0
                st_txt.text(f"분석 중... ({i+1}/{n_stocks_sel}) | 발견: {len(results)}개 | 캐시: {cache_rate:.0f}% ({cache_hit}/{cache_hit+cache_miss})")
        
        # 스캔 완료 통계
        total_scanned = cache_hit + cache_miss
        cache_rate = (cache_hit / total_scanned * 100) if total_scanned > 0 else 0
        
        if results:
            st.session_state['scan_results'] = results
            st.session_state['scan_market'] = market_sel
            st.session_state['scan_date'] = scan_date  # 검색 날짜 저장
            st.info(f"📊 **성능 통계** | 캐시 활용: {cache_rate:.1f}% ({cache_hit}/{total_scanned}) | API 호출: {cache_miss}회")
        else:
            # 결과가 없으면 이전 결과 초기화
            if 'scan_results' in st.session_state:
                del st.session_state['scan_results']
            st.warning("결과가 없습니다.")

    # 스캔 결과 표시 (항상 표시)
    if 'scan_results' in st.session_state:
        st.success(f"스캔 완료! {len(st.session_state['scan_results'])}개 종목 분석")
        
        # DataFrame 생성 및 컬럼 정리
        df_disp = pd.DataFrame(st.session_state['scan_results']).drop(columns=['df_daily', 'segments', 'recent_low'], errors='ignore')
        
        # [가독성 개선] 수익률과 상태 통합
        if '수익률' in df_disp.columns and '상태' in df_disp.columns:
            df_disp['수익률/상태'] = df_disp.apply(
                lambda row: f"{'+' if row['수익률'] > 0 else ''}{row['수익률']:.1f}% ({row['상태']})" 
                if pd.notna(row['수익률']) and pd.notna(row['상태']) else '-',
                axis=1
            )
            df_disp.drop(columns=['수익률', '상태'], inplace=True)
        
        # [가독성 개선] Max/Min 수익률과 날짜 통합
        if 'Max 수익률' in df_disp.columns and 'Max 날짜' in df_disp.columns:
            df_disp['Max 수익/날짜'] = df_disp.apply(
                lambda row: f"{'+' if row['Max 수익률'] > 0 else ''}{row['Max 수익률']:.1f}% ({row['Max 날짜']})" 
                if pd.notna(row['Max 수익률']) and pd.notna(row['Max 날짜']) else '-',
                axis=1
            )
            df_disp.drop(columns=['Max 수익률', 'Max 날짜'], inplace=True)
        
        if 'Min 수익률' in df_disp.columns and 'Min 날짜' in df_disp.columns:
            df_disp['Min 수익/날짜'] = df_disp.apply(
                lambda row: f"{'+' if row['Min 수익률'] > 0 else ''}{row['Min 수익률']:.1f}% ({row['Min 날짜']})" 
                if pd.notna(row['Min 수익률']) and pd.notna(row['Min 날짜']) else '-',
                axis=1
            )
            df_disp.drop(columns=['Min 수익률', 'Min 날짜'], inplace=True)
        
        # 컬럼 순서 재정렬 (가독성 최적화)
        preferred_cols = [
            'Code', 'Name', '매수가', '현재가', 'B/C 라인', 'B/C 상승률', 
            '수익률/상태', 'Max 수익/날짜', 'Min 수익/날짜',
            '208주 최저', '208주 최고', '현재 구간', '20일선'
        ]
        
        # 존재하는 컬럼만 선택
        cols_to_show = [c for c in preferred_cols if c in df_disp.columns]
        df_disp = df_disp[cols_to_show]
        
        # 숫자 포맷팅
        # 가격 컬럼: 소수점 제거 (정수로 표시)
        price_cols = ['매수가', '현재가', 'B/C 라인', '208주 최저', '208주 최고']
        for col in price_cols:
            if col in df_disp.columns:
                df_disp[col] = df_disp[col].apply(lambda x: f"{int(x):,}" if pd.notna(x) else x)
        
        # 퍼센트 컬럼: 포맷팅
        if 'B/C 상승률' in df_disp.columns:
            df_disp['B/C 상승률'] = df_disp['B/C 상승률'].apply(lambda x: f"+{x:.1f}%" if x > 0 else f"{x:.1f}%")

        
        st.dataframe(df_disp, width='stretch')
        st.divider()
        scan_results = st.session_state['scan_results']
        sel_name = st.selectbox("종목 선택", [res['Name'] for res in scan_results], key="scan_sel")
        row_sel = next(res for res in scan_results if res['Name'] == sel_name)
        
        # 차트 데이터 준비
        df_chart = row_sel['df_daily'].copy()
        df_chart['MA20'] = df_chart['Close'].rolling(window=20).mean()
        
        fig = go.Figure()
        
        # 가격 라인
        fig.add_trace(go.Scatter(
            x=df_chart.index, 
            y=df_chart['Close'], 
            name='가격', 
            line=dict(color='#26a69a', width=2)
        ))
        
        # 20일 이동평균선
        fig.add_trace(go.Scatter(
            x=df_chart.index, 
            y=df_chart['MA20'], 
            name='20일선', 
            line=dict(color='#ff9800', width=1, dash='dot'),
            opacity=0.7
        ))
        
        # 매수 시점 표시 (검색 기준 날짜)
        scan_date_ts = pd.Timestamp(st.session_state.get('scan_date', datetime.now().date()))
        # 검색 날짜에 가장 가까운 실제 데이터 찾기
        valid_dates = df_chart[df_chart.index <= scan_date_ts].index
        if len(valid_dates) > 0:
            buy_date = valid_dates[-1]  # 검색일 이전 가장 최근 데이터
            buy_price = df_chart.loc[buy_date, 'Close']
            fig.add_trace(go.Scatter(
                x=[buy_date], 
                y=[buy_price],
                mode='markers+text',
                name='매수 시점',
                marker=dict(color='#00ff00', size=15, symbol='triangle-up'),
                text=['🟢 BUY'],
                textposition='top center',
                textfont=dict(size=14, color='#00ff00')
            ))
        
        # 매도 시점 표시 (매도된 경우만)
        if '상태' in row_sel and '매도' in row_sel['상태']:
            # 상태에서 날짜 추출: "매도 (2025-07-01)" -> "2025-07-01"
            import re
            match = re.search(r'\((\d{4}-\d{2}-\d{2})\)', row_sel['상태'])
            if match:
                sell_date_str = match.group(1)
                sell_date_ts = pd.Timestamp(sell_date_str)
                # 매도일에 가장 가까운 실제 데이터 찾기
                valid_sell_dates = df_chart[df_chart.index <= sell_date_ts].index
                if len(valid_sell_dates) > 0:
                    sell_date = valid_sell_dates[-1]
                    sell_price = df_chart.loc[sell_date, 'Close']
                    fig.add_trace(go.Scatter(
                        x=[sell_date],
                        y=[sell_price],
                        mode='markers+text',
                        name='매도 시점',
                        marker=dict(color='#ff0000', size=15, symbol='triangle-down'),
                        text=['🔴 SELL'],
                        textposition='bottom center',
                        textfont=dict(size=14, color='#ff0000')
                    ))
        
        # 6등분 경계선
        for i, level in enumerate(row_sel['segments']):
            fig.add_hline(y=level, line_dash="dash", line_color="rgba(200,200,200,0.2)")
        
        fig.update_layout(
            template="plotly_dark", 
            height=600, 
            paper_bgcolor="#131722", 
            plot_bgcolor="#131722",
            hovermode='x unified',
            showlegend=True
        )
        st.plotly_chart(fig, width='stretch')

with tab2:
    st.subheader("초고속 백테스팅")
    with st.expander("⚙️ 전략 설정", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            bt_brk = st.checkbox("B/C 돌파 필수", value=True)
            bt_ma = st.checkbox("20일선 위 필수", value=True)
            bt_seg = st.selectbox("진입 구간", ["Segment C (B/C~C/D)", "Segment B (A/B~B/C)"])
        with c2:
            bt_tgt = st.selectbox("목표 경계", ["D/E Boundary", "C/D Boundary", "E/F Boundary"])
            bt_met = st.radio("매도 방식", ["목표 도달 후 20일선 이탈", "목표가 도달 시 즉시 매도"])
            bt_sl = st.number_input("손절 (%)", value=0.0)
    
    with st.expander("📅 백테스트 기간 설정", expanded=False):
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            bt_start = st.date_input("시작일", value=datetime(2014, 1, 1))
        with col_d2:
            bt_end = st.date_input("종료일", value=datetime.now())
    
    with st.expander("📌 보유 포지션 처리", expanded=False):
        bt_force_liquidate = st.checkbox(
            "종료일 기준 강제 청산",
            value=False,
            help="체크: 보유 중인 포지션을 종료일 가격으로 강제 청산\n해제: 보유 중인 포지션을 '보유중'으로 표시"
        )

    if st.button("🚀 초고속 분석 시작"):
        stock_list = get_stock_list_naver(market_sel, n_stocks_sel)
        
        # [Smart Feature] 스크리너 결과 자동 포함 (순위 밖이라도 백테스트에 강제 포함)
        # [Smart Feature] 스크리너 결과 자동 포함 (순위 밖이라도 백테스트에 강제 포함)
        # 단, 현재 선택된 시장(market_sel)과 스크리너 실행 시장(scan_market)이 같을 때만 포함
        if 'scan_results' in st.session_state:
            scan_market = st.session_state.get('scan_market', None)
            
            if scan_market == market_sel:
                existing_codes = set(stock_list['Code'].values)
            new_rows = []
            
            for res in st.session_state['scan_results']:
                if res['Code'] not in existing_codes:
                    # 스크리너 데이터에서 현재가 추출 시도
                    last_price = 0
                    if 'df_daily' in res and len(res['df_daily']) > 0:
                         last_price = res['df_daily']['Close'].iloc[-1]
                    
                    new_rows.append({'Code': res['Code'], 'Name': res['Name'], '현재가': last_price})
            
            if new_rows:
                stock_list = pd.concat([stock_list, pd.DataFrame(new_rows)], ignore_index=True)
                st.toast(f"💡 스크리너 발견 종목 {len(new_rows)}개를 백테스트 목록에 자동 추가했습니다!")
        cfg = {
            'buy_breakout':bt_brk, 'buy_ma20':bt_ma, 'buy_segment':bt_seg, 
            'exit_target':bt_tgt, 'exit_method':bt_met, 'stop_loss_pct':bt_sl,
            'start_date': bt_start.strftime('%Y-%m-%d'),
            'end_date': bt_end.strftime('%Y-%m-%d'),
            'end_date': bt_end.strftime('%Y-%m-%d'),
            'force_liquidate': bt_force_liquidate,
            'lookback': lookback_sel,
            'bc_breakout_days': bc_breakout_days  # B/C 돌파 확인 기간
        }
        bt_results = []
        pb_bt = st.progress(0)
        with ThreadPoolExecutor(max_workers=4) as executor:
            # [Optimization] 스크리너에서 이미 받은 데이터 재사용 (scan_data_map 활용)
            # scan_data_map은 위 Smart Feature 블록에서 (혹은 여기서 새로) 생성 필요
            scan_data_map = {}
            if 'scan_results' in st.session_state:
                for res in st.session_state['scan_results']:
                    if 'df_daily' in res:
                        scan_data_map[res['Code']] = res['df_daily']

            future_to_bt = {
                executor.submit(process_backtest_stock, r['Code'], r['Name'], market_sel, cfg, r.to_dict(), scan_data_map.get(r['Code'])): r 
                for _, r in stock_list.iterrows()
            }
            for i, future in enumerate(as_completed(future_to_bt)):
                r_bt = future.result()
                if r_bt: bt_results.append(r_bt)
                pb_bt.progress((i+1)/len(future_to_bt))
        if bt_results:
            st.session_state['bt_results'] = bt_results
            # st.dataframe display moved to persistent block below

    if 'bt_results' in st.session_state:
        bt_res = st.session_state['bt_results']
        
        # [Moved] Summary Table Persisted Display
        st.subheader("📊 백테스팅 결과 요약")
        df_summary = pd.DataFrame(bt_res).drop(columns=['df_daily', 'trades'], errors='ignore')
        
        # 날짜 컬럼을 datetime 타입으로 변환 (정렬 기능 향상)
        if 'Recent Buy' in df_summary.columns:
            df_summary['Recent Buy'] = pd.to_datetime(df_summary['Recent Buy'], format='%Y-%m-%d', errors='coerce')
        # [FIX] Recent Sell은 '보유중', '신규' 등 텍스트가 섞여있으므로 datetime 변환 금지 (변환 시 NaT가 되어 로직 깨짐)
        
        # [Filter] 시뮬레이션 기간 내 매수 신호가 있는 종목만 표시
        # 사용자 설정 기간(bt_start ~ bt_end) 이전 매수는 무시하고, 기간 내 신호만 보여줌
        start_date_filter = pd.Timestamp(bt_start)  # Streamlit date -> pandas Timestamp 변환
        mask_recent_activity = (
            (df_summary['Recent Buy'] >= start_date_filter) |  # 기간 내 매수
            (df_summary['Recent Sell'] == '🆕 신규')  # 또는 신규 신호
        )
        df_summary = df_summary[mask_recent_activity].copy()

        # 정렬 순서: 1. 신규 매수, 2. 최근 매수일
        df_summary['_is_new'] = df_summary['Recent Sell'] == '🆕 신규'
        df_summary = df_summary.sort_values(
            by=['_is_new', 'Recent Buy'], 
            ascending=[False, False]
        )
        df_summary.drop(columns=['_is_new'], inplace=True)
        
        # 정렬 후 인덱스 재설정
        df_summary = df_summary.reset_index(drop=True)
        
        # 맨 앞에 명시적인 행 번호 컬럼 추가
        df_summary.insert(0, '#', range(len(df_summary)))
        
        # [가독성 개선] Recent Buy 날짜 포맷 (날짜만 표시 + 가격 추가)
        if 'Recent Buy' in df_summary.columns and 'Recent Buy Price' in df_summary.columns:
            df_summary['Recent Buy'] = df_summary.apply(
                lambda row: f"{row['Recent Buy'].strftime('%Y-%m-%d')} ({int(row['Recent Buy Price']):,})" 
                if pd.notna(row['Recent Buy']) and isinstance(row['Recent Buy'], pd.Timestamp) and pd.notna(row['Recent Buy Price'])
                else str(row['Recent Buy']),
                axis=1
            )
        
        # [가독성 개선] Recent Sell 가격 추가 (보유중/신규 포함)
        if 'Recent Sell' in df_summary.columns and 'Recent Sell Price' in df_summary.columns:
            df_summary['Recent Sell'] = df_summary.apply(
                lambda row: f"{row['Recent Sell']} ({int(row['Recent Sell Price']):,})" 
                if pd.notna(row['Recent Sell']) and pd.notna(row['Recent Sell Price'])
                else str(row['Recent Sell']),
                axis=1
            )
        
        # [가독성 개선] 불필요한 컬럼 제거
        cols_to_drop = ['is_core_buy', 'is_new_signal', 'DebugInfo', 'Log', 'Recent Buy Price', 'Recent Sell Price']
        df_summary.drop(columns=cols_to_drop, errors='ignore', inplace=True)
        
        # [가독성 개선] 수익률 컬럼 포맷팅 (소수점 첫째자리까지)
        pnl_cols = ['Total PnL (%)', 'Win Rate (%)', 'Current PnL (%)']
        for col in pnl_cols:
            if col in df_summary.columns:
                df_summary[col] = df_summary[col].apply(
                    lambda x: f"{x:.1f}" if pd.notna(x) else '-'
                )
        
        # 컬럼 순서 재배치 (Current PnL을 Name 옆으로)
        cols = ['#', 'Ticker', 'Name', 'Current PnL (%)', 'Total PnL (%)', 'Trades', 'Win Rate (%)', 'Recent Buy', 'Recent Sell']
        # 나머지 컬럼들 뒤에 붙이기
        existing_cols = df_summary.columns.tolist()
        final_cols = [c for c in cols if c in existing_cols] + [c for c in existing_cols if c not in cols]
        df_summary = df_summary[final_cols]
        
        # 테이블 표시 (정렬 가능, DataFrame 인덱스는 숨김)
        st.dataframe(df_summary, width='stretch', hide_index=True)
        
        st.divider()
        
        # 종목명 검색으로 선택 (개선된 UX)
        st.caption("💡 **종목 선택:** 아래에서 종목명을 검색하거나 선택하세요.")
        
        # 종목명 리스트 생성 (테이블 순서와 동일)
        stock_options = [f"#{row['#']} - {row['Name']} (Ticker: {row['Ticker']}, PnL: {row['Total PnL (%)']}%)" 
                        for _, row in df_summary.iterrows()]
        
        # 기본값: 이전 선택 유지
        default_index = st.session_state.get('selected_stock_index', 0)
        if default_index >= len(stock_options):
            default_index = 0
        
        # 종목 선택 (검색 가능한 selectbox)
        selected_option = st.selectbox(
            "종목 검색/선택",
            options=stock_options,
            index=default_index,
            key="stock_selector",
            help="종목명, 티커, 행번호로 검색 가능합니다."
        )
        
        # 선택된 옵션에서 행번호 추출
        selected_row = int(selected_option.split('#')[1].split(' - ')[0])
        
        # 선택된 종목 정보 저장
        st.session_state['selected_stock_index'] = selected_row
        sel_bt = df_summary.iloc[selected_row]['Name']
        
        row_bt = next(r for r in bt_res if r['Name'] == sel_bt)
        st.subheader("📍 매매 상세 분석 (Transaction Details)")
        
        # 1. 전체 차트 (Global View)
        fig_global = go.Figure()
        if row_bt['df_daily'] is not None:
            fig_global.add_trace(go.Scatter(x=row_bt['df_daily'].index, y=row_bt['df_daily']['Close'], name='Price', line=dict(color='#d1d4dc', width=1)))
        for t in row_bt['trades']:
            color = "#26a69a" if t['pnl'] > 0 else "#ef5350"
            fig_global.add_vrect(x0=t['entry_date'], x1=t['exit_date'], fillcolor=color, opacity=0.1, layer="below", line_width=0)
        fig_global.update_layout(title=f"{sel_bt} 전체 흐름", height=300, template="plotly_dark", paper_bgcolor="#131722", plot_bgcolor="#131722")
        st.plotly_chart(fig_global, width='stretch')

        # 2. 개별 매매 상세 차트 (Zoomed View)
        for idx, t in enumerate(row_bt['trades']):
            st.divider()
            
            # 신규 매수 신호 여부 확인
            is_new_signal = t.get('is_new_signal', False)
            is_open_position = t['exit_date'] is None and not is_new_signal
            
            if is_new_signal:
                status_text = "🆕 신규"
            elif is_open_position:
                status_text = "보유중"
            else:
                status_text = f"{t['pnl']:.2f}%"
            
            st.markdown(f"#### 🎯 Trade #{idx+1} 수익률: :{'blue' if t['pnl']>0 else 'red'}[{status_text}]")
            
            # 줌 범위 설정 (진입 3개월 전 ~ 청산/현재 1개월 후)
            zoom_start = t['entry_date'] - timedelta(weeks=12)
            if is_open_position or is_new_signal:
                # 보유중인 경우 현재 날짜 기준
                zoom_end = row_bt['df_daily'].index[-1] + timedelta(weeks=4)
            else:
                zoom_end = t['exit_date'] + timedelta(weeks=4)
            
            df_zoom = row_bt['df_daily'][(row_bt['df_daily'].index >= zoom_start) & (row_bt['df_daily'].index <= zoom_end)].copy()
            
            if df_zoom.empty: continue
            
            fig = go.Figure()
            
            # 세그먼트 가로선 그리기
            labels_seg = ['L', 'A/B', 'B/C', 'C/D', 'D/E', 'E/F', 'H']
            for i, level in enumerate(t['segments']):
                # 주요 라인(B/C, D/E)은 진하게 표시
                is_key_level = labels_seg[i] in ['B/C', 'D/E']
                opacity = 0.4 if is_key_level else 0.15
                width = 2 if is_key_level else 1
                dash = "solid" if is_key_level else "dash"
                fig.add_hline(y=level, line_dash=dash, line_width=width, line_color=f'rgba(255,255,255,{opacity})', annotation_text=labels_seg[i])
            
            # 주가 그리기
            fig.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['Close'], name='Price', line=dict(color='#26a69a', width=2)))
            
            # 20일 이동평균선 추가 (매수 조건 확인용)
            if 'MA20' in df_zoom.columns:
                fig.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['MA20'], name='MA20', line=dict(color='#ffa726', width=1, dash='dot')))
            
            # 매수/매도 마커
            fig.add_annotation(x=t['entry_date'], y=t['entry_price'], text="▲ BUY", showarrow=True, arrowhead=2, arrowwidth=2, arrowcolor="#42a5f5", ax=0, ay=30, font=dict(color="#42a5f5", size=12))
            
            if is_new_signal:
                # 신규 매수 신호인 경우
                fig.add_annotation(x=df_zoom.index[-1], y=t['exit_price'], text=f"🆕 신규 매수 신호", showarrow=True, arrowhead=2, arrowwidth=2, arrowcolor="#4caf50", ax=0, ay=-30, font=dict(color="#4caf50", size=12))
                title_text = f"Trade #{idx+1} 상세 (진입 예정: {t['entry_date'].date()} - 🆕 신규)"
            elif is_open_position:
                # 보유중인 경우
                fig.add_annotation(x=df_zoom.index[-1], y=t['exit_price'], text=f"💼 보유중 ({t['pnl']:.1f}%)", showarrow=True, arrowhead=2, arrowwidth=2, arrowcolor="#ffa726", ax=0, ay=-30, font=dict(color="#ffa726", size=12))
                title_text = f"Trade #{idx+1} 상세 (진입: {t['entry_date'].date()} -> 보유중)"
            else:
                fig.add_annotation(x=t['exit_date'], y=t['exit_price'], text=f"▼ SELL ({t['pnl']:.1f}%)", showarrow=True, arrowhead=2, arrowwidth=2, arrowcolor="#ef5350", ax=0, ay=-30, font=dict(color="#ef5350", size=12))
                title_text = f"Trade #{idx+1} 상세 (진입: {t['entry_date'].date()} -> 청산: {t['exit_date'].date()})"

            fig.update_layout(title=title_text, height=450, template="plotly_dark", paper_bgcolor="#131722", plot_bgcolor="#131722")
            st.plotly_chart(fig, width='stretch')
            
        st.write("📋 매매 기록 테이블")
        if row_bt['trades']:
            df_trades = pd.DataFrame(row_bt['trades'])
            # segments 컬럼이 있으면 제거
            if 'segments' in df_trades.columns:
                df_trades = df_trades.drop(columns=['segments'])
            st.table(df_trades)
        else:
            st.info("매매 기록이 없습니다.")
