import numpy as np
import pandas as pd


def three_horse_crow(df: pd.DataFrame, prefix: str = "3hc", swing: int = 3) -> pd.DataFrame:
    df = df.copy()

    tsl_col = f"{prefix}_tsl"
    buy_col = f"{prefix}_buy"
    sell_col = f"{prefix}_sell"

    df["res"] = df["high"].rolling(window=swing, min_periods=swing).max()
    df["sup"] = df["low"].rolling(window=swing, min_periods=swing).min()

    df["res_prev"] = df["res"].shift(1)
    df["sup_prev"] = df["sup"].shift(1)

    df["avd"] = np.where(
        df["close"] > df["res_prev"],
        1,
        np.where(df["close"] < df["sup_prev"], -1, 0),
    )

    df["avn"] = df["avd"].astype("float64").replace(0, np.nan).ffill().fillna(0).astype("int8")

    df[tsl_col] = np.where(df["avn"] == 1, df["sup"], df["res"])

    df["prev_close"] = df["close"].shift(1)
    df["prev_tsl"] = df[tsl_col].shift(1)

    df[buy_col] = (df["close"] > df[tsl_col]) & (df["prev_close"] <= df["prev_tsl"])
    df[sell_col] = (df["close"] < df[tsl_col]) & (df["prev_close"] >= df["prev_tsl"])
    df[f"{prefix}_trend"] = np.where(df["close"] > df[tsl_col], 1, -1)

    return df.drop(
        columns=[
            "oi",
            "volume",
            "res",
            "sup",
            "res_prev",
            "sup_prev",
            "avd",
            "avn",
            "prev_close",
            "prev_tsl",
        ],
        errors="ignore",
    )


def two_ut_bot(
    df: pd.DataFrame,
    prefix: str = "2ut",
    key_value: float = 1.25,
    atr_period: int = 10,
    use_heikin_ashi: bool = False,
) -> pd.DataFrame:
    data = df.copy()

    tsl_col = f"{prefix}_tsl"
    buy_col = f"{prefix}_buy"
    sell_col = f"{prefix}_sell"

    if use_heikin_ashi:
        ha = pd.DataFrame(index=data.index)

        ha["close"] = (data["open"] + data["high"] + data["low"] + data["close"]) / 4
        ha["open"] = (data["open"].shift(1) + data["close"].shift(1)) / 2
        ha["high"] = ha[["open", "close"]].join(data["high"]).max(axis=1)
        ha["low"] = ha[["open", "close"]].join(data["low"]).min(axis=1)

        src = ha["close"]

    else:
        src = data["close"]

    high = data["high"]
    low = data["low"]
    close = data["close"]

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)

    atr = tr.rolling(atr_period).mean()
    n_loss = key_value * atr

    trailing_stop = np.zeros(len(data))
    src_values = src.to_numpy()
    n_loss_values = n_loss.to_numpy()

    # for i in range(1, len(data)):
    #     prev = trailing_stop[i - 1]

    #     if src.iloc[i] > prev and src.iloc[i - 1] > prev:
    #         trailing_stop[i] = max(prev, src.iloc[i] - n_loss.iloc[i])

    #     elif src.iloc[i] < prev and src.iloc[i - 1] < prev:
    #         trailing_stop[i] = min(prev, src.iloc[i] + n_loss.iloc[i])

    #     elif src.iloc[i] > prev:
    #         trailing_stop[i] = src.iloc[i] - n_loss.iloc[i]

    #     else:
    #         trailing_stop[i] = src.iloc[i] + n_loss.iloc[i]
    
    for i in range(1, len(data)):

        prev = trailing_stop[i - 1]
        current_src = src_values[i]
        previous_src = src_values[i - 1]
        current_loss = n_loss_values[i]

        if current_src > prev and previous_src > prev:
            trailing_stop[i] = max(prev, current_src - current_loss)
        elif current_src < prev and previous_src < prev:
            trailing_stop[i] = min(prev, current_src + current_loss)
        elif current_src > prev:
            trailing_stop[i] = current_src - current_loss
        else:
            trailing_stop[i] = current_src + current_loss

    trailing_stop = pd.Series(trailing_stop, index=data.index)

    result = data.copy()

    result[tsl_col] = trailing_stop
    result["src"] = src
    result["prev_src"] = src.shift(1)
    result["prev_close"] = result["close"].shift(1)
    result["prev_tsl"] = trailing_stop.shift(1)

    # result[buy_col] = (result["close"] > result[tsl_col]) & (result["prev_close"] <= result["prev_tsl"])
    # result[sell_col] = (result["close"] < result[tsl_col]) & (result["prev_close"] >= result["prev_tsl"])
    # result[f"{prefix}_trend"] = np.where(result["close"] > result[tsl_col], 1.0, -1.0)
    # result = result.drop(columns=["prev_close", "prev_tsl"], errors="ignore")

    result[buy_col] = ((result["src"] > result[tsl_col]) & (result["prev_src"] <= result["prev_tsl"]))
    result[sell_col] = ((result["src"] < result[tsl_col]) & (result["prev_src"] >= result["prev_tsl"]))
    result[f"{prefix}_trend"] = np.where(result["src"] > result[tsl_col],1.0,-1.0,)

    result = result.drop(columns=["src", "prev_src", "prev_tsl"],errors="ignore",)


    if "oi" in df.columns:
        result = result.drop(columns=["oi"], errors="ignore")

    return result


def supertrend(
    df: pd.DataFrame,
    prefix: str = "st",
    atr_period: int = 10,
    factor: float = 1.25,
) -> pd.DataFrame:
    data = df.copy()

    tsl_col = f"{prefix}_tsl"
    buy_col = f"{prefix}_buy"
    sell_col = f"{prefix}_sell"
    trend_col = f"{prefix}_trend"

    high = data["high"]
    low = data["low"]
    close = data["close"]

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)

    atr = tr.rolling(atr_period).mean()

    hl2 = (high + low) / 2
    basic_upper = hl2 + factor * atr
    basic_lower = hl2 - factor * atr

    n = len(data)

    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    direction = np.full(n, np.nan)
    st_vals = np.full(n, np.nan)

    for i in range(1, n):
        bu = basic_upper.iloc[i]
        bl = basic_lower.iloc[i]

        prev_upper = final_upper[i - 1]
        prev_lower = final_lower[i - 1]
        prev_close = close.iloc[i - 1]

        final_upper[i] = bu if np.isnan(prev_upper) or bu < prev_upper or prev_close > prev_upper else prev_upper
        final_lower[i] = bl if np.isnan(prev_lower) or bl > prev_lower or prev_close < prev_lower else prev_lower

        prev_st = st_vals[i - 1]

        if np.isnan(prev_st):
            direction[i] = 1
            st_vals[i] = final_lower[i]

        elif prev_st == final_upper[i - 1]:
            direction[i] = 1 if close.iloc[i] > final_upper[i] else -1

        else:
            direction[i] = -1 if close.iloc[i] < final_lower[i] else 1

        st_vals[i] = final_lower[i] if direction[i] == 1 else final_upper[i]

    data[tsl_col] = st_vals
    data["_st_dir"] = direction

    prev_dir = data["_st_dir"].shift(1)

    data[buy_col] = (data["_st_dir"] == 1) & (prev_dir == -1)
    data[sell_col] = (data["_st_dir"] == -1) & (prev_dir == 1)
    data[trend_col] = data["_st_dir"]

    data = data.drop(columns=["_st_dir"], errors="ignore")

    if "oi" in df.columns:
        data = data.drop(columns=["oi"], errors="ignore")

    return data


def dema(df: pd.DataFrame, prefix: str = "dema", period: int = 5, column: str = "close") -> pd.DataFrame:
    df = df.copy()

    ema1 = df[column].ewm(span=period, adjust=False).mean()
    ema2 = ema1.ewm(span=period, adjust=False).mean()

    df[prefix] = (2 * ema1) - ema2

    return df


def tema(df: pd.DataFrame, prefix: str = "tema", period: int = 20, column: str = "close") -> pd.DataFrame:
    df = df.copy()

    ema1 = df[column].ewm(span=period, adjust=False).mean()
    ema2 = ema1.ewm(span=period, adjust=False).mean()
    ema3 = ema2.ewm(span=period, adjust=False).mean()

    df[prefix] = (3 * ema1) - (3 * ema2) + ema3

    return df


def rsi(df: pd.DataFrame, prefix: str = "rsi", period: int = 14, column: str = "close") -> pd.DataFrame:
    df = df.copy()

    delta = df[column].diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    average_gain = gain.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    average_loss = loss.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    rs = average_gain / average_loss

    df[prefix] = 100 - (100 / (1 + rs))

    return df


def sma(df: pd.DataFrame, prefix: str = "sma", period: int = 20, column: str = "close") -> pd.DataFrame:
    df = df.copy()

    df[prefix] = df[column].rolling(window=period, min_periods=period).mean()

    return df

INDICATOR_REGISTRY: dict[str, tuple] = {
    "3hc":        (three_horse_crow, "3hc"),
    "2ut":        (two_ut_bot,       "2ut"),
    "supertrend": (supertrend,       "st"),
    "dema":       (dema,       "dema"),
    "tema":       (tema,       "tema"),
}