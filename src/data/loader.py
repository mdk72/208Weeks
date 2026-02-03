import sqlite3
import os
import threading
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pytz
import warnings

# Suppress external library warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated as an API.*")

# Global Constants
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_DIR = os.path.join(BASE_DIR, "src", "data", "cache") # Keep CACHE_DIR distinct if needed, or just use BASE_DIR for DB
# Original logic seemingly used BASE_DIR for DB. Let's stick to root for DB as seen in file list.
DB_PATH = os.path.join(BASE_DIR, "price_cache.db")
CACHE_DB = DB_PATH # Alias for backward compatibility
STOCKEASY_DB_PATH = os.path.join(os.getcwd(), "src", "data", "stockeasy_data.db")
db_lock = threading.Lock()

# Excluded Tickers (Data Discrepancies/Complex Corp Actions)
EXCLUDED_TICKERS = []

def is_market_open():
    """
    장중 여부 확인 (09:00-15:30 KST)
    Returns: True if market is currently open, False otherwise
    """
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.now(kst)
    
    # 주말 제외
    if now.weekday() >= 5:  # 5=토요일, 6=일요일
        return False
    
    hour, minute = now.hour, now.minute
    
    # 09:00 ~ 15:30
    if hour == 9 and minute >= 0:
        return True
    elif 10 <= hour < 15:
        return True
    elif hour == 15 and minute <= 30:
        return True
    
    return False

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

def get_cached_data(ticker, requested_start_date, scan_date=None):
    """캐시에서 데이터 조회"""
    try:
        with db_lock:
            conn = sqlite3.connect(CACHE_DB)
            # 인덱스 활용을 위해 날짜 조건 추가
            query = f"SELECT date, open, high, low, close FROM price_data WHERE ticker = ? AND date >= ? ORDER BY date"
            df = pd.read_sql(query, conn, params=(ticker, requested_start_date))
            
            # 메타데이터 확인 (최신 데이터 여부)
            cursor = conn.cursor()
            cursor.execute("SELECT last_updated FROM cache_meta WHERE ticker = ?", (ticker,))
            row = cursor.fetchone()
            conn.close()

        if df.empty or row is None:
            return None

        # [Important] 캐시된 데이터의 시작 날짜 확인
        # 요청된 시작 날짜보다 캐시 데이터가 늦게 시작하면(데이터 부족), 
        # 새로 받아야 함. (단, 7일 정도의 초기 버퍼 허용)
        first_data_date = pd.to_datetime(df['date'].iloc[0]).date()
        req_start_date_obj = pd.to_datetime(requested_start_date).date()
        # [UPDATE] 데이터 시작일 체크 완화
        # 신규 상장 종목(IPO)의 경우 2020년보다 늦게 시작할 수 있음.
        # 캐시된 데이터가 있고, 마지막 날짜가 최신이면 유효한 것으로 간주.
        # if first_data_date > req_start_date_obj + pd.Timedelta(days=7):
        #    return None

        # [Smart Cache] scan_date가 오늘이 아니라면(백테스트 검증 등 과거 날짜),
        # 오늘 날짜로 업데이트되었는지 굳이 엄격하게 따질 필요 없음.
        # 캐시된 데이터의 마지막 날짜가 scan_date보다 같거나 뒤라면 유효한 것으로 간주.
        import pytz
        kst = pytz.timezone('Asia/Seoul')
        today_date = datetime.now(kst).date()
        today_str = today_date.strftime('%Y-%m-%d')
        
        # 캐시의 마지막 데이터 날짜 확인
        last_data_date_str = df['date'].iloc[-1]
        last_data_date = datetime.strptime(last_data_date_str, '%Y-%m-%d').date()

        # [NEW LOGIC] 장중/장마감 구분
        market_is_open = is_market_open()
        yesterday_date = today_date - timedelta(days=1)
        
        # 1. scan_date가 주어진 경우 (백테스트): 기존 로직 유지
        if scan_date:
            if last_data_date >= scan_date:
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
                df.index.name = 'Date'
                df.columns = ['Open', 'High', 'Low', 'Close']
                return df
            else:
                return None
        
        # 2. 장중인 경우: 전일까지의 데이터만 리턴 (당일 데이터는 API로 갱신 필요)
        if market_is_open:
            if last_data_date >= yesterday_date:
                # 어제까지의 데이터만 필터링
                df_filtered = df[df['date'] < today_str].copy()
                if not df_filtered.empty:
                    df_filtered['date'] = pd.to_datetime(df_filtered['date'])
                    df_filtered.set_index('date', inplace=True)
                    df_filtered.index.name = 'Date'
                    df_filtered.columns = ['Open', 'High', 'Low', 'Close']
                    return df_filtered
            # 어제 데이터도 없으면 전체 재수집
            return None
        
        # 3. 장마감 후: 기존 로직 (오늘 업데이트 확인)
        if row[0] == today_str:
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            df.index.name = 'Date'
            df.columns = ['Open', 'High', 'Low', 'Close']
            return df
        
        # 오늘 업데이트 기록 없음 -> 3일 이내면 사용
        if (today_date - last_data_date).days > 3:
             return None

        # 포맷 변환 및 리턴
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        df.index.name = 'Date'
        df.columns = ['Open', 'High', 'Low', 'Close']
        
        return df
        
    except Exception:
        return None

def save_to_cache(ticker, df):
    """데이터 캐시 저장"""
    if df is None or df.empty: return
    
    try:
        import pytz
        kst = pytz.timezone('Asia/Seoul')
        today_str = datetime.now(kst).strftime('%Y-%m-%d')
        
        with db_lock:
            conn = sqlite3.connect(CACHE_DB)
            cursor = conn.cursor()
            
            # 기존 데이터 삭제 후 전체 저장 (중복 방지 및 갱신) -> MERGE가 좋지만 SQLite는 REPLCAE
            # 하지만 전체 기간을 다시 받으므로 기존 데이터를 지우고 넣는게 깔끔함
            cursor.execute("DELETE FROM price_data WHERE ticker = ?", (ticker,))
            
            # Bulk Insert
            data_to_insert = []
            for date, row in df.iterrows():
                # yfinance 데이터가 Series 객체로 반환될 경우 스칼라 값으로 변환
                # (가끔 row['Open']이 Series로 나오는 경우가 있음 - 버전 차이)
                o = float(row['Open'].iloc[0]) if hasattr(row['Open'], 'iloc') else float(row['Open'])
                h = float(row['High'].iloc[0]) if hasattr(row['High'], 'iloc') else float(row['High'])
                l = float(row['Low'].iloc[0]) if hasattr(row['Low'], 'iloc') else float(row['Low'])
                c = float(row['Close'].iloc[0]) if hasattr(row['Close'], 'iloc') else float(row['Close'])
                
                data_to_insert.append((ticker, date.strftime('%Y-%m-%d'), o, h, l, c))
                
            cursor.executemany("INSERT INTO price_data VALUES (?, ?, ?, ?, ?, ?)", data_to_insert)
            
            # 메타데이터 갱신 (오늘 날짜로 업데이트됨 표시)
            cursor.execute("REPLACE INTO cache_meta (ticker, last_updated) VALUES (?, ?)", (ticker, today_str))
            
            conn.commit()
            conn.close()
            
    except Exception as e:
        print(f"[ERROR] Failed to save cache for {ticker}: {e}")

def fetch_naver_data(ticker, days=365*5):
    """
    네이버 금융에서 일별 시세 데이터 조회 (XML)
    """
    try:
        # Naver code is 6 digits
        code = str(ticker).zfill(6)
        count = days  # Request enough data
        
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={count}&requestType=0"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        
        soup = BeautifulSoup(res.text, "xml")
        items = soup.find_all("item")
        
        if not items:
            return None
            
        data = []
        for item in items:
            # data format: Date|Open|High|Low|Close|Volume
            vals = item['data'].split('|')
            if len(vals) >= 6:
                data.append({
                    'Date': pd.to_datetime(vals[0], format='%Y%m%d'),
                    'Open': float(vals[1]),
                    'High': float(vals[2]),
                    'Low': float(vals[3]),
                    'Close': float(vals[4]),
                    'Volume': float(vals[5])
                })
                
        if not data:
            return None
            
        df = pd.DataFrame(data).set_index('Date')
        df = df.sort_index()
        
        # Ensure numeric columns
        cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        for c in cols:
            df[c] = pd.to_numeric(df[c])
            
        return df
        
    except Exception as e:
        print(f"Naver fetch failed for {ticker}: {e}")
        return None

def fetch_data(ticker, market, start_date='2020-01-01', scan_date=None):
    """
    데이터 가져오기 (캐시 -> pykrx)
    장중: 전일 캐시 + 당일 API
    장마감 후: 전체 캐시 또는 전체 API
    """
    kst = pytz.timezone('Asia/Seoul')
    now_kst = datetime.now(kst)
    market_is_open = is_market_open()
    
    # 캐시 확인
    cached_df = get_cached_data(ticker, start_date, scan_date=scan_date)
    
    # [NEW LOGIC] 장중 + 캐시 있음 -> 당일 데이터만 API로 가져와서 병합
    is_today_scan = (scan_date is None) or (scan_date == now_kst.date())
    
    if market_is_open and cached_df is not None and is_today_scan:
        try:
            # [NEW] Naver Finance로 실시간(장중) 데이터 업데이트 시도
            # yfinance는 속도/데이터 이슈가 있으므로 제거하고 Naver 사용
            naver_ticker = ticker.split('.')[0] if '.' in ticker else ticker
            df_recent = fetch_naver_data(naver_ticker, days=20) # 최근 20일치만 빠르게 조회
            
            if df_recent is not None and not df_recent.empty:
                df_recent.index.name = 'Date'
                
                # 오늘 날짜 확인
                today_date = now_kst.date()
                
                # Naver 데이터에서 오늘 날짜 있는지 확인
                df_today = df_recent[df_recent.index.date == today_date]
                
                if not df_today.empty:
                    # 캐시 + 오늘 데이터 병합/업데이트
                    # (캐시의 마지막 데이터가 오늘 날짜라면 덮어쓰고, 아니면 추가)
                    combined_df = pd.concat([cached_df, df_today[['Open', 'High', 'Low', 'Close', 'Volume']]])
                    combined_df = combined_df[~combined_df.index.duplicated(keep='last')]
                    combined_df = combined_df.sort_index()
                    
                    return combined_df, "cache_update"
        except Exception:
            pass
        
        # 오늘 데이터 실패 -> 캐시만 리턴
        return cached_df, "cache"
    
    # 캐시가 완전히 유효한 경우
    if cached_df is not None:
        return cached_df, "cache"
    
    # [NEW LOGIC] 캐시 없고 장중 or 캐시 없음 -> Naver Finance 우선 시도 (가장 정확한 수정주가)
    if True: # Always try Naver first if cache is missing or insufficient
        try:
            # Naver는 Ticker(6자리)만 필요
            naver_ticker = ticker.split('.')[0] if '.' in ticker else ticker
            df = fetch_naver_data(naver_ticker, days=2000) # 약 5년치
            
            if df is not None and not df.empty:
                # 데이터 포맷 확인 및 가공
                df.index.name = 'Date'
                
                # Start Date 필터링
                if start_date:
                    df = df[df.index >= pd.Timestamp(start_date)]
                
                # 데이터 유효성 체크
                if len(df) >= 10:
                    save_to_cache(ticker, df)
                    return df, "api"
                else:
                    pass
            else:
                pass
        except Exception as e:
            # print(f"Naver fetch failed: {e}")
            pass

    # Naver 실패 시 기존 로직 (yfinance)
    if market_is_open and is_today_scan:
        try:
            import yfinance as yf
            
            yf_ticker_ks = f"{ticker}.KS"
            yf_ticker_kq = f"{ticker}.KQ"
            
            df = None
            
            # KOSPI 시도
            try:
                df_temp = yf.download(yf_ticker_ks, start=start_date, progress=False, auto_adjust=True)
                if df_temp is not None and not df_temp.empty:
                    df = df_temp
            except Exception:
                pass
                
            # KOSDAQ 시도
            if df is None or df.empty:
                try:
                    df_temp = yf.download(yf_ticker_kq, start=start_date, progress=False, auto_adjust=True)
                    if df_temp is not None and not df_temp.empty:
                        df = df_temp
                except Exception:
                    pass
            
            if df is not None and not df.empty:
                # MultiIndex 및 포맷 처리
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                
                df = df.rename(columns={
                    'Open': 'Open', 'High': 'High', 'Low': 'Low', 
                    'Close': 'Close', 'Volume': 'Volume'
                })
                
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
                    
                df.index = pd.to_datetime(df.index)
                df.index.name = 'Date'
                
                # 데이터 유효성 체크
                if 'Close' in df.columns and len(df) >= 10:
                    save_to_cache(ticker, df)
                    return df, False
                    
        except Exception:
            pass  # 실패 시 pykrx로 Fallback

    # 캐시 없음 -> 전체 데이터 API로 가져오기 (pykrx)
    try:
        from pykrx import stock
        
        kst = pytz.timezone('Asia/Seoul')
        now_kst = datetime.now(kst)
        
        end_date = now_kst.strftime('%Y%m%d')
        start_date_pykrx = datetime.strptime(start_date, '%Y-%m-%d').strftime('%Y%m%d')
        
        try:
            df = stock.get_market_ohlcv_by_date(start_date_pykrx, end_date, ticker)
        except Exception:
            df = None

        # pykrx 실패 시 yfinance 시도
        if df is None or df.empty:
            try:
                import yfinance as yf
                yf_ticker = f"{ticker}.KS"
                df_yf = yf.download(yf_ticker, start=start_date, progress=False, auto_adjust=True)
                
                if df_yf is None or df_yf.empty:
                    # 코스닥 시도
                    yf_ticker = f"{ticker}.KQ"
                    df_yf = yf.download(yf_ticker, start=start_date, progress=False, auto_adjust=True)
                
                if df_yf is not None and not df_yf.empty:
                    df = df_yf
                    
                    # [Robustness] yfinance 0.2.x+ MultiIndex columns handle
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                        
                    # yfinance 컬럼 매핑
                    df = df.rename(columns={
                        'Open': 'Open', 'High': 'High', 'Low': 'Low', 
                        'Close': 'Close', 'Volume': 'Volume'
                    })
                    # 인덱스 타임존 제거
                    if df.index.tz is not None:
                        df.index = df.index.tz_localize(None)
            except Exception:
                pass
        
        if df is None or df.empty:
            return None, "api" # Failed api
        
        # 컬럼명 통일 (한글 -> 영어)
        df = df.rename(columns={
            '시가': 'Open',
            '고가': 'High', 
            '저가': 'Low',
            '종가': 'Close',
            '거래량': 'Volume'
        })
        
        df.index = pd.to_datetime(df.index)
        df.index.name = 'Date'
        
        # 데이터 정합성 체크 (Price가 0인 경우 제외)
        if 'Close' in df.columns:
            df = df[df['Close'] > 0]
        
        if len(df) < 10:
             return None, "api" # Failed api

        save_to_cache(ticker, df)
        return df, "api"
        
    except Exception:
        return None, "api"

def get_stock_list_naver(market_type, top_n=200):
    """네이버 금융 시가총액 상위 리스트 크롤링"""
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
                if len(tds) <= 1: continue
                
                try:
                    rank = tds[0].text.strip()
                    if not rank.isdigit(): continue
                except: continue
                
                try:
                    a_tag = tds[1].find('a')
                    if not a_tag: continue
                    
                    name = a_tag.text.strip()
                    href = a_tag['href'] 
                    code = href.split('=')[-1].zfill(6)
                    
                    # [Exclude Filter] 데이터 이상 종목 제외
                    if code in EXCLUDED_TICKERS:
                        continue
                    
                    # [Common Stock Filter] 보통주(0)가 아니면 제외 (우선주, 권리락 등 제외)
                    if not code.endswith('0'):
                        continue
                    
                    # ETF 및 기타 지수 종목 필터링 강화
                    etf_keywords = [
                        'KODEX', 'TIGER', 'ACE', 'KBSTAR', 'SOL', 'RISE', 'ARIRANG', 
                        'HANARO', 'KINDEX', 'KOSEC', 'KOSEF', 'TREX', 'SMART', 'FOCUS', 'WOORI',
                        'KIWOOM', 'PLUS', 'N2', 'KOSPI', 'KOSDAQ', '레버리지', '인버스', '선물', ' 200', ' 150'
                    ]
                    if any(kw in name.upper() for kw in etf_keywords) or name.endswith('TR'):
                        continue
                    
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
        # Fallback data
        return pd.DataFrame([
            {'Code':'005930', 'Name':'삼성전자'}, {'Code':'000660', 'Name':'SK하이닉스'},
            {'Code':'373220', 'Name':'LG에너지솔루션'}, {'Code':'207940', 'Name':'삼성바이오로직스'},
            {'Code':'005380', 'Name':'현대차'}, {'Code':'000270', 'Name':'기아'}
        ])


def get_historical_market_cap_list(date_str, market_type, top_n=200):
    """
    특정 시점(date_str)의 시가총액 상위 종목 리스트를 가져옴 (생존편향 제거용)
    date_str: 'YYYYMMDD' or 'YYYY-MM-DD'
    market_type: 'KOSPI' or 'KOSDAQ'
    """
    try:
        from pykrx import stock
        import time
        
        # 날짜 포맷 정리
        target_date = date_str.replace('-', '')
        
        # [REFACTORED] Improved error handling for pykrx failures
        df = None
        last_error = None
        
        # 1. 시가총액 데이터 가져오기 (휴장일 고려 역추적)
        search_date = target_date
        for i in range(10): 
            try:
                temp_df = stock.get_market_cap(search_date)
                if temp_df is not None and not temp_df.empty:
                    df = temp_df
                    target_date = search_date # 실제 데이터를 찾은 날짜로 갱신
                    break
                
                # 데이터가 없는 경우 (None or Empty) -> 휴장일 가능성
                curr_dt = datetime.strptime(search_date, "%Y%m%d")
                search_date = (curr_dt - timedelta(days=1)).strftime("%Y%m%d")
                time.sleep(0.05) 
            except Exception as e:
                # 라이브러리 내부 에러 (KeyError, Encoding 등)
                last_error = str(e)
                break # 에러 발생 시 역추적 중단하고 실패 처리
                
        if df is None or df.empty:
            # [SILENCED] Removed debug print to avoid terminal clutter as per user request
            return None

        # Ticker가 인덱스로 오므로 컬럼으로 변환
        df = df.reset_index()
        
        # 코스피/코스닥 필터링
        # 해당 날짜 기준의 티커 리스트 필요
        tickers_kospi = stock.get_market_ticker_list(target_date, market="KOSPI")
        tickers_kosdaq = stock.get_market_ticker_list(target_date, market="KOSDAQ")
        
        if market_type == "KOSPI":
            df = df[df['티커'].isin(tickers_kospi)]
        else:
            df = df[df['티커'].isin(tickers_kosdaq)]
            
        # 시가총액 순 정렬
        df = df.sort_values(by='시가총액', ascending=False)
        
        # ETF 필터링 (과거 시점 종목명 기준)
        etf_keywords = [
             'KODEX', 'TIGER', 'ACE', 'KBSTAR', 'SOL', 'RISE', 'ARIRANG', 
             'HANARO', 'KINDEX', 'KOSEC', 'KOSEF', 'TREX', 'SMART', 'FOCUS', 'WOORI'
        ]
        
        stocks = []
        count = 0
        for _, row in df.iterrows():
            name = row['종목명']
            # ETF 제외
            if any(kw in name.upper() for kw in etf_keywords):
                continue
            # 스팩 제외 (종목명에 '스팩' 포함)
            if '스팩' in name:
                continue
                
            stocks.append({
                'Code': row['티커'],
                'Name': name,
                '현재가': row['종가'] # 당시의 종가를 '현재가' 컨셉으로 사용
            })
            count += 1
            if count >= top_n:
                break
            
        # print(f"Historical Universe constructed for {target_date}: {len(stocks)} stocks")
        return pd.DataFrame(stocks)
    except Exception as e:
        # print(f"Error fetching historical market cap: {e}")
        return None

def create_market_cap_snapshot(market='KOSPI', top_n=200):
    """
    현재 시점의 시가총액 상위 종목을 스냅샷으로 저장
    Returns: (success: bool, snapshot_date: str, error: str)
    """
    try:
        kst = pytz.timezone('Asia/Seoul')
        now = datetime.now(kst)
        today_str = now.strftime('%Y-%m-%d')
        
        # Fetch current top stocks
        stock_df = get_stock_list_naver(market, top_n)
        
        if stock_df is None or stock_df.empty:
            return False, None, "Failed to fetch stock list from Naver"
        
        # Extract market cap if available (Naver doesn't provide it directly)
        # We'll save just the list for now
        snapshot = {
            today_str: {
                market: {
                    'top_stocks': stock_df['Code'].tolist(),
                    'names': dict(zip(stock_df['Code'], stock_df['Name'])),
                    'prices': dict(zip(stock_df['Code'], stock_df.get('현재가', [0]*len(stock_df))))
                },
                'metadata': {
                    'created_at': now.isoformat(),
                    'source': 'naver_finance',
                    'total_stocks': len(stock_df),
                    'market': market
                }
            }
        }
        
        return True, today_str, snapshot
        
    except Exception as e:
        return False, None, str(e)

def get_stock_universe_for_date(target_date, market, n_stocks):
    """
    특정 날짜의 주식 유니버스 반환
    우선순위: Snapshot → Historical pykrx → Current fallback
    Returns: (DataFrame, source: str)
    """
    from .utils import load_market_cap_snapshots
    
    # Load snapshots
    snapshots = load_market_cap_snapshots()
    
    # Find closest snapshot <= target_date
    target_str = target_date.strftime('%Y-%m-%d')
    available_dates = sorted([
        d for d in snapshots['snapshots'].keys()
        if d <= target_str
    ], reverse=True)
    
    if available_dates:
        closest_date = available_dates[0]
        snapshot = snapshots['snapshots'][closest_date]
        
        # Check if this snapshot has the requested market
        if market in snapshot:
            codes = snapshot[market]['top_stocks'][:n_stocks]
            names = snapshot[market].get('names', {})
            prices = snapshot[market].get('prices', {})
            
            stock_list = pd.DataFrame([
                {'Code': code, 'Name': names.get(code, ''), '현재가': prices.get(code, 0)}
                for code in codes
            ])
            
            return stock_list, f"snapshot_{closest_date}"
    
    # Fallback to historical pykrx
    historical = get_historical_market_cap_list(target_date.strftime('%Y-%m-%d'), market, n_stocks)
    if historical is not None and not historical.empty:
        return historical, "historical_pykrx"
    
    # Last resort: current rankings
    current = get_stock_list_naver(market, n_stocks)
    return current, "current_fallback"
