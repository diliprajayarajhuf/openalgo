#!/usr/bin/env python
"""
Simple EMA Crossover Strategy Example
This strategy demonstrates how to integrate with OpenAlgo API
"""
from openalgo import api
import pandas as pd
import numpy as np
import time
import threading
from datetime import datetime, timedelta
import os, sys
from pathlib import Path
# from strategies.indicators.indicators import dema, tema
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "indicators")
)

from indicators import dema, tema
from datetime import datetime
from zoneinfo import ZoneInfo

# Read API credentials and endpoints from environment.
# When this strategy is launched via OpenAlgo's /python runner,
# OPENALGO_API_KEY is injected by the platform and HOST_SERVER /
# WEBSOCKET_URL are inherited from OpenAlgo's .env file.
api_key = os.getenv('OPENALGO_API_KEY', '2df5a8438b75aec4067d7ce239f8162899dc71a72b175f24060622ed4beb28b4')
host    = os.getenv('HOST_SERVER', 'http://127.0.0.1:5000')
ws_url  = os.getenv('WEBSOCKET_URL', 'ws://127.0.0.1:8765')

if not api_key:
    print("Error: OPENALGO_API_KEY environment variable not set")
    exit(1)


# Set the strategy details and trading parameters
strategy = "EMA Crossover Python"
nifty50_stocks = ["ADANIENT","ADANIPORTS","APOLLOHOSP","ASIANPAINT","AXISBANK","BAJAJ-AUTO","BAJFINANCE","BAJAJFINSV","BEL","BHARTIARTL","BSE","CIPLA","COALINDIA","DRREDDY","EICHERMOT","ETERNAL","GRASIM","HCLTECH","HDFCBANK","HDFCLIFE","HINDALCO","HINDUNILVR","ICICIBANK","INDIGO","INFY","ITC","JIOFIN","JSWSTEEL","KOTAKBANK","LT","M&M","MARUTI","MAXHEALTH","NESTLEIND","NTPC","ONGC","POWERGRID","RELIANCE","SBILIFE","SHRIRAMFIN","SBIN","SUNPHARMA","TCS","TATACONSUM","TMPV","TATASTEEL","TECHM","TITAN","TRENT","ULTRACEMCO"]
exchange = "NSE"
product = "CNC"
quantity = 10

# EMA periods
fast_period = 5
slow_period = 10

# Set the API Key
client = api(api_key=api_key, host=host, ws_url=ws_url)

def ema_strategy(symbol):
    """
    The EMA crossover trading strategy.
    """
    position = 0
    last_run_date = None

    try:
        # Dynamic date range: 7 days back to today
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=52)).strftime("%Y-%m-%d")

        # Fetch 1-minute historical data using OpenAlgo
        df = client.history(
            symbol=symbol,
            exchange=exchange,
            interval="D",
            start_date=start_date,
            end_date=end_date
        )

        # Check for valid data
        if df.empty:
            print("DataFrame is empty. Retrying...")
            time.sleep(15)
            return

        # Verify required columns
        if 'close' not in df.columns:
            raise KeyError("Missing 'close' column in DataFrame")

        # Round the close column
        df['close'] = df['close'].round(2)

        # Calculate EMAs and signals
        # signals = calculate_ema_signals(df)
        df = dema(df)
        df = tema(df)
        print(df.tail(2))

        # Use the last two completed candles
        previous = df.iloc[-3]
        current = df.iloc[-2]
        buy = (
            previous["dema"] <= previous["tema"]
            and current["dema"] > current["tema"]
        )

        # Sell when 5 DEMA crosses below 20 TEMA
        sell = (
            previous["dema"] >= previous["tema"]
            and current["dema"] < current["tema"]
        )


        # Execute Buy Order
        if buy and position <= 0:
            position = quantity
            status = client.analyzerstatus()

            if (
                status.get("status") != "success"
                or status.get("data", {}).get("analyze_mode") is not True
            ):
                print("Analyzer Mode is OFF. Order blocked.")
                return
            print(f"Analyzer Mode is {status}. Order blocked.")
            response = client.placesmartorder(
                strategy=strategy,
                symbol=symbol,
                action="BUY",
                exchange=exchange,
                price_type="MARKET",
                product=product,
                quantity=quantity,
                position_size=position
            )
            print("Buy Order Response:", response)

        # Execute Sell Order
        # elif sell and position >= 0:
        #     position = quantity * -1
        #     response = client.placesmartorder(
        #         strategy=strategy,
        #         symbol=symbol,
        #         action="SELL",
        #         exchange=exchange,
        #         price_type="MARKET",
        #         product=product,
        #         quantity=quantity,
        #         position_size=position
        #     )
        #     print("Sell Order Response:", response)

        # Log strategy information
        print("\nStrategy Status:")
        print("-" * 50)
        print(f"Position: {position}")
        print(f"LTP: {df['close'].iloc[-1]}")
        print("-" * 50)

    except Exception as e:
        print(f"Error in strategy: {str(e)}")
        time.sleep(15)
        return


if __name__ == "__main__":
    while True:
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        print(f"{strategy} running at {now}")
        # Run only once at 3:22 PM IST
        # if now.hour != 15 or now.minute != 22:
        #     print(f"skipping {strategy} at {now}")
        #     time.sleep(1)
        #     continue
        for stock in nifty50_stocks:
            print(f"Starting {stock} {fast_period}/{slow_period} EMA Crossover Strategy...")
            ema_strategy(stock)
            print(f"Completed {stock} {fast_period}/{slow_period} EMA Crossover Strategy...")

