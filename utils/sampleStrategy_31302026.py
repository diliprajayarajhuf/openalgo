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
# sys.path.insert(
#     0,
#     str(Path(__file__).resolve().parent.parent / "indicators")
# )
from utils.index_constituent import NIFTY_50
from strategies.indicators.indicators import dema, tema, two_ut_bot, supertrend, three_horse_crow, INDICATOR_REGISTRY
from datetime import datetime
from zoneinfo import ZoneInfo

# Read API credentials and endpoints from environment.
# When this strategy is launched via OpenAlgo's /python runner,
# OPENALGO_API_KEY is injected by the platform and HOST_SERVER /
# WEBSOCKET_URL are inherited from OpenAlgo's .env file.
api_key = os.getenv('OPENALGO_API_KEY')
host    = os.getenv('HOST_SERVER', 'http://127.0.0.1:5000')
ws_url  = os.getenv('WEBSOCKET_URL', 'ws://127.0.0.1:8765')
# 'db' reads candles stored by OpenAlgo's Historify; 'api' asks the broker.
history_source = os.getenv('STRATEGY_HISTORY_SOURCE', 'db')
IST = ZoneInfo("Asia/Kolkata")

stock_cfg = {
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

if not api_key:
    print("Error: OPENALGO_API_KEY environment variable not set")
    exit(1)


# Set the strategy details and trading parameters
strategy = "EMA Crossover Python"
# nifty50_stocks = ["ADANIENT","ADANIPORTS","APOLLOHOSP","ASIANPAINT","AXISBANK","BAJAJ-AUTO","BAJFINANCE","BAJAJFINSV","BEL","BHARTIARTL","BSE","CIPLA","COALINDIA","DRREDDY","EICHERMOT","ETERNAL","GRASIM","HCLTECH","HDFCBANK","HDFCLIFE","HINDALCO","HINDUNILVR","ICICIBANK","INDIGO","INFY","ITC","JIOFIN","JSWSTEEL","KOTAKBANK","LT","M&M","MARUTI","MAXHEALTH","NESTLEIND","NTPC","ONGC","POWERGRID","RELIANCE","SBILIFE","SHRIRAMFIN","SBIN","SUNPHARMA","TCS","TATACONSUM","TMPV","TATASTEEL","TECHM","TITAN","TRENT","ULTRACEMCO"]
exchange = "NSE"
product = "CNC"
quantity = 10


# Set the API Key
client = api(api_key=api_key, host=host, ws_url=ws_url)


def _crossover_direction(last, prev, crossover: dict) -> str | None:
    left, right = crossover.get("left"), crossover.get("right")
    if not left or not right or prev is None:
        return None
    try:
        cl, cr = float(last[left]), float(last[right])
        pl, pr = float(prev[left]), float(prev[right])
    except (KeyError, TypeError, ValueError):
        return None
    if pl <= pr and cl > cr:
        return "buy"
    if pl >= pr and cl < cr:
        return "sell"
    return None

def _eval_group(group: dict, ind_direction: dict, last, prev) -> str | None:
    operator = group.get("operator", "AND").upper()
    votes = []

    for ind in group.get("indicators", []):
        votes.append(ind_direction.get(ind))

    crossover = group.get("crossover")
    if crossover:
        votes.append(_crossover_direction(last, prev, crossover))

    if not votes:
        return None

    if operator == "AND":
        if any(v is None for v in votes):
            return None
        unique = set(votes)
        return unique.pop() if len(unique) == 1 else None

    # OR: any non-None vote; all non-None must agree on direction
    non_none = [v for v in votes if v is not None]
    if not non_none:
        return None
    unique = set(non_none)
    return unique.pop() if len(unique) == 1 else None


def build_signals(df: pd.DataFrame, stock_cfg: dict) -> dict | None:
    """
    Evaluate all indicators, apply entry conditions, and return exactly ONE
    consolidated signal dict or None.

    entry_conditions with mode AND: all listed indicators must agree on direction.
    No entry_conditions (or empty): any single indicator firing is sufficient,
    but all firing indicators must agree on direction.

    If the required agreement isn't met, the candle is not silently dropped.
    Each configured indicator's persistent trend column (e.g. 2ut_trend,
    st_trend) is compared: if those trends disagree AND at least one of them
    just changed on this candle (vs. the previous candle), a single "sl"
    signal is returned for that candle. If the same disagreement already
    existed on the previous candle (no indicator flipped this candle), "sl"
    is not re-fired — this keeps "sl" a one-shot event per divergence,
    mirroring how the buy/sell columns only fire on the crossover candle.

    Returned dict shape:
      {
        "symbol":      str,
        "signal_type": "buy" | "sell" | "sl",
        "close":       float,
        "tsl":         float,          # most conservative: max for buy, min for sell
        "timestamp":   str,
        "indicators":  list[str],      # names of indicators that fired
      }
    """
    if df.empty:
        return None

    working = df.copy()
    if "ts" in working.columns:
        working["ts"] = pd.to_datetime(working["ts"])
        working = working.set_index("ts")
    else:
        working.index = pd.to_datetime(working.index)

    last = working.iloc[-2]
    prev = working.iloc[-3] if len(working) >= 4 else None

    ind_direction: dict[str, str | None] = {}
    ind_trend: dict[str, str | None] = {}
    ind_trend_prev: dict[str, str | None] = {}
    ind_tsl: dict[str, float] = {}

    for ind_cfg in stock_cfg.get("indicators", []):
        name = ind_cfg["name"]
        # if name not in SIGNAL_INDICATORS:
        #     continue
        entry = INDICATOR_REGISTRY.get(name)
        if entry is None:
            continue
        _, prefix = entry
        if f"{prefix}_tsl" not in working.columns:
            continue

        allowed = set(ind_cfg.get("signals", ["buy", "sell"]))

        buy_col  = f"{prefix}_buy"
        sell_col = f"{prefix}_sell"

        direction = None
        if "buy" in allowed and buy_col in working.columns and bool(last[buy_col]):
            direction = "buy"
        elif "sell" in allowed and sell_col in working.columns and bool(last[sell_col]):
            direction = "sell"

        ind_direction[name] = direction
        ind_tsl[name] = float(last[f"{prefix}_tsl"])

        trend_col = f"{prefix}_trend"
        trend_dir = None
        if trend_col in working.columns:
            try:
                trend_val = float(last[trend_col])
                trend_dir = "buy" if trend_val > 0 else "sell" if trend_val < 0 else None
            except (TypeError, ValueError):
                trend_dir = None
        ind_trend[name] = trend_dir

        prev_trend_dir = None
        if prev is not None and trend_col in working.columns:
            try:
                prev_trend_val = float(prev[trend_col])
                prev_trend_dir = "buy" if prev_trend_val > 0 else "sell" if prev_trend_val < 0 else None
            except (TypeError, ValueError):
                prev_trend_dir = None
        ind_trend_prev[name] = prev_trend_dir

    # An "sl" divergence is only newsworthy on the candle where it first
    # appears — if no indicator's trend changed since the previous candle,
    # the same disagreement already fired (or was already present) before.
    trend_is_fresh = prev is None or ind_trend_prev != ind_trend

    # --- Entry condition gating ---
    entry_cond = stock_cfg.get("entry_conditions") or {}

    # New format: { "operator": "AND", "groups": [...] }
    if "groups" in entry_cond:
        top_op = entry_cond.get("operator", "AND").upper()
        group_results = [_eval_group(g, ind_direction, last, prev) for g in entry_cond["groups"]]

        if top_op == "AND":
            if any(r is None for r in group_results):
                agreed = None
            else:
                unique = set(group_results)
                agreed = unique.pop() if len(unique) == 1 else None
        else:  # OR
            non_none = [r for r in group_results if r is not None]
            unique = set(non_none) if non_none else set()
            agreed = unique.pop() if len(unique) == 1 else None

        if agreed in ("buy", "sell"):
            signal_type      = agreed
            fired_indicators = [n for n, d in ind_direction.items() if d == agreed]
            for group, result in zip(entry_cond["groups"], group_results):
                if result == agreed and "crossover" in group:
                    co = group["crossover"]
                    fired_indicators.append(f"{co.get('left')}_x_{co.get('right')}")
        else:
            trends = {d for d in ind_trend.values() if d is not None}
            if len(trends) < 2 or not trend_is_fresh:
                return None
            signal_type      = "sl"
            fired_indicators = [n for n, d in ind_trend.items() if d is not None]

    else:
        # Legacy format: { "mode": "AND", "indicators": [...] }
        mode      = entry_cond.get("mode", "AND").upper()
        gate_inds = entry_cond.get("indicators", [])

        if gate_inds and mode == "AND":
            votes  = {ind_direction.get(ind) for ind in gate_inds}
            agreed = votes.pop() if len(votes) == 1 and None not in votes else None
            if agreed in ("buy", "sell"):
                signal_type      = agreed
                fired_indicators = [ind for ind in gate_inds if ind_direction.get(ind) == agreed]
            else:
                trends = {ind_trend.get(ind) for ind in gate_inds if ind_trend.get(ind) is not None}
                if len(trends) < 2 or not trend_is_fresh:
                    return None
                signal_type      = "sl"
                fired_indicators = [ind for ind in gate_inds if ind_trend.get(ind) is not None]
        else:
            trends = {d for d in ind_trend.values() if d is not None}
            if len(trends) > 1 and trend_is_fresh:
                signal_type      = "sl"
                fired_indicators = [n for n, d in ind_trend.items() if d is not None]
            else:
                fired_indicators = [n for n, d in ind_direction.items() if d is not None]
                if not fired_indicators:
                    return None
                directions = {ind_direction[n] for n in fired_indicators}
                if len(directions) != 1:
                    return None
                signal_type = directions.pop()

    fired_tsls = [ind_tsl[n] for n in fired_indicators if n in ind_tsl]
    if signal_type == "buy":
        tsl = max(fired_tsls) if fired_tsls else float(last["close"])
    elif signal_type == "sell":
        tsl = min(fired_tsls) if fired_tsls else float(last["close"])
    else:  # "sl" — partial/conflicting indicator activity
        tsl = fired_tsls[0] if fired_tsls else float(last["close"])

    return {
        "symbol":      str(last["symbol"]),
        "signal_type": signal_type,
        "close":       float(last["close"]),
        "tsl":         tsl,
        "timestamp":   last.name.isoformat(),
        "indicators":  fired_indicators,
    }

def ema_strategy(symbol):
    """
    The EMA crossover trading strategy.
    """
    position = 0
    last_run_date = None

    try:
        # Dynamic date range: 7 days back to today
        end_date = datetime.now(IST).strftime("%Y-%m-%d")
        start_date = (datetime.now(IST) - timedelta(days=52)).strftime("%Y-%m-%d")

        # Fetch 1-minute historical data using OpenAlgo
        df = client.history(
            symbol=symbol,
            exchange=exchange,
            interval="D",
            start_date=start_date,
            end_date=end_date,
            source=history_source
        )
        if not isinstance(df, pd.DataFrame):
            print(f"History request failed for {symbol}: {df}")
            return
        df['symbol']= symbol
        print(df.tail(20))

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
        df = two_ut_bot(df)
        df = three_horse_crow(df)
        df = supertrend(df)
        print(df.tail(10))
        df1 = build_signals(df, stock_cfg)
        print('dada',df1)
        # sys.exit("Planned Exit")
        # import logging
        # logging.basicConfig(
        #     level=logging.INFO,
        #     format="%(asctime)s - %(levelname)s - %(message)s"
        # )

        # logger = logging.getLogger(__name__)

        # Use the last two completed candles
        # previous = df.iloc[-3]
        # current = df.iloc[-2]
        # buy = (
        #     previous["dema"] <= previous["tema"]
        #     and current["dema"] > current["tema"]
        # )

        # # Sell when 5 DEMA crosses below 20 TEMA
        # sell = (
        #     previous["dema"] >= previous["tema"]
        #     and current["dema"] < current["tema"]
        # )


        # Execute Buy Order
        # if buy and position <= 0:
        #     position = quantity
        #     status = client.analyzerstatus()

        #     if (
        #         status.get("status") != "success"
        #         or status.get("data", {}).get("analyze_mode") is not True
        #     ):
        #         print("Analyzer Mode is OFF. Order blocked.")
        #         return
        #     print(f"Analyzer Mode is {status}. Order blocked.")
        #     response = client.placesmartorder(
        #         strategy=strategy,
        #         symbol=symbol,
        #         action="BUY",
        #         exchange=exchange,
        #         price_type="MARKET",
        #         product=product,
        #         quantity=quantity,
        #         position_size=position
        #     )
        #     print("Buy Order Response:", response)

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
    # while True:
    now = datetime.now(IST)
    print(f"{strategy} running at {now}")
    # Run only once at 3:22 PM IST
    # if now.hour != 15 or now.minute != 22:
    #     print(f"skipping {strategy} at {now}")
    #     time.sleep(1)
    #     continue
    for stock in NIFTY_50:
        # print(f"Starting {stock} {fast_period}/{slow_period} EMA Crossover Strategy...")
        ema_strategy(stock)
        # print(f"Completed {stock} {fast_period}/{slow_period} EMA Crossover Strategy...")

