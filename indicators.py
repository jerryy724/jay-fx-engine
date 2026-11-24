"""
indicators.py - market data download and indicator maths for the FX engine.
Same tested maths as the Gold engine (Wilder RSI/ATR/ADX, true EMAs).
No trading decisions live here.
"""

from datetime import datetime, timezone, timedelta

import data_client


# ============================================================
# TIME AND MARKET DATA
# ============================================================

def parse_bar_time(value):
    ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def clean_row(row):
    try:
        bar = {
            "datetime": parse_bar_time(row["datetime"]).isoformat(),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        }
    except (KeyError, TypeError, ValueError):
        return None

    if bar["high"] < bar["low"]:
        return None
    if not (bar["low"] <= bar["open"] <= bar["high"]):
        return None
    if not (bar["low"] <= bar["close"] <= bar["high"]):
        return None

    return bar


def fetch_bars(symbol, interval="1h", outputsize=220, end_date=None):
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "order": "ASC",
        "timezone": "UTC",
        "format": "JSON",
    }

    if end_date:
        params["end_date"] = end_date

    data = data_client.twelvedata_get("time_series", params, timeout=60)

    if not isinstance(data, dict) or "values" not in data:
        raise RuntimeError(
            f"Unexpected Twelve Data response for {symbol} {interval}: {data}"
        )

    bars = [clean_row(row) for row in data["values"]]
    unique = {b["datetime"]: b for b in bars if b}

    return [unique[key] for key in sorted(unique)]


def closed_bars(bars, interval_hours, now=None):
    now = now or datetime.now(timezone.utc)
    result = []

    for bar in bars:
        try:
            start = parse_bar_time(bar["datetime"])
            if start + timedelta(hours=interval_hours) <= now:
                result.append(bar)
        except (KeyError, TypeError, ValueError):
            continue

    return result


# ============================================================
# EMA, RSI, ATR (Wilder)
# ============================================================

def ema_series(values, period):
    result = [None] * len(values)

    if len(values) < period:
        return result

    multiplier = 2.0 / (period + 1.0)
    current = sum(values[:period]) / period
    result[period - 1] = current

    for i in range(period, len(values)):
        current = values[i] * multiplier + current * (1.0 - multiplier)
        result[i] = current

    return result


def ema(values, period):
    series = ema_series(values, period)

    if not series or series[-1] is None:
        raise ValueError(f"Not enough data for EMA{period}")

    return float(series[-1])


def wilder_average(values, period):
    if len(values) < period:
        raise ValueError(f"Not enough data for Wilder average {period}")

    current = sum(values[:period]) / period

    for value in values[period:]:
        current = ((current * (period - 1)) + value) / period

    return current


def rsi(closes, period=14):
    if len(closes) <= period:
        raise ValueError("Not enough data for RSI")

    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(c, 0.0) for c in changes]
    losses = [max(-c, 0.0) for c in changes]

    avg_gain = wilder_average(gains, period)
    avg_loss = wilder_average(losses, period)

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))


def true_ranges(bars):
    out = []

    for i in range(1, len(bars)):
        high = bars[i]["high"]
        low = bars[i]["low"]
        prev = bars[i - 1]["close"]
        out.append(max(high - low, abs(high - prev), abs(low - prev)))

    return out


def atr(bars, period=14):
    return wilder_average(true_ranges(bars), period)


# ============================================================
# ADX AND DIRECTIONAL INDICATORS
# ============================================================

def adx(bars, period=14):
    if len(bars) < (period * 2 + 1):
        raise ValueError("Not enough data for ADX")

    plus_dm = []
    minus_dm = []
    tr_values = []

    for i in range(1, len(bars)):
        up_move = bars[i]["high"] - bars[i - 1]["high"]
        down_move = bars[i - 1]["low"] - bars[i]["low"]

        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(
            down_move if down_move > up_move and down_move > 0 else 0.0
        )
        tr_values.append(
            max(
                bars[i]["high"] - bars[i]["low"],
                abs(bars[i]["high"] - bars[i - 1]["close"]),
                abs(bars[i]["low"] - bars[i - 1]["close"]),
            )
        )

    def wilder_series(values, length):
        out = [None] * len(values)

        if len(values) < length:
            return out

        current = sum(values[:length])
        out[length - 1] = current

        for j in range(length, len(values)):
            current = current - (current / length) + values[j]
            out[j] = current

        return out

    sm_tr = wilder_series(tr_values, period)
    sm_plus = wilder_series(plus_dm, period)
    sm_minus = wilder_series(minus_dm, period)

    dx_values = []
    plus_di = 0.0
    minus_di = 0.0

    for i in range(len(tr_values)):
        if (
            sm_tr[i] is None
            or sm_tr[i] == 0
            or sm_plus[i] is None
            or sm_minus[i] is None
        ):
            continue

        pdi = 100.0 * sm_plus[i] / sm_tr[i]
        mdi = 100.0 * sm_minus[i] / sm_tr[i]
        total = pdi + mdi

        dx_values.append(0.0 if total == 0 else 100.0 * abs(pdi - mdi) / total)
        plus_di = pdi
        minus_di = mdi

    if len(dx_values) < period:
        raise ValueError("Not enough data to calculate ADX")

    return wilder_average(dx_values, period), plus_di, minus_di


def macd_histogram(closes, fast=12, slow=26, signal=9):
    fast_series = ema_series(closes, fast)
    slow_series = ema_series(closes, slow)

    macd_values = [
        f - s
        for f, s in zip(fast_series, slow_series)
        if f is not None and s is not None
    ]

    if len(macd_values) < signal:
        raise ValueError("Not enough data for MACD")

    return macd_values[-1] - ema(macd_values, signal)
