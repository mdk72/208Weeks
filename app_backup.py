import streamlit as st
from pykrx import stock
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import time

# --- Setup ---
st.set_page_config(page_title="208주 6등분 스크리너", layout="wide")

# 폰트 설정 (Windows 한글 깨짐 방지)
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

# --- Sidebar ---
st.sidebar.title("🔍 설정")
market = st.sidebar.selectbox("시장 선택", ["KOSPI", "KOSDAQ"])
period_weeks = st.sidebar.number_input("조회 기간 (주)", value=208, min_value=1)
top_n = st.sidebar.slider("분석할 상위 종목 수 (시총 기준)", 50, 500, 200)

import requests
from bs4 import BeautifulSoup

# --- Functions ---
@st.cache_data(ttl=3600)
def get_stock_list(market):
    try:
        # 네이버 금융 시가총액 페이지에서 상위 종목 가져오기
        url_market = "kospi" if market == "KOSPI" else "kosdaq"
        stocks_data = []
        
        # 상위 5페이지(250종목) 정도 가져오기
        for page in range(1, 6):
            url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={0 if market == 'KOSPI' else 1}&page={page}"
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(res.text, 'html.parser')
            
            table = soup.find('table', {'class': 'type_2'})
            if not table:
                continue
                
            rows = table.find_all('tr')
            for row in rows:
                cols = row.find_all('td')
                if len(cols) > 1 and cols[1].find('a'):
                    ticker_url = cols[1].find('a')['href']
                    ticker = ticker_url.split('=')[-1]
                    name = cols[1].find('a').text
                    stocks_data.append({'Code': ticker, 'Name': name})
        
        if stocks_data:
            return pd.DataFrame(stocks_data)
            
    except Exception as e:
        st.error(f"데이터 조회 중 오류 발생: {e}")
    
    # 마지막 수단: 하드코딩된 리스트 (이것도 유지하되, 위 로직이 우선)
    if market == "KOSPI":
        fallback = {'005930': '삼성전자', '000660': 'SK하이닉스', '373220': 'LG에너지솔루션'}
    else:
        fallback = {'247540': '에코프로비엠', '086520': '에코프로', '091990': '셀트리온헬스케어'}
    return pd.DataFrame(list(fallback.items()), columns=['Code', 'Name'])

def analyze_stock(ticker, name, period_weeks=208):
    try:
        # 야후 파이낸스 티커 변환
        yf_ticker = ticker + (".KS" if market == "KOSPI" else ".KQ")
        
        # 주봉 데이터 (충분한 데이터를 위해 5년치 이상)
        end_date = datetime.now()
        start_date = end_date - timedelta(weeks=period_weeks + 52)
        
        df_weekly = yf.download(yf_ticker, start=start_date, end=end_date, interval='1wk', progress=False)
        if df_weekly.empty or len(df_weekly) < period_weeks:
            return None
        
        # MultiIndex 컬럼 평탄화 (yfinance 최신 버전 대응)
        if isinstance(df_weekly.columns, pd.MultiIndex):
            df_weekly.columns = df_weekly.columns.get_level_values(0)
            
        # 마지막 period_weeks 봉 선정
        df_target = df_weekly.tail(period_weeks).copy()
        
        low_208 = float(df_target['Low'].min())
        high_208 = float(df_target['High'].max())
        range_208 = high_208 - low_208
        if range_208 == 0: return None
        
        step = range_208 / 6
        
        # 구간 정의 (하단부터 A~F)
        b_top = low_208 + 2 * step # B/C 경계
        c_top = low_208 + 3 * step # C/D 경계
        
        current_price = float(df_target['Close'].iloc[-1])
        
        # 조건 1: 현재가가 B/C 경계와 C/D 경계 사이에 위치 (CD구간/Segment C)
        is_in_segment_c = b_top < current_price <= c_top
        
        # 조건 2: 최근 12주 이내에 B/C 경계를 돌파한 적이 있는가 (골든크로스)
        # 이전 봉이 B/C 이하이고 현재/최근 봉이 B/C 초과인 경우
        was_below_bc = (df_target['Close'].shift(1).tail(12) <= b_top).any()
        
        # 조건 3: 20일선 위에 존재
        df_daily = yf.download(yf_ticker, period='60d', interval='1d', progress=False)
        if df_daily.empty or len(df_daily) < 20:
            return None
            
        if isinstance(df_daily.columns, pd.MultiIndex):
            df_daily.columns = df_daily.columns.get_level_values(0)
            
        ma20 = float(df_daily['Close'].rolling(window=20).mean().iloc[-1])
        above_ma20 = current_price > ma20
        
        if is_in_segment_c and was_below_bc and above_ma20:
            return {
                'Ticker': ticker,
                'Name': name,
                'Total PnL (%)': total_pnl,
                'Trades': len(trades),
                'Win Rate (%)': win_rate,
                'df_daily': df_daily,
                'trades': trades
            }
    except:
        return None
    return None

# --- UI Setup ---
st.set_page_config(page_title="208주 6등분 스크리너", layout="wide")
init_db()

@st.cache_data
def get_stock_list(market_type):
    """KOSPI/KOSDAQ 시가총액 리스트 가져오기 (pandas-datareader 대신 krx api 등 활용)"""
    url = 'http://kind.krx.co.kr/corpgeneral/corpList.do?method=download'
    df = pd.read_html(url, header=0)[0]
    df['Code'] = df['종목코드'].map('{:06d}'.format)
    # 실제로는 시가총액 데이터를 따로 가져와야 하지만, 일단 KIND 리스트 사용
    return df[['Code', '기업명']].rename(columns={'기업명': 'Name'})

st.title("📈 208-Week 6-Segment Scalping System")

with st.sidebar:
    st.header("🔍 설정")
    market = st.radio("시장 선택", ["KOSPI", "KOSDAQ"])
    lookback = st.number_input("조회 기간 (주)", value=208, step=1, min_value=52)
    n_stocks = st.slider("분석할 상위 종목 수 (시총 기준)", 50, 500, 200)

tab1, tab2 = st.tabs(["📊 실시간 스크리너", "🧪 백테스팅"])

with tab1:
    if st.button("🔥 실시간 종목 스캔 시작"):
        stock_list = get_stock_list(market).head(n_stocks)
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # 병렬 스캔 실행
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_stock = {
                executor.submit(fetch_data, row['Code'], market): row for _, row in stock_list.iterrows()
            }
            
            count = 0
            for future in as_completed(future_to_stock):
                stock_row = future_to_stock[future]
                df = future.result()
                if df is not None:
                    res = analyze_stock_core(stock_row['Code'], stock_row['Name'], df, lookback)
                    if res: results.append(res)
                
                count += 1
                progress_bar.progress(count / n_stocks)
                status_text.text(f"분석 중... ({count}/{n_stocks})")
        
        if results:
            df_res = pd.DataFrame(results).drop(columns=['df_daily', 'segments'])
            st.success(f"스캔 완료! 조건에 맞는 {len(results)}개 종목 분석")
            st.dataframe(df_res, use_container_width=True)
            st.session_state['scan_results'] = results
        else:
            st.warning("분석 결과가 없습니다.")

    if 'scan_results' in st.session_state:
        st.divider()
        st.subheader("종목별 상세 분석 차트")
        scan_results = st.session_state['scan_results']
        selected_name = st.selectbox("종목 선택", [res['Name'] for res in scan_results])
        
        sel_row = next(res for res in scan_results if res['Name'] == selected_name)
        df_plot = sel_row['df_daily']
        segments = sel_row['segments']
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['Close'], name='주가', line=dict(color='#26a69a', width=1.5)))
        
        labels_seg = ['L', 'A/B', 'B/C', 'C/D', 'D/E', 'E/F', 'H']
        for i, level in enumerate(segments):
            opacity = 0.2 if labels_seg[i] in ['B/C', 'D/E'] else 0.12
            fig.add_hline(y=level, line_dash="dash", line_color=f"rgba(255,255,255,{opacity})", annotation_text=labels_seg[i])
            
        fig.update_layout(title=f"{selected_name} 세그먼트 차트", template="plotly_dark", height=600, paper_bgcolor="#131722", plot_bgcolor="#131722")
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("전략 일괄 백테스팅 (2020~)")
    
    with st.expander("⚙️ 전략 조건 설정", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**[매수 조건]**")
            buy_breakout = st.checkbox("B/C 경계 상향 돌파 필수 (최근 5일)", value=True, key="bt_breakout")
            buy_ma20 = st.checkbox("20일 이평선 위 필수", value=True, key="bt_ma20")
            buy_segment = st.selectbox("진입 허용 구간", ["Segment C (B/C~C/D)", "Segment B (A/B~B/C)"], index=0, key="bt_seg")
        
        with col2:
            st.markdown("**[매도 조건]**")
            exit_target = st.selectbox("목표 구간 (익절 기준선)", ["D/E Boundary", "C/D Boundary", "E/F Boundary"], index=0, key="bt_target")
            exit_method = st.radio("매도 방식", ["목표 도달 후 20일선 이탈", "목표가 도달 시 즉시 매도"], index=0, key="bt_method")
            stop_loss_pct = st.number_input("손절 비율 (-% / 0일 경우 미사용)", min_value=0.0, max_value=50.0, value=0.0, step=0.5, key="bt_stoploss")

    bt_target_n = st.slider("분석할 상위 종목 수", 10, 100, 30, key="bt_n")
    
    if st.button("🚀 초고속 일괄 분석 시작"):
        config = {
            'buy_breakout': buy_breakout, 'buy_ma20': buy_ma20, 'buy_segment': buy_segment,
            'exit_target': exit_target, 'exit_method': exit_method, 'stop_loss_pct': stop_loss_pct
        }
        
        stock_list = get_stock_list(market).head(bt_target_n)
        batch_results = []
        progress_bt = st.progress(0)
        status_bt = st.empty()
        
        # 병렬 백테스트 실행
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_bt = {
                executor.submit(process_backtest_stock, row['Code'], row['Name'], market, config): row 
                for _, row in stock_list.iterrows()
            }
            
            count = 0
            for future in as_completed(future_to_bt):
                res = future.result()
                if res: batch_results.append(res)
                count += 1
                progress_bt.progress(count / bt_target_n)
                status_bt.text(f"백테스팅 완료: {count}/{bt_target_n}")
        
        if batch_results:
            df_bt = pd.DataFrame(batch_results).drop(columns=['df_daily', 'trades']).sort_values('Total PnL (%)', ascending=False)
            st.success(f"분석 완료! 상위 평균 수익률: {df_bt['Total PnL (%)'].mean():.2f}%")
            st.dataframe(df_bt, use_container_width=True)
            st.session_state['bt_batch_results'] = batch_results

    if 'bt_batch_results' in st.session_state:
        st.divider()
        batch_results = st.session_state['bt_batch_results']
        selected_name = st.selectbox("결과 상세 보기", [res['Name'] for res in batch_results], key="bt_select")
        
        sel_row = next(res for res in batch_results if res['Name'] == selected_name)
        df_plot = sel_row['df_daily']
        trades_plot = sel_row['trades']
        
        # 1. Performance Summary
        global_fig = go.Figure()
        global_fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['Close'], name='Price', line=dict(color='#d1d4dc', width=1)))
        for t in trades_plot:
            global_fig.add_vrect(x0=t['entry_date'], x1=t['exit_date'], fillcolor="#26a69a" if t['pnl'] > 0 else "#ef5350", opacity=0.15, layer="below", line_width=0)
        
        global_fig.update_layout(title=f"<b>{selected_name} Performance Summary</b>", height=300, template="plotly_dark", paper_bgcolor="#131722", plot_bgcolor="#131722", xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor="#2a2e39"))
        st.plotly_chart(global_fig, use_container_width=True)

        st.subheader("📍 Transaction Details")
        for idx, t in enumerate(trades_plot):
            st.write(f"#### Trade #{idx+1} ({t['pnl']:.2f}%)")
            zoom_start = t['entry_date'] - timedelta(weeks=12)
            zoom_end = t['exit_date'] + timedelta(weeks=4)
            df_zoom = df_plot[(df_plot.index >= zoom_start) & (df_plot.index <= zoom_end)].copy()
            if df_zoom.empty: continue
            
            fig = go.Figure()
            labels_seg = ['L', 'A/B', 'B/C', 'C/D', 'D/E', 'E/F', 'H']
            for i, level in enumerate(t['segments']):
                opacity = 0.2 if labels_seg[i] in ['B/C', 'D/E'] else 0.12
                fig.add_hline(y=level, line_dash="dash", line_color=f'rgba(255,255,255,{opacity})', line_width=1)
            
            fig.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['Close'], name='Price', line=dict(color='#26a69a', width=1.5)))
            fig.add_annotation(x=t['entry_date'], y=t['entry_price'], text="▲ BUY", showarrow=False, yshift=15, font=dict(color="#2196f3"))
            fig.add_annotation(x=t['exit_date'], y=t['exit_price'], text=f"▼ SELL ({t['pnl']:.1f}%)", showarrow=False, yshift=15, font=dict(color="#ff5252"))
            
            fig.update_layout(height=450, template="plotly_dark", paper_bgcolor="#131722", plot_bgcolor="#131722", yaxis=dict(side="right"))
            st.plotly_chart(fig, use_container_width=True)
            
        st.table(pd.DataFrame(trades_plot).drop(columns=['segments']))
