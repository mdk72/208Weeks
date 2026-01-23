from pykrx import stock
import yfinance as yf
from datetime import datetime
import pandas as pd
import sys
import analyzer

# Windows console encoding fix
import io
sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

ticker = "047040"
name = "대우건설"
start_date = "2020-01-01"
end_date = datetime.now().strftime("%Y-%m-%d")

print(f"--- Backtest Simulation for {ticker} (Daewoo E&C) ---")

config = {
    'buy_breakout': True,
    'buy_ma20': True,
    'buy_segment': "Segment C (B/C~C/D)",
    'exit_target': "D/E Boundary", # Default assumption
    'exit_method': "목표가 도달 시 즉시 매도", # Default
    'stop_loss_pct': 10, # Default
    'start_date': start_date,
    'end_date': end_date,
    'lookback': 208,
    'bc_breakout_days': 60
}

def run_backtest(source_name, df):
    if df is None or df.empty:
        print(f"[{source_name}] Data fetch failed.")
        return

    # Column/Index fix
    if source_name == 'Pykrx':
         df = df.rename(columns={'시가': 'Open', '고가': 'High', '저가': 'Low', '종가': 'Close', '거래량': 'Volume'})
    
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None: df.index = df.index.tz_localize(None)
    
    # Run Backtest
    print(f"\n[{source_name}] Running process_backtest_stock...")
    res = analyzer.process_backtest_stock(ticker, name, "KOSPI", config, pre_fetched_df=df)
    
    if res and res.get('Trades', 0) > 0:
        print(f"✅ [{source_name}] Backtest Result: {res['Trades']} Trades")
        print(f"   - Recent Buy: {res['Recent Buy']}")
        print(f"   - Recent Sell: {res['Recent Sell']}")
        print(f"   - Win Rate: {res['Win Rate (%)']:.1f}%")
    else:
        print(f"❌ [{source_name}] No trades found.")

# 1. Pykrx Test
try:
    s = start_date.replace("-", "")
    e = end_date.replace("-", "")
    df_pykrx = stock.get_market_ohlcv_by_date(s, e, ticker)
    run_backtest("Pykrx", df_pykrx)
except Exception as e:
    print(f"[Pykrx] Execution Error: {e}")

# 2. Yfinance Test
try:
    df_yf = yf.download(f"{ticker}.KS", start=start_date, progress=False)
    if df_yf is not None:
         if df_yf.columns.nlevels > 1: df_yf.columns = df_yf.columns.droplevel(1)
         df_yf = df_yf.rename(columns={'Open': 'Open', 'High': 'High', 'Low': 'Low', 'Close': 'Close', 'Volume': 'Volume'})
    run_backtest("Yfinance", df_yf)
except Exception as e:
    print(f"[Yfinance] Execution Error: {e}")
