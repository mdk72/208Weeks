import pandas as pd
from pykrx import stock
import yfinance as yf
from datetime import datetime
import pytz

def test_fetch(ticker, name):
    print(f"\n--- Testing {name} ({ticker}) ---")
    kst = pytz.timezone('Asia/Seoul')
    end_date = datetime.now(kst).strftime('%Y%m%d')
    start_date_pykrx = "20170101" # Ensuring long enough history
    start_date_yf = "2017-01-01"

    # 1. Test Pykrx
    print(f"Testing Pykrx...")
    try:
        df_pykrx = stock.get_market_ohlcv_by_date(start_date_pykrx, end_date, ticker)
        if df_pykrx is not None and not df_pykrx.empty:
            print(f"  Pykrx Success: {len(df_pykrx)} rows")
        else:
            print(f"  Pykrx Failed: Empty result")
    except Exception as e:
        print(f"  Pykrx Error: {e}")

    # 2. Test Yfinance
    print(f"Testing Yfinance...")
    try:
        yf_ticker = f"{ticker}.KS"
        df_yf = yf.download(yf_ticker, start=start_date_yf, progress=False)
        if df_yf is not None and not df_yf.empty:
            print(f"  Yfinance Success: {len(df_yf)} rows")
        else:
            print(f"  Yfinance Failed: Empty result")
    except Exception as e:
        print(f"  Yfinance Error: {e}")

stocks = [
    {'Code': '006260', 'Name': 'LS'},
    {'Code': '128940', 'Name': '한미약품'},
    {'Code': '004370', 'Name': '농심'},
    {'Code': '069620', 'Name': '대웅제약'}
]

for s in stocks:
    test_fetch(s['Code'], s['Name'])
