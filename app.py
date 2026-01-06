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

def get_cached_data(ticker, start_date):
    if not os.path.exists(CACHE_DB): return None
    try:
        with db_lock:
            conn = sqlite3.connect(CACHE_DB)
            cursor = conn.cursor()
            cursor.execute("SELECT last_updated FROM cache_meta WHERE ticker = ?", (ticker,))
            row = cursor.fetchone()
            
            today_str = datetime.now().strftime('%Y-%m-%d')
            if row and row[0] == today_str:
                df = pd.read_sql_query("SELECT * FROM price_data WHERE ticker = ? AND date >= ?", conn, params=(ticker, start_date))
                conn.close()
                if not df.empty:
                    df['date'] = pd.to_datetime(df['date'])
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

def fetch_data(ticker, market, start_date="2016-01-01"):
    # Rate Limit 방지: 랜덤 딜레이 (속도 향상을 위해 최소화: 0.05~0.1초)
    time.sleep(random.uniform(0.05, 0.1))
    
    yf_ticker = ticker + (".KS" if market == "KOSPI" else ".KQ")
    cached_df = get_cached_data(ticker, start_date)
    if cached_df is not None:
        return cached_df
    
    try:
        # yfinance 호출 실패 시 재시도 로직 없이 바로 실패 처리 (쓰로틀링 우선)
        # threads=False로 설정하여 내부 스레딩 비활성화 (외부 ThreadPoolExecutor 충돌 방지)
        df = yf.download(yf_ticker, start=start_date, progress=False, timeout=10, threads=False)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        save_to_cache(ticker, df)
        return df
    except Exception as e:
        # print(f"Fetch Error ({ticker}): {e}") # 로그 과다 방지
        return None


def analyze_stock_core(ticker, name, df, lookback_weeks=208):
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
        
        # Condition 2: Golden Cross over B/C line within last 12 weeks (Rising Logic)
        # 하락하다가 멈춘게 아니라, "밑에서 치고 올라온" 종목이어야 함.
        # 즉, 최근 12주(약 3달) 내에 최저가가 B/C 라인보다 낮았어야 함 (돌파 발생 확인)
        recent_low = df['Low'].tail(12).min()
        if recent_low >= bc_line:
            return None # 최근에 B/C 밑에 있었던 적이 없으면(계속 위에 있었거나 위에서 내려옴) 탈락
        
        # Condition 3: Above 20MA
        df_temp = df.tail(30).copy()
        df_temp['MA20'] = df_temp['Close'].rolling(window=20).mean()
        curr_ma20 = float(df_temp['MA20'].iloc[-1])
        
        if current_price < curr_ma20:
             return None # Skip if below 20MA
        
        ma_status = "O (Above)"
        
        return {
            'Code': ticker, 'Name': name, '현재가': current_price,
            '208주 최저': low_208, '208주 최고': high_208,
            '현재 구간': curr_seg, '20일선': ma_status,
            'df_daily': df, 'segments': segments,
            'recent_low': recent_low # 디버깅용
        }
    except:
        return None

def process_backtest_stock(ticker, name, market, config):
    try:
        df_daily = fetch_data(ticker, market)
        if df_daily is None or len(df_daily) < 1000: return None
            
        buy_breakout = config['buy_breakout']
        buy_ma20 = config['buy_ma20']
        buy_segment = config['buy_segment']
        exit_target = config['exit_target']
        exit_method = config['exit_method']
        stop_loss_pct = config['stop_loss_pct']
        
        df_daily = df_daily.copy()
        df_daily['MA20'] = df_daily['Close'].rolling(window=20).mean()
        # 1040일 롤링으로 208주 고저가 근사 (벡터화 속도 개선)
        df_daily['RollLow'] = df_daily['Low'].rolling(window=1040).min().shift(1)
        df_daily['RollHigh'] = df_daily['High'].rolling(window=1040).max().shift(1)
        
        trades = []
        position = None
        target_hit = False
        df_test = df_daily[df_daily.index >= pd.Timestamp("2020-01-01")].copy()
        
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
                    was_below = float(df_test['Close'].iloc[max(0, i-5):i].min()) <= bnd
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
                    
        if trades:
            return {
                'Ticker': ticker, 'Name': name, 'Total PnL (%)': sum(t['pnl'] for t in trades),
                'Trades': len(trades), 'Win Rate (%)': (len([t for t in trades if t['pnl'] > 0]) / len(trades)) * 100,
                'df_daily': df_daily, 'trades': trades
            }
    except: return None
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
                    
                    stocks.append({'Code': code, 'Name': name})
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

st.title("� 208-Week High-Speed System")

with st.sidebar:
    st.header("🔍 설정")
    market_sel = st.radio("시장 선택", ["KOSPI", "KOSDAQ"])
    lookback_sel = st.number_input("조회 기간 (주)", value=208, step=1, min_value=52)
    n_stocks_sel = st.slider("분석할 상위 종목 수", 50, 500, 200)

tab1, tab2 = st.tabs(["📊 실시간 스크리너", "🧪 백테스팅"])

with tab1:
    if st.button("🔥 실시간 종목 스캔 시작"):
        stock_list = get_stock_list_naver(market_sel, n_stocks_sel)
        results = []
        pb = st.progress(0)
        st_txt = st.empty()
        
        # 안정성을 위해 병렬 처리 개수 조정 (2~4)
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_stock = {executor.submit(fetch_data, row['Code'], market_sel): row for _, row in stock_list.iterrows()}
            
            success_count = 0
            fail_count = 0
            
            for i, future in enumerate(as_completed(future_to_stock)):
                stock_row = future_to_stock[future]
                try:
                    df = future.result()
                    if df is not None:
                        res = analyze_stock_core(stock_row['Code'], stock_row['Name'], df, lookback_sel)
                        if res: 
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
                st_txt.text(f"분석 중... ({i+1}/{n_stocks_sel}) | 발견: {len(results)}개")
        
        if results:
            st.success(f"스캔 완료! {len(results)}개 종목 분석")
            df_disp = pd.DataFrame(results).drop(columns=['df_daily', 'segments'])
            st.dataframe(df_disp, use_container_width=True)
            st.session_state['scan_results'] = results
        else: st.warning("결과가 없습니다.")

    if 'scan_results' in st.session_state:
        st.divider()
        scan_results = st.session_state['scan_results']
        sel_name = st.selectbox("종목 선택", [res['Name'] for res in scan_results], key="scan_sel")
        row_sel = next(res for res in scan_results if res['Name'] == sel_name)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=row_sel['df_daily'].index, y=row_sel['df_daily']['Close'], name='Price', line=dict(color='#26a69a')))
        for i, level in enumerate(row_sel['segments']):
            fig.add_hline(y=level, line_dash="dash", line_color="rgba(200,200,200,0.2)")
        fig.update_layout(template="plotly_dark", height=600, paper_bgcolor="#131722", plot_bgcolor="#131722")
        st.plotly_chart(fig, use_container_width=True)

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

    if st.button("🚀 초고속 분석 시작"):
        stock_list = get_stock_list_naver(market_sel, 100)
        cfg = {'buy_breakout':bt_brk, 'buy_ma20':bt_ma, 'buy_segment':bt_seg, 'exit_target':bt_tgt, 'exit_method':bt_met, 'stop_loss_pct':bt_sl}
        bt_results = []
        pb_bt = st.progress(0)
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_bt = {executor.submit(process_backtest_stock, r['Code'], r['Name'], market_sel, cfg): r for _, r in stock_list.iterrows()}
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
        st.dataframe(pd.DataFrame(bt_res).drop(columns=['df_daily', 'trades']).sort_values('Total PnL (%)', ascending=False), use_container_width=True)
        st.divider()
        sel_bt = st.selectbox("상세 보기", [r['Name'] for r in bt_res], key="bt_sel")
        row_bt = next(r for r in bt_res if r['Name'] == sel_bt)
        st.subheader("📍 매매 상세 분석 (Transaction Details)")
        
        # 1. 전체 차트 (Global View)
        fig_global = go.Figure()
        fig_global.add_trace(go.Scatter(x=row_bt['df_daily'].index, y=row_bt['df_daily']['Close'], name='Price', line=dict(color='#d1d4dc', width=1)))
        for t in row_bt['trades']:
            color = "#26a69a" if t['pnl'] > 0 else "#ef5350"
            fig_global.add_vrect(x0=t['entry_date'], x1=t['exit_date'], fillcolor=color, opacity=0.1, layer="below", line_width=0)
        fig_global.update_layout(title=f"{sel_bt} 전체 흐름", height=300, template="plotly_dark", paper_bgcolor="#131722", plot_bgcolor="#131722")
        st.plotly_chart(fig_global, use_container_width=True)

        # 2. 개별 매매 상세 차트 (Zoomed View)
        for idx, t in enumerate(row_bt['trades']):
            st.divider()
            st.markdown(f"#### 🎯 Trade #{idx+1} 수익률: :{'blue' if t['pnl']>0 else 'red'}[{t['pnl']:.2f}%]")
            
            # 줌 범위 설정 (진입 3개월 전 ~ 청산 1개월 후)
            zoom_start = t['entry_date'] - timedelta(weeks=12)
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
            
            # 매수/매도 마커
            fig.add_annotation(x=t['entry_date'], y=t['entry_price'], text="▲ BUY", showarrow=True, arrowhead=2, arrowwidth=2, arrowcolor="#42a5f5", ax=0, ay=30, font=dict(color="#42a5f5", size=12))
            fig.add_annotation(x=t['exit_date'], y=t['exit_price'], text=f"▼ SELL ({t['pnl']:.1f}%)", showarrow=True, arrowhead=2, arrowwidth=2, arrowcolor="#ef5350", ax=0, ay=-30, font=dict(color="#ef5350", size=12))

            fig.update_layout(title=f"Trade #{idx+1} 상세 (진입: {t['entry_date'].date()} -> 청산: {t['exit_date'].date()})", height=450, template="plotly_dark", paper_bgcolor="#131722", plot_bgcolor="#131722")
            st.plotly_chart(fig, use_container_width=True)
            
        st.write("📋 매매 기록 테이블")
        st.table(pd.DataFrame(row_bt['trades']).drop(columns=['segments']))
