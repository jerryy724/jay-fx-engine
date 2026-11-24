"""
fx_engine.py - the FX signal decision, as pure functions.

analyse(): the v2 engine. Same logic as the Gold engine (4H trend + 1H
momentum + trend strength), applied per pair. It takes candles in and
returns a decision, so the live job and the backtest use identical code.

legacy_signal(): a faithful copy of the OLD FX engine's decision (price vs a
rough 4H EMA50, always BUY or SELL). Used only by the backtest so we can
measure what the old engine really earned.
"""

import config
from indicators import (
    ema,
    rsi,
    atr,
    adx,
    macd_histogram,
)

# R (one unit of risk) = SL_ATR x ATR.
SL_ATR = 1.5

# v2 ladder in ATR multiples: 1R, 2R, 3R. Share closed at each target.
TP_MULT = (1.5, 3.0, 4.5)
TP_WEIGHTS = (0.4, 0.3, 0.3)

MIN_DATA_1H = 60
MIN_DATA_4H = 60


def trend_label(price, ema50, ema200):
    if ema200 is None:
        return "4H price above EMA50" if price > ema50 else "4H price below EMA50"

    if price > ema50 > ema200:
        return "4H uptrend"

    if price < ema50 < ema200:
        return "4H downtrend"

    if ema50 > ema200:
        return "4H pullback inside an uptrend"

    return "4H bounce inside a downtrend"


def features(bars_1h, bars_4h):
    """Indicator values for the latest closed candles (computed once)."""

    closes_1h = [b["close"] for b in bars_1h]
    closes_4h = [b["close"] for b in bars_4h]

    adx_1h, plus_di, minus_di = adx(bars_1h, 14)

    return {
        "price": closes_1h[-1],
        "trend_price": closes_4h[-1],
        "ema50": ema(closes_4h, 50),
        "ema200": ema(closes_4h, 200) if len(closes_4h) >= 200 else None,
        "rsi": rsi(closes_1h, 14),
        "atr": atr(bars_1h, 14),
        "adx": adx_1h,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "macd": macd_histogram(closes_1h),
    }


def decide(pair, f, params, now):
    """Entry decision from precomputed features. Returns (signal, reason)."""

    price = f["price"]
    trend_price = f["trend_price"]
    ema50 = f["ema50"]
    ema200 = f["ema200"]
    rsi_1h = f["rsi"]

    if ema200 is not None and params["trend_mode"] == "STRUCTURE":
        bullish_trend = ema50 > ema200
        bearish_trend = ema50 < ema200
    elif ema200 is not None:
        bullish_trend = trend_price > ema50 > ema200
        bearish_trend = trend_price < ema50 < ema200
    else:
        bullish_trend = trend_price > ema50
        bearish_trend = trend_price < ema50

    need = params["momentum_min"]

    buy_votes = sum([
        rsi_1h >= params["rsi_buy"],
        f["macd"] > 0,
        f["plus_di"] > f["minus_di"],
    ])
    sell_votes = sum([
        rsi_1h <= params["rsi_sell"],
        f["macd"] < 0,
        f["minus_di"] > f["plus_di"],
    ])

    label = trend_label(trend_price, ema50, ema200)

    if bullish_trend and buy_votes >= need:
        direction = "BUY"
    elif bearish_trend and sell_votes >= need:
        direction = "SELL"
    elif bullish_trend or bearish_trend:
        return None, f"{pair}: {label}, 1H momentum not confirmed (RSI {rsi_1h:.0f})."
    else:
        return None, f"{pair}: {label}. Waiting for the trend to resume."

    if f["adx"] < params["adx_min"]:
        return None, f"{pair}: {label}, trend too weak (ADX {f['adx']:.1f})."

    if direction == "BUY" and rsi_1h >= 72:
        return None, f"{pair}: BUY rejected, overbought (RSI {rsi_1h:.0f})."

    if direction == "SELL" and rsi_1h <= 28:
        return None, f"{pair}: SELL rejected, oversold (RSI {rsi_1h:.0f})."

    return {
        "pair": pair,
        "direction": direction,
        "entry": price,
        "atr": f["atr"],
        "rsi": rsi_1h,
        "adx": f["adx"],
        "trend": label,
        "time": now,
    }, f"{pair}: {direction} setup qualified. {label}."


def analyse(pair, bars_1h, bars_4h, now, params=None):
    """
    bars_1h / bars_4h: CLOSED candles, oldest first.
    Returns (signal_or_None, reason_text).
    """

    params = params or config.FX_PARAMS

    if len(bars_1h) < MIN_DATA_1H or len(bars_4h) < MIN_DATA_4H:
        return None, "Not enough candles."

    return decide(pair, features(bars_1h, bars_4h), params, now)


# ============================================================
# THE OLD FX ENGINE (for comparison only)
# ============================================================

def _legacy_atr(bars, period=14):
    ranges = []

    for i in range(1, len(bars)):
        high = bars[i]["high"]
        low = bars[i]["low"]
        prev = bars[i - 1]["close"]
        ranges.append(max(high - low, abs(high - prev), abs(low - prev)))

    if len(ranges) < period:
        return None

    return sum(ranges[-period:]) / period


def _legacy_ema_4h(bars):
    closes = [b["close"] for b in bars]
    grouped = [closes[i] for i in range(3, len(closes), 4)]

    if len(grouped) < 50:
        return sum(closes[-50:]) / min(len(closes), 50)

    k = 2.0 / 51
    value = sum(grouped[:50]) / 50.0

    for price in grouped[50:]:
        value = price * k + value * (1.0 - k)

    return value


def legacy_signal(pair, bars_window, now):
    """bars_window: the last 220 closed 1H candles (like the old engine)."""

    if len(bars_window) < 100:
        return None

    price = bars_window[-1]["close"]
    atr_value = _legacy_atr(bars_window)

    if not atr_value:
        return None

    direction = "BUY" if price > _legacy_ema_4h(bars_window) else "SELL"

    return {
        "pair": pair,
        "direction": direction,
        "entry": price,
        "atr": atr_value,
        "rsi": 50.0,
        "adx": 0.0,
        "trend": "legacy",
        "time": now,
  }
