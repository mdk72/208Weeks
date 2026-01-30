import pandas as pd
import numpy as np
from datetime import datetime
from data_loader import fetch_data

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
        # print(f"Performance calc error: {e}")
        return None

def analyze_stock_core(ticker, name, df, lookback_weeks=208, bc_breakout_days=60):
    """핵심 분석 로직: 208주 6등분 및 전략 조건 확인"""
    try:
        if df is None or len(df) < lookback_weeks: return None
        df = df.copy() # [FIX] Ensure we are working on a copy to avoid SettingWithCopyWarning
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
        
        # Condition 1: Current Price in Segment C (B/C < Price <= C/D)
        bc_line = segments[2]
        cd_line = segments[3]
        
        if not (bc_line < current_price <= cd_line):
            return None 
            
        curr_seg = "Segment C"
        
        # Condition 2: Golden Cross over B/C line within last N days
        recent_low = df['Low'].tail(bc_breakout_days).min()
        if recent_low >= bc_line:
            return None 
        
        # Condition 2-2: B/C 라인 근처만 선택 (5% 이내)
        max_rise_from_bc = 0.05
        if current_price > bc_line * (1 + max_rise_from_bc):
            return None
        
        # Condition 3: Above 20MA
        # [Optimized] Calculate MA20 for the entire dataframe to return it for charting
        df['MA20'] = df['Close'].rolling(window=20).mean()
        curr_ma20 = float(df['MA20'].iloc[-1])
        
        if current_price < curr_ma20:
             return None
        
        ma_status = "O (Above)"
        
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

def process_backtest_stock(ticker, name, market, config, current_row=None, pre_fetched_df=None, scan_date=None):
    """백테스팅 개별 종목 처리"""
    from_cache_overall = False
    try:
        if pre_fetched_df is not None:
            df_daily = pre_fetched_df.copy()
            from_cache_overall = True
        else:
            # config['start_date']와 lookback을 고려하여 충분한 기간의 데이터를 요청
            bt_start_val = config.get('start_date', '2020-01-01')
            lookback_val = config.get('lookback', 208)
            dt_start = pd.to_datetime(bt_start_val)
            # 안전하게 충분한 기간 확보 (2배)
            fetch_start_bt = (dt_start - pd.Timedelta(weeks=int(lookback_val * 2))).strftime('%Y-%m-%d')

            result = fetch_data(ticker, market, start_date=fetch_start_bt, scan_date=scan_date)
            if result is None:
                df_daily = None
            else:
                df_daily, from_cache_overall = result 
            
        if df_daily is None:
             return {'Ticker': ticker, 'Name': name, 'status': 'excluded_no_data'}

        lookback_days = config.get('lookback', 208)
        if len(df_daily) < lookback_days:
             return {'Ticker': ticker, 'Name': name, 'status': 'excluded_short_history'}
        
        # 실시간 데이터 반영 (캐시된 데이터가 오늘짜가 아닐 경우 또는 업데이트)
        if current_row is not None:
            last_date = df_daily.index[-1]
            # Timezone aware comparison handling
            import pytz
            kst = pytz.timezone('Asia/Seoul')
            today_date = datetime.now(kst).date()
            
            curr_price = float(current_row.get('현재가', 0))
            
            if curr_price > 0:
                if last_date.date() < today_date:
                    try:
                        new_idx = pd.Timestamp(today_date)
                        new_row = pd.DataFrame({
                            'Open': [curr_price], 'High': [curr_price], 'Low': [curr_price], 'Close': [curr_price], 'Volume': [0]
                        }, index=[new_idx])
                        df_daily = pd.concat([df_daily, new_row])
                    except: pass
                elif last_date.date() == today_date:
                    try:
                        df_daily.at[last_date, 'Close'] = curr_price
                        if curr_price > df_daily.at[last_date, 'High']: df_daily.at[last_date, 'High'] = curr_price
                        if curr_price < df_daily.at[last_date, 'Low']: df_daily.at[last_date, 'Low'] = curr_price
                    except: pass
            
        buy_breakout = config['buy_breakout']
        buy_ma20 = config['buy_ma20']
        buy_segment = config['buy_segment']
        exit_target = config['exit_target']
        exit_method = config['exit_method']
        stop_loss_pct = config['stop_loss_pct']
        start_date = config.get('start_date', '2020-01-01')
        end_date = config.get('end_date', None)
        force_liquidate = config.get('force_liquidate', False)
        bc_breakout_days = config.get('bc_breakout_days', 60)
        
        df_daily = df_daily.copy()
        df_daily['MA20'] = df_daily['Close'].rolling(window=20).mean()
        
        df_weekly = df_daily.resample('W').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'})
        df_weekly['Low208'] = df_weekly['Low'].rolling(window=208, min_periods=208).min()
        df_weekly['High208'] = df_weekly['High'].rolling(window=208, min_periods=208).max()
        
        # 주봉 데이터를 일별로 매핑
        df_daily['Week'] = df_daily.index.to_period('W')
        df_weekly['Week'] = df_weekly.index.to_period('W')
        weekly_map = df_weekly[['Week', 'Low208', 'High208']].set_index('Week')
        
        # join시 중복 컬럼 방지를 위해 suffixes 사용 안함 (이미 원본엔 없음)
        df_daily = df_daily.join(weekly_map, on='Week')
        df_daily = df_daily.drop(columns=['Week'])
        df_daily = df_daily.rename(columns={'Low208': 'RollLow', 'High208': 'RollHigh'})
        
        trades = []
        position = None
        target_hit = False
        
        # 시뮬레이션 기간 필터링
        df_test = df_daily[df_daily.index >= pd.Timestamp(start_date)].copy()
        if end_date:
            df_test = df_test[df_test.index <= pd.Timestamp(end_date)]
        
        # [Analysis] 데이터가 시뮬레이션 종료일까지 존재하는지 확인
        is_delisted = False
        if end_date and not df_test.empty:
            bt_end_ts = pd.Timestamp(end_date)
            final_date = df_test.index[-1]
            # 마지막 데이터가 백테스트 종료일보다 7일 이상 전이면 상장폐지로 추정
            if (bt_end_ts - final_date).days > 7:
                is_delisted = True
        
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
                    # [FIX] Look back in df_daily instead of df_test to catch breakouts before start_date
                    idx_in_daily = df_daily.index.get_loc(curr_date)
                    was_below = float(df_daily['Low'].iloc[max(0, idx_in_daily-bc_breakout_days):idx_in_daily].min()) <= bnd
                    if not was_below: is_buy = False
                
                if is_buy and buy_segment == "Segment C (B/C~C/D)":
                    bc_line = bounds[2]
                    if curr_price > bc_line * 1.05: is_buy = False
                    
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
        
        # 보유 중 포지션 처리
        if position is not None:
            final_date = df_test.index[-1]
            final_price = float(df_test['Close'].iloc[-1])
            
            if force_liquidate or is_delisted:
                trades.append({
                    'entry_date': position['entry_date'], 'entry_price': position['entry_price'],
                    'exit_date': final_date, 'exit_price': final_price,
                    'pnl': (final_price / position['entry_price'] - 1) * 100,
                    'duration': (final_date - position['entry_date']).days,
                    'segments': position['segments'],
                    'is_delisted': is_delisted
                })
            else:
                trades.append({
                    'entry_date': position['entry_date'], 'entry_price': position['entry_price'],
                    'exit_date': None,
                    'exit_price': final_price,
                    'pnl': (final_price / position['entry_price'] - 1) * 100,
                    'duration': (final_date - position['entry_date']).days,
                    'segments': position['segments']
                })

        # 종료일 기준 신규 매수 신호 체크 (시그널 헌팅)
        if position is None and len(df_test) > 0 and not is_delisted:
            last_idx = len(df_test) - 1
            low_208 = df_test['RollLow'].iloc[last_idx]
            high_208 = df_test['RollHigh'].iloc[last_idx]
            
            if not pd.isna(low_208) and (high_208 - low_208) > 0:
                curr_date = df_test.index[last_idx]
                curr_price = float(df_test['Close'].iloc[last_idx])
                ma20 = float(df_test['MA20'].iloc[last_idx])
                step = (high_208 - low_208) / 6
                bounds = [low_208 + j*step for j in range(7)]
                
                is_buy = True
                if buy_segment == "Segment B (A/B~B/C)":
                    if not (bounds[1] < curr_price <= bounds[2]): is_buy = False
                else: 
                    if not (bounds[2] < curr_price <= bounds[3]): is_buy = False
                
                if is_buy and buy_breakout:
                    bnd = bounds[2] if buy_segment == "Segment C (B/C~C/D)" else bounds[1]
                    # [FIX] Look back in df_daily instead of df_test for consistency
                    idx_in_daily = df_daily.index.get_loc(curr_date)
                    was_below = float(df_daily['Low'].iloc[max(0, idx_in_daily-bc_breakout_days):idx_in_daily].min()) <= bnd
                    if not was_below: is_buy = False
                
                if is_buy and buy_segment == "Segment C (B/C~C/D)":
                    bc_line = bounds[2]
                    if curr_price > bc_line * 1.05: is_buy = False
                    
                if is_buy and buy_ma20 and curr_price < ma20: is_buy = False
                
                if is_buy:
                    trades.append({
                        'entry_date': curr_date, 'entry_price': curr_price,
                        'exit_date': None, 'exit_price': curr_price,
                        'pnl': 0.0, 'duration': 0,
                        'segments': bounds, 'is_new_signal': True
                    })

        # 검증 로직 (analyze_stock_core 사용) - delisted된 종목은 제외
        if not is_delisted:
            try:
                end_date_ts = pd.Timestamp(config.get('end_date'))
                df_for_core = df_daily[df_daily.index <= end_date_ts].copy()
                core_res = analyze_stock_core(ticker, name, df_for_core, config.get('lookback', 208), bc_breakout_days)
                
                if core_res:
                    has_new_signal = any(t.get('is_new_signal') for t in trades)
                    if not has_new_signal:
                        if position is None:
                            trades.append({
                                'entry_date': df_for_core.index[-1],
                                'entry_price': float(df_for_core['Close'].iloc[-1]),
                                'exit_date': None, 'exit_price': float(df_for_core['Close'].iloc[-1]),
                                'pnl': 0.0, 'duration': 0,
                                'segments': core_res['segments'],
                                'is_new_signal': True
                            })
            except: pass
                    
        if trades:
            last_trade = trades[-1]
            if last_trade['exit_date'] is None or last_trade.get('is_new_signal', False):
                last_buy = last_trade['entry_date'].strftime('%Y-%m-%d')
            else:
                held_trades = [t for t in trades if t['exit_date'] is None]
                if held_trades:
                    last_buy = held_trades[-1]['entry_date'].strftime('%Y-%m-%d')
                else:
                    last_buy = last_trade['entry_date'].strftime('%Y-%m-%d')
            
            pnl_val = trades[-1]['pnl'] if (trades[-1]['exit_date'] is None or trades[-1].get('is_new_signal', False)) else None
            
            if trades[-1].get('is_new_signal', False): last_sell = 'New'
            elif trades[-1].get('is_delisted', False): last_sell = f"상장폐지 ({trades[-1]['exit_date'].strftime('%Y-%m-%d')})"
            elif trades[-1]['exit_date'] is None: last_sell = '보유중'
            else: last_sell = trades[-1]['exit_date'].strftime('%Y-%m-%d')
            
            # Max/Min Calculate
            recent_entry_date = last_trade['entry_date']
            recent_entry_price = last_trade['entry_price']
            recent_exit_date = last_trade['exit_date']
            
            df_after_entry = df_daily[df_daily.index >= recent_entry_date]
            if pd.notna(recent_exit_date):
                 df_after_entry = df_after_entry[df_after_entry.index <= recent_exit_date]
            
            if len(df_after_entry) > 0:
                df_after_entry_copy = df_after_entry.copy()
                df_after_entry_copy['pnl_pct'] = (df_after_entry_copy['Close'] / recent_entry_price - 1) * 100
                max_pnl = df_after_entry_copy['pnl_pct'].max()
                max_pnl_date = df_after_entry_copy['pnl_pct'].idxmax().strftime('%Y-%m-%d')
                min_pnl = df_after_entry_copy['pnl_pct'].min()
                min_pnl_date = df_after_entry_copy['pnl_pct'].idxmin().strftime('%Y-%m-%d')
            else:
                max_pnl = 0.0; max_pnl_date = recent_entry_date.strftime('%Y-%m-%d')
                min_pnl = 0.0; min_pnl_date = recent_entry_date.strftime('%Y-%m-%d')
            
            return {
                'Ticker': ticker, 'Name': name, 
                'Recent Buy Price': last_trade['entry_price'],
                'Recent Sell Price': last_trade['exit_price'],
                'Current PnL (%)': pnl_val,
                'Max 수익률': max_pnl, 'Max 날짜': max_pnl_date,
                'Min 수익률': min_pnl, 'Min 날짜': min_pnl_date,
                'Total PnL (%)': sum(t['pnl'] for t in trades),
                'Trades': len(trades), 
                'Win Rate (%)': (len([t for t in trades if t['pnl'] > 0]) / len(trades)) * 100 if trades else 0,
                'Recent Buy': last_buy, 'Recent Sell': last_sell,
                'Duration': last_trade['duration'],
                'df_daily': df_daily, 'trades': trades,
                'from_cache': from_cache_overall,
                'status': 'active' if not is_delisted else 'delisted'
            }
    except:
        return {
            'Ticker': ticker, 'Name': name, 'Total PnL (%)': 0.0,
            'Trades': 0, 'Win Rate (%)': 0.0,
            'Recent Buy': '-', 'Recent Sell': '-',
            'Current PnL (%)': None,
            'df_daily': None, 'trades': [],
             'status': 'error'
        }
    return {'Ticker': ticker, 'Name': name, 'status': 'no_trades'}
