
import pandas as pd
from data_loader import fetch_data
from datetime import datetime
import pytz

stocks = [
    ('006260', 'LS'),
    ('128940', '한미약품'),
    ('004370', '농심'),
    ('069620', '대웅제약')
]

kst = pytz.timezone('Asia/Seoul')
scan_date = datetime.now(kst).date()
lookback_sel = 208
fetch_start_date = (scan_date - pd.Timedelta(weeks=int(lookback_sel * 1.5))).strftime('%Y-%m-%d')

print(f"Scan Date: {scan_date}")
print(f"Fetch Start Date: {fetch_start_date}")
print("-" * 30)

for code, name in stocks:
    print(f"Testing {name} ({code})...")
    try:
        df, from_cache = fetch_data(code, "KOSPI", start_date=fetch_start_date, scan_date=scan_date)
        if df is not None:
            print(f"  Result: Success! Rows: {len(df)}, From Cache: {from_cache}")
            # Check for insufficient data/history logic like in app.py
            df_full_for_chart = df.copy()
            target_date = pd.Timestamp(scan_date)
            df_until_scan = df[df.index <= target_date]
            
            if df_until_scan.empty:
                print("  Status: Skip (Before IPO)")
            else:
                df_weekly_check = df_until_scan.resample('W').agg({'Close': 'last'})
                if len(df_weekly_check) < lookback_sel:
                    print(f"  Status: Skip (Insufficient History: {len(df_weekly_check)} < {lookback_sel} weeks)")
                else:
                    print("  Status: OK (Passed all app.py checks)")
        else:
            print(f"  Result: FAILED (fetch_data returned None)")
    except Exception as e:
        print(f"  Error: {e}")
    print("-" * 30)
