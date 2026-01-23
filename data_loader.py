import sqlite3
import os
import threading
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz
import warnings

# Suppress external library warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated as an API.*")

# Constants
CACHE_DB = os.path.join(os.path.dirname(__file__), "price_cache.db")
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
        if first_data_date > req_start_date_obj + pd.Timedelta(days=7):
            return None

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

        # [Logic]
        # 1. scan_date가 주어진 경우: 캐시가 scan_date까지 커버하면 OK
        if scan_date:
            if last_data_date >= scan_date:
                # 인덱스 설정 및 변환
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
                df.index.name = 'Date'
                df.columns = ['Open', 'High', 'Low', 'Close']
                return df
            else:
                # scan_date보다 데이터가 부족하면 -> API 호출 필요 (업데이트)
                return None
        
        # 2. scan_date가 없는 경우 (기존 로직): 오늘 날짜 기준 최신성 판단
        # 장 중이라면 오늘 날짜 업데이트가 안 되어 있을 수 있음 -> 그래도 어제까지의 데이터가 있으면 유효하다고 볼 수도 있지만,
        # 실시간 스크리너 특성상 "오늘 데이터"가 없으면 실효성이 떨어짐.
        # 하지만 매번 API 호출은 부담스러우므로, "장 마감 후"에는 오늘 데이터 필수, "장 중"에는 어제 데이터도 허용하는 식의 유연함 필요.
        # -> 일단 기존 로직(오늘 날짜 업데이트 확인) 유지하되, 너무 잦은 갱신을 막기 위해 
        #    last_updated(메타)가 오늘 날짜면 데이터 갯수 상관없이 일단 리턴.
        
        if row[0] == today_str:
            # 오늘 이미 업데이트 했음 -> 캐시 리턴
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            df.index.name = 'Date'
            df.columns = ['Open', 'High', 'Low', 'Close']
            return df
        
        # 오늘 업데이트 기록 없음 -> 데이터가 최신인지 확인
        # 만약 지금이 장 시작 전(09:00 이전)이라면, 어제 데이터만 있어도 충분함.
        # 하지만 복잡도를 줄이기 위해, "마지막 데이터 날짜"와 "오늘 날짜" 차이가 크지 않으면 사용하도록 개선.
        
        # [Optimized Logic] 주말/휴일 고려 없이 단순 3일 이내면 캐시 사용 (API 호출 절약)
        if (today_date - last_data_date).days > 3:
             return None # 너무 오래됨 (재수집 필요)

        # 포맷 변환 및 리턴
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        df.index.name = 'Date'
        df.columns = ['Open', 'High', 'Low', 'Close']
        
        return df
        
    except Exception as e:
        # print(f"Cache read error: {e}")
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
        print(f"Cache save error for {ticker}: {e}")
        pass

def fetch_data(ticker, market, start_date='2020-01-01', scan_date=None):
    """
    데이터 가져오기 (캐시 -> pykrx)
    """
    # 캐시 확인
    cached_df = get_cached_data(ticker, start_date, scan_date=scan_date)
    if cached_df is not None:
        return cached_df, True
    
    # pykrx 사용
    try:
        from pykrx import stock
        import pytz
        
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
                df_yf = yf.download(yf_ticker, start=start_date, progress=False)
                
                if df_yf is None or df_yf.empty:
                    # 코스닥 시도
                    yf_ticker = f"{ticker}.KQ"
                    df_yf = yf.download(yf_ticker, start=start_date, progress=False)
                
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
            except Exception as e:
                # print(f"yfinance fallback error for {ticker}: {e}")
                pass
        
        if df is None or df.empty:
            return None, False
        
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
             return None, False

        save_to_cache(ticker, df)
        return df, False
        
    except Exception as e:
        # print(f"fetch_data error for {ticker}: {e}")
        return None, False

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
                    
                    # [NEW] ETF 필터링: 주요 ETF 브랜드 포함 시 제외
                    etf_keywords = [
                        'KODEX', 'TIGER', 'ACE', 'KBSTAR', 'SOL', 'RISE', 'ARIRANG', 
                        'HANARO', 'KINDEX', 'KOSEC', 'KOSEF', 'TREX', 'SMART', 'FOCUS', 'WOORI'
                    ]
                    if any(kw in name.upper() for kw in etf_keywords):
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
