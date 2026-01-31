from datetime import datetime
import pandas as pd
import numpy as np
import pytz
import sys
import os

# root path for relative imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.loader import fetch_data
from strategies.reversal_208 import analyze_stock_core

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
             return {'Ticker': ticker, 'Name': name, 'status': 'excluded_no_data', 'exit_reason': '-', 'from_cache': from_cache_overall}

        lookback_days = config.get('lookback', 208)
        if len(df_daily) < lookback_days:
             return {'Ticker': ticker, 'Name': name, 'status': 'excluded_short_history', 'exit_reason': '-', 'from_cache': from_cache_overall}
        
        # 실시간 데이터 반영 (캐시된 데이터가 오늘짜가 아닐 경우 또는 업데이트)
        if current_row is not None:
            last_date = df_daily.index[-1]
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
            
        buy_breakout = config.get('buy_breakout', True)
        buy_ma20 = config.get('buy_ma20', True)
        buy_segment = config.get('buy_segment', "Segment C (B/C~C/D)")
        exit_target = config.get('exit_target', "D/E Boundary")
        exit_method = config.get('exit_method', "목표 도달 후 20일선 이탈")
        stop_loss_pct = float(config.get('stop_loss_pct', 0.0))
        start_date = config.get('start_date', '2023-01-02')
        end_date = config.get('end_date', None)
        force_liquidate = config.get('force_liquidate', False)
        bc_breakout_days = int(config.get('bc_breakout_days', 60))
        max_holding_months = int(config.get('max_holding_months', 0))
        defense_trailing_pct = float(config.get('defense_trailing_pct', 0.0))
        profit_trailing_pct = float(config.get('profit_trailing_pct', 0.0))
        bc_exit_days = int(config.get('bc_exit_days', 0))
        cooldown_days = int(config.get('cooldown_days', 0))
        
        df_daily = df_daily.copy()
        
        # [ROBUST] Remove potential duplicates in index and ensure naive timestamps
        df_daily = df_daily[~df_daily.index.duplicated(keep='last')]
        if df_daily.index.tz is not None:
            df_daily.index = df_daily.index.tz_localize(None)
            
        df_daily['MA20'] = df_daily['Close'].rolling(window=20).mean()
        
        # 주봉 기반 208주 경계선 계산 (Rolling Boundary)
        df_weekly = df_daily.resample('W').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'})
        df_weekly['Low208'] = df_weekly['Low'].rolling(window=208, min_periods=1).min()
        df_weekly['High208'] = df_weekly['High'].rolling(window=208, min_periods=1).max()
        
        # 주봉 데이터를 일별로 매핑
        df_daily['Week'] = df_daily.index.to_period('W')
        df_weekly['Week'] = df_weekly.index.to_period('W')
        # Ensure unique week indices for mapping
        weekly_map = df_weekly[['Week', 'Low208', 'High208']].copy()
        weekly_map = weekly_map[~weekly_map['Week'].duplicated(keep='last')].set_index('Week')
        
        df_daily = df_daily.join(weekly_map, on='Week')
        df_daily = df_daily.drop(columns=['Week'])
        df_daily = df_daily.rename(columns={'Low208': 'RollLow', 'High208': 'RollHigh'})
        
        trades = []
        position = None
        target_hit = False
        max_price_since_entry = 0.0
        max_price_since_target_hit = 0.0
        below_bc_days_counter = 0
        last_exit_date = None
        
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
                # [V3] Cooldown Check Gate (First Gate)
                if cooldown_days > 0 and last_exit_date is not None:
                    c_ts = pd.Timestamp(curr_date).floor('D')
                    l_ts = pd.Timestamp(last_exit_date).floor('D')
                    if (c_ts - l_ts) < pd.Timedelta(days=cooldown_days):
                        continue # Skip this day entirely if in cooldown
                
                is_buy = True
                if buy_segment == "Segment B (A/B~B/C)":
                    if not (bounds[1] < curr_price <= bounds[2]): 
                        is_buy = False
                else: # Segment C
                    if not (bounds[2] < curr_price <= bounds[3]): 
                        is_buy = False
                    
                if is_buy and buy_breakout:
                    bnd = bounds[2] if buy_segment == "Segment C (B/C~C/D)" else bounds[1]
                    idx_in_daily = df_daily.index.get_loc(curr_date)
                    # [ROBUST] Handle slice/array if duplicate dates exist
                    if not isinstance(idx_in_daily, int):
                        idx_in_daily = idx_in_daily.start if hasattr(idx_in_daily, 'start') else idx_in_daily[0]
                    
                    if idx_in_daily > 0:
                        lookback_start = max(0, idx_in_daily - bc_breakout_days)
                        prev_low = float(df_daily['Low'].iloc[lookback_start:idx_in_daily].min())
                        if prev_low > bnd: is_buy = False
                
                # Segment C Only: Price must be within 5% of B/C boundary
                if is_buy and buy_segment == "Segment C (B/C~C/D)":
                    if curr_price > bounds[2] * 1.05: 
                        is_buy = False
                    
                if is_buy and buy_ma20 and (pd.isna(ma20) or curr_price < ma20): 
                    is_buy = False

                # Volume Breakout Confirmation
                if is_buy and config.get('volume_filter', False):
                    # Check if current day volume is 1.5x higher than 20-day average
                    idx_in_daily_vol = df_daily.index.get_loc(curr_date)
                    if not isinstance(idx_in_daily_vol, int):
                        idx_in_daily_vol = idx_in_daily_vol.start if hasattr(idx_in_daily_vol, 'start') else idx_in_daily_vol[0]
                    
                    if idx_in_daily_vol >= 20:  # Need at least 20 days for average
                        lookback_start_vol = max(0, idx_in_daily_vol - 20)
                        avg_volume = float(df_daily['Volume'].iloc[lookback_start_vol:idx_in_daily_vol].mean())
                        curr_volume = float(df_daily['Volume'].iloc[idx_in_daily_vol])
                        
                        if curr_volume < avg_volume * 1.5:
                            is_buy = False

                if is_buy:
                    position = {'entry_date': curr_date, 'entry_price': curr_price, 'segments': bounds}
                    target_hit = False
                    max_price_since_entry = curr_price
                    below_bc_days_counter = 0
            else:
                sell_sig = False
                if curr_price >= target_boundary: 
                    if not target_hit:
                        target_hit = True
                        max_price_since_target_hit = curr_price
                
                if target_hit:
                    if curr_price > max_price_since_target_hit:
                        max_price_since_target_hit = curr_price

                if exit_method == "목표가 도달 시 즉시 매도":
                    if target_hit: 
                        sell_sig = True
                        position['exit_reason'] = '목표달성 즉시매도'
                elif exit_method == "목표가 도달 후 트레일링스탑":
                    if target_hit and profit_trailing_pct > 0:
                        # [FIXED] PnL-based trailing stop instead of price-based
                        # Calculate max PnL and current PnL
                        max_pnl = (max_price_since_target_hit / position['entry_price'] - 1) * 100
                        curr_pnl = (curr_price / position['entry_price'] - 1) * 100
                        
                        # Trigger if current PnL drops below max PnL * (1 - T/S%)
                        # Example: Max 143%, T/S 10% → Sell if below 128.7%
                        if curr_pnl < max_pnl * (1 - profit_trailing_pct / 100):
                            sell_sig = True
                            position['exit_reason'] = '목표달성 T/S'
                else: # "목표 도달 후 20일선 이탈"
                    if target_hit and curr_price < ma20: 
                        sell_sig = True
                        position['exit_reason'] = '목표달성 20일선 하향'
                
                # 1. 고정 % 손절
                if not sell_sig and stop_loss_pct > 0:
                    if curr_price < position['entry_price'] * (1 - stop_loss_pct / 100): 
                        sell_sig = True
                        position['exit_reason'] = '손절(고정)'

                # 2. 최대 보유 기간 손절 (Time Stop)
                if not sell_sig and max_holding_months > 0:
                    holding_days = (curr_date - position['entry_date']).days
                    if holding_days >= max_holding_months * 30:
                        sell_sig = True
                        position['exit_reason'] = '기간만료'

                # 3. 방어용 트레일링 스톱 (Defense Trailing Stop)
                # 매수 시점부터 작동하며 고점 대비 하락 시 원금 보호 매도
                if not sell_sig and defense_trailing_pct > 0:
                    if curr_price > max_price_since_entry:
                        max_price_since_entry = curr_price
                    
                    # [FIXED] PnL-based defense trailing stop
                    max_pnl_since_entry = (max_price_since_entry / position['entry_price'] - 1) * 100
                    curr_pnl = (curr_price / position['entry_price'] - 1) * 100
                    
                    if curr_pnl < max_pnl_since_entry * (1 - defense_trailing_pct / 100):
                        sell_sig = True
                        position['exit_reason'] = '트레일링스톱'

                # 4. B/C 라인 이탈 매도 (BC Threshold Stop)
                if not sell_sig and bc_exit_days > 0:
                    bc_line = position['segments'][2]
                    if curr_price < bc_line:
                        below_bc_days_counter += 1
                    else:
                        below_bc_days_counter = 0 # 회복 시 리셋
                    
                    if below_bc_days_counter >= bc_exit_days:
                        sell_sig = True
                        position['exit_reason'] = '구간이탈'
                
                if sell_sig:
                    trades.append({
                        'entry_date': position['entry_date'], 'entry_price': position['entry_price'],
                        'exit_date': curr_date, 'exit_price': curr_price,
                        'pnl': (curr_price / position['entry_price'] - 1) * 100,
                        'duration': (curr_date - position['entry_date']).days,
                        'segments': position['segments'],
                        'exit_reason': position.get('exit_reason', '목표도달' if target_hit else '기타')
                    })
                    last_exit_date = curr_date
                    position = None
                    target_hit = False
        
        # --- 루프 종료 후 뒷정리 ---
        if position is not None:
            final_idx = len(df_test) - 1
            final_date = df_test.index[final_idx]
            final_price = float(df_test['Close'].iloc[final_idx])
            
            # 신규 시그널 여부: 마지막 날 매수한 경우
            is_new_signal = (final_date == position['entry_date'])

            if force_liquidate or is_delisted:
                trades.append({
                    'entry_date': position['entry_date'], 'entry_price': position['entry_price'],
                    'exit_date': final_date, 'exit_price': final_price,
                    'pnl': (final_price / position['entry_price'] - 1) * 100,
                    'duration': (final_date - position['entry_date']).days,
                    'segments': position['segments'],
                    'exit_reason': '보유중(강제)' if not is_delisted else '상장폐지',
                    'is_delisted': is_delisted
                })
                last_exit_date = final_date 
            else:
                trades.append({
                    'entry_date': position['entry_date'], 'entry_price': position['entry_price'],
                    'exit_date': None, 'exit_price': final_price,
                    'pnl': (final_price / position['entry_price'] - 1) * 100,
                    'duration': (final_date - position['entry_date']).days,
                    'segments': position['segments'],
                    'exit_reason': '보유중',
                    'is_new_signal': is_new_signal
                })
        
        # [SIGNAL HUNTING] If no active position, check if currently meeting Buy criteria
        if position is None and not is_delisted:
            try:
                # Use current state of df_daily up to end_ts
                end_ts = pd.Timestamp(config.get('end_date', datetime.now().strftime('%Y-%m-%d'))).floor('D')
                df_for_hunt = df_daily[df_daily.index <= end_ts].copy()
                if not df_for_hunt.empty:
                    # Logic is consistent with backtest loop
                    curr_date = df_for_hunt.index[-1]
                    curr_price = float(df_for_hunt['Close'].iloc[-1])
                    ma20_curr = float(df_for_hunt['MA20'].iloc[-1]) if 'MA20' in df_for_hunt.columns else None
                    if ma20_curr is None:
                        ma20_curr = float(df_for_hunt['Close'].rolling(window=20).mean().iloc[-1])
                    
                    low_208_curr = df_for_hunt['RollLow'].iloc[-1]
                    high_208_curr = df_for_hunt['RollHigh'].iloc[-1]
                    
                    if not pd.isna(low_208_curr) and high_208_curr > low_208_curr:
                        st_val = (high_208_curr - low_208_curr) / 6
                        bnds = [low_208_curr + j*st_val for j in range(7)]
                        
                        is_buy_now = True
                        if buy_segment == "Segment B (A/B~B/C)":
                            if not (bnds[1] < curr_price <= bnds[2]): is_buy_now = False
                        else: # Segment C
                            if not (bnds[2] < curr_price <= bnds[3]): is_buy_now = False
                        
                        if is_buy_now and buy_ma20 and (pd.isna(ma20_curr) or curr_price < ma20_curr):
                            is_buy_now = False
                            
                        # Breakout check
                        if is_buy_now and buy_breakout:
                            bnd_line = bnds[2] if buy_segment == "Segment C (B/C~C/D)" else bnds[1]
                            idx_now = df_for_hunt.index.get_loc(curr_date)
                            if not isinstance(idx_now, int):
                                idx_now = idx_now.start if hasattr(idx_now, 'start') else idx_now[0]
                            
                            if idx_now > 0:
                                lookback_st = max(0, idx_now - bc_breakout_days)
                                prev_l = float(df_for_hunt['Low'].iloc[lookback_st:idx_now].min())
                                if prev_l > bnd_line: is_buy_now = False
                        
                        # Segment C specific 5% limit
                        if is_buy_now and buy_segment == "Segment C (B/C~C/D)":
                            if curr_price > bnds[2] * 1.05: is_buy_now = False

                        if is_buy_now:
                            # Check cooldown
                            can_buy_now = True
                            if cooldown_days > 0 and last_exit_date is not None:
                                c_ts = pd.Timestamp(curr_date).floor('D')
                                l_ts = pd.Timestamp(last_exit_date).floor('D')
                                if (c_ts - l_ts) < pd.Timedelta(days=cooldown_days):
                                    can_buy_now = False
                            
                            if can_buy_now:
                                trades.append({
                                    'entry_date': curr_date,
                                    'entry_price': curr_price,
                                    'exit_date': None, 'exit_price': curr_price,
                                    'pnl': 0.0, 'duration': 0,
                                    'segments': bnds,
                                    'exit_reason': '매수권역(신규)',
                                    'is_new_signal': True
                                })
            except Exception:
                pass
                    
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
            
            recent_entry_date = last_trade['entry_date']
            recent_entry_price = last_trade['entry_price']
            recent_exit_date = last_trade['exit_date']
            
            df_after_entry = df_daily[df_daily.index >= recent_entry_date]
            if pd.notna(recent_exit_date):
                 df_after_entry = df_after_entry[df_after_entry.index <= recent_exit_date]
            
            if not df_after_entry.empty:
                df_after_entry_copy = df_after_entry.copy()
                df_after_entry_copy['pnl_pct'] = (df_after_entry_copy['Close'] / recent_entry_price - 1) * 100
                max_pnl = df_after_entry_copy['pnl_pct'].max()
                max_pnl_date = df_after_entry_copy['pnl_pct'].idxmax().strftime('%Y-%m-%d')
                min_pnl = df_after_entry_copy['pnl_pct'].min()
                min_pnl_date = df_after_entry_copy['pnl_pct'].idxmin().strftime('%Y-%m-%d')
            else:
                max_pnl = 0.0; max_pnl_date = recent_entry_date.strftime('%Y-%m-%d')
                min_pnl = 0.0; min_pnl_date = recent_entry_date.strftime('%Y-%m-%d')

            compounded_pnl_val = 1.0
            for t in trades:
                 compounded_pnl_val *= (1 + t['pnl'] / 100)
            total_pnl = (compounded_pnl_val - 1) * 100

            closed_trades = [t for t in trades if t['exit_date'] is not None and not t.get('is_new_signal')]
            last_realized_pnl = closed_trades[-1]['pnl'] if closed_trades else None

            return {
                'Ticker': ticker, 'Name': name, 
                'Recent Buy Price': last_trade['entry_price'],
                'Recent Sell Price': last_trade['exit_price'],
                'Current PnL (%)': pnl_val,
                'Realized PnL (%)': last_realized_pnl,
                'Max 수익률': max_pnl, 'Max 날짜': max_pnl_date,
                'Min 수익률': min_pnl, 'Min 날짜': min_pnl_date,
                'Total PnL (%)': total_pnl,
                'Trades': len(trades), 
                'Win Rate (%)': (len([t for t in trades if t['pnl'] > 0]) / len(trades)) * 100 if trades else 0.0,
                'Recent Buy': last_buy, 'Recent Sell': last_sell,
                'Duration': last_trade['duration'],
                'exit_reason': last_trade.get('exit_reason', '-'),
                'df_daily': df_daily, 'trades': trades,
                'status': 'active' if not is_delisted else 'delisted',
                'from_cache': from_cache_overall
            }
    except Exception as e:
        import traceback
        error_msg = f"{str(e)}: {traceback.format_exc().splitlines()[-1]}"
        return {
            'Ticker': ticker, 'Name': name, 'Total PnL (%)': 0.0,
            'Trades': 0, 'Win Rate (%)': 0.0,
            'Recent Buy': '-', 'Recent Sell': '-',
            'Current PnL (%)': None,
            'Realized PnL (%)': None,
            'Max 수익률': None, 'Max 날짜': None,
            'Min 수익률': None, 'Min 날짜': None,
            'Duration': 0, 'exit_reason': f"Error: {error_msg}",
            'df_daily': None, 'trades': [],
             'status': 'error',
             'from_cache': from_cache_overall
        }
    return {
        'Ticker': ticker, 'Name': name, 'Total PnL (%)': 0.0,
        'Trades': 0, 'Win Rate (%)': 0.0,
        'Recent Buy': '-', 'Recent Sell': '-',
        'Recent Buy Price': 0, 'Recent Sell Price': 0,
        'Current PnL (%)': None,
        'Realized PnL (%)': None,
        'Max 수익률': None, 'Max 날짜': None,
        'Min 수익률': None, 'Min 날짜': None,
        'Duration': 0, 'exit_reason': '-',
        'df_daily': None, 'trades': [],
        'status': 'no_trades',
        'from_cache': from_cache_overall
    }
