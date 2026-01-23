
import pandas as pd
from pykrx import stock
import yfinance as yf
from datetime import datetime
import pytz

def test_fetch(ticker, name):
    print(f"\n--- Testing {name} ({ticker}) ---")
    start_date = "2020-01-31"
    end_date = datetime.now().strftime('%Y%m%d')
    start_date_pykrx = datetime.strptime(start_date, '%Y-%m-%d').strftime('%Y%m%d')

    print(f"Pykrx ({start_date_pykrx} to {end_date}):")
    try:
        df_pykrx = stock.get_market_ohlcv_by_date(start_date_pykrx, end_date, ticker)
        if df_pykrx is not None and not df_pykrx.empty:
            print(f"  Success: {len(df_pykrx)} rows. Last date: {df_pykrx.index[-1]}")
        else:
            print(f"  Failed: Empty DataFrame")
    except Exception as e:
        print(f"  Failed with error: {e}")

    print(f"Yfinance (.KS):")
    try:
        df_yf = yf.download(f"{ticker}.KS", start=start_date, progress=False)
        if df_yf is not None and not df_yf.empty:
            print(f"  Success: {len(df_yf)} rows. Last date: {df_yf.index[-1]}")
        else:
            print(f"  Failed: Empty DataFrame")
    except Exception as e:
        print(f"  Failed with error: {e}")

    print(f"Yfinance (.KQ):")
    try:
        df_yf = yf.download(f"{ticker}.KQ", start=start_date, progress=False)
        if df_yf is not None and not df_yf.empty:
            print(f"  Success: {len(df_yf)} rows. Last date: {df_yf.index[-1]}")
        else:
            print(f"  Failed: Empty DataFrame")
    except Exception as e:
        print(f"  Failed with error: {e}")

tickers = [
    ("006260", "LS"),
    ("128940", "한미약품"),
    ("004370", "농심"),
    ("069620", "대웅")
]

for t, n in tickers:
    test_fetch(t, n)
