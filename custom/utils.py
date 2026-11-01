import pandas as pd
import boto3
import os, sys, time, math, json
from .indicators import INDICATOR_REGISTRY
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
IST = ZoneInfo("Asia/Kolkata")

ALLOWED_INTERVALS = {
    "api": ["D", "W", "M"],
    "db":  ["D", "W", "M", "Q", "Y"],
}

STRATEGY_CONFIG = {
    "execution_time": "15:22",
    "daily_intervals": ("D", "W", "M", "Q"),
}

def get_date_range(interval: str, source: str | None = "api"):
    """Validate interval/source and return (start_date, end_date, source)."""
    source = source or "api"

    if source not in ALLOWED_INTERVALS:
        raise ValueError(f"Invalid source '{source}'. Use 'api' or 'db'.")

    if interval not in ALLOWED_INTERVALS[source]:
        raise ValueError(
            f"Interval '{interval}' is not allowed with source='{source}'. "
            f"Allowed: {', '.join(ALLOWED_INTERVALS[source])}"
        )

    now = datetime.now(IST)
    if interval == "D":
        start = now - timedelta(days=365)
    elif interval == "W":
        start = now - timedelta(days=365 * 3)
    elif interval == "M":
        start = now - timedelta(days=365 * 5)
    else:  # Q, Y
        start = datetime(2015, 1, 1, tzinfo=IST)

    return start.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d"), source

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

    last = working.iloc[-1]
    prev = working.iloc[-2] if len(working) >= 4 else None

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

def write_to_s3(bucket: str, key: str, body: bytes, content_type: str) -> None:
    print('write to s3 started')
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
    print('write to s3 completed')

def read_s3_object(bucket: str, key: str) -> set[str]:
    try:
        s3 = boto3.client("s3")
        resp = s3.get_object(Bucket=bucket, Key=key)
        return list(json.loads(resp["Body"].read().decode("utf-8")))
    except Exception:
        return list()
    
def strategy_exit():
        print("Markets are closed. Stopping all Strategies.")
        sys.exit(0)

def calculate_position_size(close: float, max_capital) -> int:
    """
    Allocate max_capital per trade.
    Returns 0 if price exceeds the allocation cap.
    """
    return math.floor(max_capital / close)