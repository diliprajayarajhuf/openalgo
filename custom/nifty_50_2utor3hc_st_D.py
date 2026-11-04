#!/usr/bin/env python
"""
Simple EMA Crossover Strategy Example
This strategy demonstrates how to integrate with OpenAlgo API
"""
from openalgo import api
import pandas as pd
import numpy as np
import time, json
from pathlib import Path
import os, sys
# from .index_constituent import NIFTY_50
# from .indicators import dema, tema, two_ut_bot, supertrend, three_horse_crow
# from .utils import build_signals, get_date_range, write_to_s3, read_s3_object, strategy_exit, STRATEGY_CONFIG
# from .nse_utils import is_last_trading_day_of_week, is_last_trading_day_of_month
# from .orders import place_order
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

# Add project root (/app), not /app/custom
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Imports
from custom.index_constituent import NIFTY_50
from custom.indicators import (
    dema,
    tema,
    two_ut_bot,
    supertrend,
    three_horse_crow,
)
from custom.utils import (
    build_signals,
    get_date_range,
    write_to_s3,
    read_s3_object,
    strategy_exit,
    STRATEGY_CONFIG,
)
from custom.nse_utils import (
    is_last_trading_day_of_week,
    is_last_trading_day_of_month,
)
from custom.orders import place_order
from datetime import datetime, time as dt_time, timedelta, date
from zoneinfo import ZoneInfo
IST = ZoneInfo("Asia/Kolkata")

# S3 bucket settings
BUCKET = 'us-east-1-openalgo'
STRATEGY_FOLDER = 'strategies'
ORDER_FOLDER = 'orders'

# Strategy Settings
EXIT_TIME = dt_time(16, 0)
INTERVAL = 'D'
SOURCE = 'api'

# Trade Settings
MAX_CAPITAL_TRADE = 10000
EXCHANGE = "NSE"
PRODUCT = "CNC"

strategy_indicator_cfg = {
    "indicators": [
        {"name": "2ut", "signals": ["buy", "sell"]},
        {"name": "3hc", "signals": ["buy", "sell"]},
        {"name": "supertrend", "signals": ["buy", "sell"]}
    ],
    "entry_conditions": {
        "operator": "OR",
        "groups": [
            {
                "operator": "AND",
                "indicators": ["2ut", "supertrend"]
            },
            {
                "operator": "AND",
                "indicators": ["3hc", "supertrend"]
            }
        ]
    }
}

api_key = os.getenv('OPENALGO_API_KEY', 'f0db54b37d92f713f0f5ad51426fae5fc7f3af3f7822bb21c1f0b66c3585a705')
host    = os.getenv('HOST_SERVER', 'http://127.0.0.1:5000')
ws_url  = os.getenv('WEBSOCKET_URL', 'ws://127.0.0.1:8765')

if not api_key:
    print("Error: OPENALGO_API_KEY environment variable not set")
    exit(1)

# Set the API Key
client = api(api_key=api_key, host=host, ws_url=ws_url)

signals = []

def execute_strategy(symbol, interval='D', source='api'):
    try:
        start_date, end_date, source = get_date_range(interval=interval, source=source)

        df = client.history(
            symbol=symbol,
            exchange=EXCHANGE,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            source=source
        )
        if not isinstance(df, pd.DataFrame):
            print(f"History request failed for {symbol}: {df}")
            return
        df['symbol']= symbol
        
        if df.empty:
            print("DataFrame is empty. Retrying...")
            time.sleep(15)
            return

        # Verify required columns
        if 'close' not in df.columns:
            raise KeyError("Missing 'close' column in DataFrame")
        
        df['close'] = df['close'].round(2)
        df = two_ut_bot(df)
        df = three_horse_crow(df)
        df = supertrend(df)
        print(df.tail(10))
        signal = build_signals(df, strategy_indicator_cfg)
        if signal:
            signals.append(signal)
            print('signals',signal)
    except Exception as e:
        print(f"Error in strategy: {str(e)}")
        time.sleep(15)
        return
    
def get_ltp(symbol, exchange=EXCHANGE):
    """Fetch the last traded price from OpenAlgo."""
    response = client.quotes(symbol=symbol, exchange=exchange)
    print(f"response {response}")
    if response.get("status") == "success":
        return response["data"]["ltp"]
    print(f"Could not fetch LTP: {response}")
    return None

if __name__ == "__main__":

    if INTERVAL.upper().endswith('W') and not is_last_trading_day_of_week(datetime.now(IST).date()):
        print(f"Skipping weekly signals — {date.today()} is not the last trading day of the week")
        sys.exit(0)
    if INTERVAL.upper().endswith(("M", "Q")) and not is_last_trading_day_of_month(datetime.now(IST).date()):
        print(f"Skipping monthly signals — {date.today()} is not the last trading day of the month")
        sys.exit(0)
    strategy = Path(__file__).stem
    print(strategy)
    now = datetime.now(IST)
    # now = datetime.fromisoformat("2026-11-01 15:15:00.880580+05:30")
    print(f"{strategy} running at {now}")
    if (INTERVAL.upper().endswith(STRATEGY_CONFIG["daily_intervals"])and now.strftime("%H:%M") != STRATEGY_CONFIG["execution_time"]):
        execution_time = datetime.combine(now.date(),datetime.strptime(STRATEGY_CONFIG["execution_time"], "%H:%M").time(),tzinfo=IST)
        print("execution_time",execution_time)
        if now < execution_time:
            wait_seconds = max(0, (execution_time - now).total_seconds() - 5)
            print(f"Waiting {wait_seconds:.0f} seconds until {execution_time:%H:%M}")
            time.sleep(wait_seconds)
        elif now >= execution_time + timedelta(minutes=1):
            strategy_exit()
    if datetime.now(IST).time() >= EXIT_TIME:
            strategy_exit()
    for stock in NIFTY_50:
        print(f"Starting {stock} {strategy} strategy ...")
        execute_strategy(stock, INTERVAL, SOURCE)
        print(f"Completed {stock} {strategy} strategy...")
        print()
        print()
        print()
    if signals:
        now_ist = datetime.now(IST)
        date_str = now_ist.strftime("%Y-%m-%d")
        ts_str = now_ist.strftime("%Y%m%dT%H%M%S%f")
        print(f"signals is {signals}")
        s3_order_key = f"{ORDER_FOLDER}/{strategy}/{date_str}/executed_orders.json"
        already_executed_orders = read_s3_object(BUCKET,s3_order_key)
        signals = [signal for signal in signals if signal["symbol"] not in already_executed_orders]
        print(f"signals is {signals}")
        placed_order = place_order(client, strategy, EXCHANGE, PRODUCT, MAX_CAPITAL_TRADE, signals)
        print(f"placed_order {placed_order}")
        if place_order:
            already_executed_orders.append(placed_order)
            write_to_s3(BUCKET, s3_order_key, json.dumps(already_executed_orders, indent=2).encode("utf-8"), "application/json")
        s3_strategy_key = f"{STRATEGY_FOLDER}/{strategy}/{date_str}/executed_{ts_str}.json"
        write_to_s3(BUCKET, s3_strategy_key, json.dumps(signals, indent=2).encode("utf-8"), "application/json")