"""
JAY FX - Backtest (single self-contained file)

This file needs NOTHING else from the repo except the secrets in GitHub
(BOT_TOKEN, ADMIN_CHAT_ID, TWELVE_DATA_API_KEY and optional _2 _3 _4).
It contains the data download, the indicator maths, the v2 FX engine, the
old-engine copy, the simulator and the report.

Answers two questions with real candles:
1. What did the OLD FX engine really earn (hourly rotation, always trades)?
2. Does the new v2 engine (same tested logic as Gold, per pair) do better?

For each pair it downloads about 2.4 years of hourly candles plus 4H candles,
replays every entry rule, and simulates two exit ladders:
- v2 ladder: 1R / 2R / 3R, close 40/30/30, stop to entry after TP1, 72 bar stop
- old FX ladder: 1.0 / 2.0 / 3.2 / 4.5 ATR, 25% each, trailing stop ratchet

All combinations run under the SAME risk caps (one trade per pair, a total
cap, and a cap per USD side) and the same spread assumptions.
Rules are judged on the first 60% of time (practice) and must hold on the
last 40% (unseen). Results are evidence, not a promise.
"""

import bisect
import html
import io
import math
import os
import re
import sys
import time
from collections import defaultdict
from contextlib import redirect_stdout
from datetime import datetime, timezone, timedelta

import requests

import atexit

_RAN = {"main": False}


def _integrity_check():
    if not _RAN["main"]:
        print(
            "ERROR: main() never ran. The file was pasted incompletely. "
            "Delete fx_backtest.py, create it again and paste the WHOLE file "
            "down to the last line: if __name__ == \"__main__\": main()"
        )
        os._exit(1)


atexit.register(_integrity_check)

# ============================================================
# SETTINGS (edit spreads here to match your broker)
# ============================================================

class config:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
    ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()

    # The pairs, in the same order as the old hourly rotation.
    FX_ROTATION = [
        {"name": "EUR/USD"},
        {"name": "GBP/USD"},
        {"name": "USD/JPY"},
        {"name": "AUD/USD"},
        {"name": "USD/CAD"},
        {"name": "USD/CHF"},
    ]

    # Spread + slippage assumption per pair, in pips (round trip).
    PAIR_SETTINGS = {
        "EUR/USD": {"pip": 0.0001, "spread_pips": 1.0},
        "GBP/USD": {"pip": 0.0001, "spread_pips": 1.4},
        "USD/JPY": {"pip": 0.01, "spread_pips": 1.2},
        "AUD/USD": {"pip": 0.0001, "spread_pips": 1.4},
        "USD/CAD": {"pip": 0.0001, "spread_pips": 1.8},
        "USD/CHF": {"pip": 0.0001, "spread_pips": 1.8},
    }

    FX_PAIRS = list(PAIR_SETTINGS.keys())

    FX_PARAMS = {
        "trend_mode": "STRICT",
        "rsi_buy": 52,
        "rsi_sell": 48,
        "adx_min": 14.0,
        "momentum_min": 3,
    }

    # The old channel is quiet from 22:00 to 24:00 UTC.
    QUIET_HOUR_START = 22
    QUIET_HOUR_END = 24

    # Risk caps across the whole FX book.
    MAX_OPEN_PER_PAIR = 1
    MAX_OPEN_TOTAL = 6
    MAX_OPEN_PER_USD_SIDE = 3

# ============================================================
# TWELVE DATA (all keys, waits when the per-minute limit is hit)
# ============================================================

def td_get(endpoint, params, timeout=60):
    keys = [
        os.getenv(name, "").strip()
        for name in (
            "TWELVE_DATA_API_KEY",
            "TWELVE_DATA_API_KEY_2",
            "TWELVE_DATA_API_KEY_3",
            "TWELVE_DATA_API_KEY_4",
        )
    ]
    keys = [k for k in keys if k]

    if not keys:
        raise RuntimeError(
            "No TWELVE_DATA_API_KEY secret found. Add it in GitHub secrets."
        )

    last = {"status": "error", "message": "no response"}

    for attempt in range(4):
        rate_limited = False

        for key in keys:
            query = dict(params)
            query["apikey"] = key

            try:
                res = requests.get(
                    f"https://api.twelvedata.com/{endpoint}",
                    params=query,
                    timeout=timeout,
                ).json()
            except Exception as error:
                last = {"status": "error", "message": str(error)}
                continue

            failed = isinstance(res, dict) and (
                res.get("status") == "error"
                or (isinstance(res.get("code"), int) and res["code"] >= 400)
            )

            if not failed:
                return res

            last = res
            text = str(res.get("message", "")).lower()

            if res.get("code") == 429 or "credits" in text or "limit" in text:
                rate_limited = True

        if not rate_limited:
            return last

        print(f"Twelve Data rate limit, waiting 25s (attempt {attempt + 1}/4)")
        time.sleep(25)

    return last

# ============================================================
# ADMIN MESSAGES (private chat only)
# ============================================================

def notify(text, html_mode=False):
    if not config.BOT_TOKEN or not config.ADMIN_CHAT_ID:
        print("ADMIN message skipped: BOT_TOKEN or ADMIN_CHAT_ID secret is empty.")
        return False

    payload = {"chat_id": config.ADMIN_CHAT_ID, "text": str(text)[:3900]}

    if html_mode:
        payload["parse_mode"] = "HTML"

    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"

    try:
        response = requests.post(url, json=payload, timeout=15)

        if not response.ok and html_mode:
            payload.pop("parse_mode", None)
            response = requests.post(url, json=payload, timeout=15)

        if not response.ok:
            print(
                "ADMIN message FAILED. Check ADMIN_CHAT_ID, and press Start "
                f"on the FX bot in Telegram. Telegram said: {response.text}"
            )

        return response.ok

    except Exception as error:
        print(f"Admin notify failed: {error}")
        return False

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

    data = td_get("time_series", params, timeout=60)

    if not isinstance(data, dict) or "values" not in data:
        raise RuntimeError(
            f"Unexpected Twelve Data response for {symbol} {interval}: {data}"
        )

    bars = [clean_row(row) for row in data["values"]]
    unique = {b["datetime"]: b for b in bars if b}

    return [unique[key] for key in sorted(unique)]

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

# ============================================================
# FX ENGINE (v2 decision and the old engine copy)
# ============================================================

# R (one unit of risk) = SL_ATR x ATR.
SL_ATR = 1.5

# v2 ladder in ATR multiples: 1R, 2R, 3R. Share closed at each target.
TP_MULT = (1.5, 3.0, 4.5)
TP_WEIGHTS = (0.4, 0.3, 0.3)

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

# ============================================================
# LONG HISTORY LOADER
# ============================================================

PAGE_SIZE = 5000
PAUSE_SECONDS = 8   # keeps us under the Twelve Data per-minute limit

def load_history(symbol, interval, pages):
    """Newest page first, then older pages. Returns bars oldest to newest."""

    merged = {}
    end_date = None

    for page in range(pages):
        try:
            bars = fetch_bars(symbol, interval, PAGE_SIZE, end_date)
        except Exception as error:
            print(f"{symbol} {interval}: no more history ({error})")
            break

        if not bars:
            break

        before = len(merged)

        for bar in bars:
            merged[bar["datetime"]] = bar

        print(
            f"{symbol} {interval} page {page + 1}: {len(bars)} candles, "
            f"{bars[0]['datetime'][:10]} to {bars[-1]['datetime'][:10]}"
        )

        if len(merged) == before:
            break

        oldest = parse_bar_time(bars[0]["datetime"])
        end_date = (oldest - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")

        time.sleep(PAUSE_SECONDS)

    return [merged[key] for key in sorted(merged)]

# ============================================================
# BACKTEST
# ============================================================

PAGES_1H = 3
PAGES_4H = 1

SPLIT_FRACTION = 0.60
MIN_UNSEEN_TRADES = 150
MIN_UNSEEN_R = 0.05
MIN_Z = 1.5
BE_BAND_R = 0.05

LADDER_V2 = {
    "name": "v2 ladder 1R/2R/3R",
    "sl": 1.5,
    "tps": (1.5, 3.0, 4.5),
    "weights": (0.4, 0.3, 0.3),
    "trail": "BE",
    "max_hold": 72,
}

LADDER_OLD = {
    "name": "old FX ladder",
    "sl": 1.5,
    "tps": (1.0, 2.0, 3.2, 4.5),
    "weights": (0.25, 0.25, 0.25, 0.25),
    "trail": "RATCHET",
    "max_hold": 500,
}

PARAMS_STRICT = dict(config.FX_PARAMS)

PARAMS_BE = dict(config.FX_PARAMS)
PARAMS_BE.update({"trend_mode": "STRUCTURE", "adx_min": 10.0})

ENTRIES = [
    ("OLD entries (hourly rotation, always trades)", "LEGACY", None),
    ("v2 entries, strict", "V2", PARAMS_STRICT),
    ("v2 entries, pullbacks + ADX 10", "V2", PARAMS_BE),
]

RULE = "━━━━━━━━━━━━━━━━━━"

# ============================================================
# 1. FIND SIGNALS FOR ONE PAIR (all entry rules in one pass)
# ============================================================

def in_quiet_hours(now):
    return config.QUIET_HOUR_START <= now.hour < config.QUIET_HOUR_END

def scan_pair(pair, bars_1h, bars_4h):
    """Returns {entry_name: [signals]} for this pair."""

    starts_1h = [parse_bar_time(b["datetime"]) for b in bars_1h]
    starts_4h = [parse_bar_time(b["datetime"]) for b in bars_4h]

    names = [e[0] for e in ENTRIES]
    out = {name: [] for name in names}

    rotation = [item["name"] for item in config.FX_ROTATION]

    for i in range(230, len(bars_1h)):
        now = starts_1h[i] + timedelta(hours=1)

        if in_quiet_hours(now):
            continue

        if (starts_1h[i] - starts_1h[i - 1]).total_seconds() > 4 * 3600:
            continue

        cut4 = bisect.bisect_right(starts_4h, now - timedelta(hours=4))

        if cut4 < 205:
            continue

        window_1h = bars_1h[i - 218:i + 1]
        window_4h = bars_4h[cut4 - 219:cut4]

        try:
            with redirect_stdout(io.StringIO()):
                feats = features(window_1h, window_4h)
        except Exception:
            feats = None

        for name, kind, params in ENTRIES:
            if kind == "V2":
                if feats is None:
                    continue

                signal, _ = decide(pair, feats, params, now)

            else:
                if rotation[now.hour % len(rotation)] != pair:
                    continue

                if now.weekday() > 4:
                    continue

                signal = legacy_signal(
                    pair, bars_1h[max(0, i - 219):i + 1], now
                )

            if signal:
                signal["index"] = i
                out[name].append(signal)

    return out

# ============================================================
# 2. SIMULATE ONE TRADE
# ============================================================

def simulate(signal, profile, bars_1h):
    pair = signal["pair"]
    settings = config.PAIR_SETTINGS[pair]

    sign = 1 if signal["direction"] == "BUY" else -1
    entry = signal["entry"]
    atr_value = signal["atr"]

    risk = profile["sl"] * atr_value
    stop = entry - sign * risk
    targets = [entry + sign * m * atr_value for m in profile["tps"]]
    weights = profile["weights"]

    hit = [False] * len(targets)
    remaining = 1.0
    realized = 0.0

    i = signal["index"]
    exit_index = None

    for j in range(i + 1, len(bars_1h)):
        high = bars_1h[j]["high"]
        low = bars_1h[j]["low"]

        stop_hit = low <= stop if sign == 1 else high >= stop

        if stop_hit:
            realized += remaining * sign * (stop - entry)
            remaining = 0.0
            exit_index = j
            break

        for k, target in enumerate(targets):
            reached = high >= target if sign == 1 else low <= target

            if not hit[k] and reached:
                hit[k] = True
                realized += weights[k] * sign * (target - entry)
                remaining -= weights[k]

        if remaining <= 1e-9:
            exit_index = j
            break

        if hit[0]:
            if profile["trail"] == "BE":
                stop = entry
            else:
                top = max(k for k, flag in enumerate(hit) if flag)
                stop = entry if top == 0 else targets[top - 1]

        if profile["max_hold"] and (j - i) >= profile["max_hold"]:
            realized += remaining * sign * (bars_1h[j]["close"] - entry)
            remaining = 0.0
            exit_index = j
            break

    if exit_index is None:
        return None

    cost_price = settings["spread_pips"] * settings["pip"]
    realized -= cost_price

    return {
        "pair": pair,
        "direction": signal["direction"],
        "entry_time": signal["time"],
        "exit_time": parse_bar_time(bars_1h[exit_index]["datetime"])
        + timedelta(hours=1),
        "r": realized / risk,
        "risk": risk,
        "cost_price": cost_price,
        "hold": exit_index - i,
    }

# ============================================================
# 3. PORTFOLIO RULES (same caps for every combination)
# ============================================================

def usd_side(pair, direction):
    base = pair.split("/")[0]

    long_usd = (direction == "BUY") if base == "USD" else (direction == "SELL")

    return "USD_LONG" if long_usd else "USD_SHORT"

def apply_caps(trades):
    kept = []
    open_now = []

    for trade in sorted(trades, key=lambda t: t["entry_time"]):
        open_now = [o for o in open_now if o["exit_time"] > trade["entry_time"]]

        same_pair = sum(1 for o in open_now if o["pair"] == trade["pair"])
        side = usd_side(trade["pair"], trade["direction"])
        same_side = sum(
            1 for o in open_now if usd_side(o["pair"], o["direction"]) == side
        )

        if same_pair >= config.MAX_OPEN_PER_PAIR:
            continue

        if len(open_now) >= config.MAX_OPEN_TOTAL:
            continue

        if same_side >= config.MAX_OPEN_PER_USD_SIDE:
            continue

        kept.append(trade)
        open_now.append(trade)

    return kept

# ============================================================
# 4. STATISTICS
# ============================================================

def stats(trades):
    n = len(trades)

    if n == 0:
        return None

    rs = [t["r"] for t in trades]
    wins = sum(1 for r in rs if r > BE_BAND_R)
    losses = sum(1 for r in rs if r < -BE_BAND_R)

    gross_win = sum(r for r in rs if r > 0)
    gross_loss = -sum(r for r in rs if r < 0)

    mean = sum(rs) / n
    stderr = 0.0

    if n > 1:
        variance = sum((r - mean) ** 2 for r in rs) / (n - 1)
        stderr = math.sqrt(variance) / math.sqrt(n)

    equity = peak = drawdown = 0.0

    for trade in sorted(trades, key=lambda t: t["exit_time"]):
        equity += trade["r"]
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)

    return {
        "n": n,
        "win": 100.0 * wins / n,
        "loss": 100.0 * losses / n,
        "avg": mean,
        "se": stderr,
        "total": sum(rs),
        "pf": gross_win / gross_loss if gross_loss > 0 else float("inf"),
        "dd": drawdown,
    }

def daily_z(trades):
    by_day = defaultdict(float)

    for trade in trades:
        by_day[trade["entry_time"].date()] += trade["r"]

    values = list(by_day.values())

    if len(values) < 20:
        return 0.0

    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)

    if var <= 0:
        return 0.0

    return mean / (math.sqrt(var) / math.sqrt(len(values)))

def stress_avg(trades, multiple):
    if not trades:
        return 0.0

    return sum(
        t["r"] - (multiple - 1.0) * t["cost_price"] / t["risk"] for t in trades
    ) / len(trades)

def max_open(trades):
    events = []

    for t in trades:
        events.append((t["entry_time"], 1))
        events.append((t["exit_time"], -1))

    events.sort(key=lambda e: (e[0], e[1]))

    current = peak = 0

    for _, step in events:
        current += step
        peak = max(peak, current)

    return peak

# ============================================================
# 5. REPORT
# ============================================================

def esc(text):
    return html.escape(str(text), quote=False)

def strip_tags(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text))

def evaluate(trades, split_time, days):
    practice = [t for t in trades if t["entry_time"] < split_time]
    unseen = [t for t in trades if t["entry_time"] >= split_time]

    p, u, a = stats(practice), stats(unseen), stats(trades)

    if not p or not u or not a:
        return None

    return {
        "p": p,
        "u": u,
        "a": a,
        "z": daily_z(trades),
        "per_day": len(trades) / days,
        "open": max_open(trades),
    }

def passes(result):
    return bool(
        result
        and result["p"]["avg"] > 0
        and result["u"]["avg"] >= MIN_UNSEEN_R
        and result["u"]["n"] >= MIN_UNSEEN_TRADES
        and result["z"] >= MIN_Z
    )

def combo_card(name, result):
    if not result:
        return f"⚪ <b>{esc(name)}</b>\n   Too few trades"

    icon = "✅" if passes(result) else "⚠️"

    return (
        f"{icon} <b>{esc(name)}</b>\n"
        f"   📡 <b>{result['per_day']:.1f} signals per trading day</b> "
        f"(all pairs)\n"
        f"   🔵 Practice {result['p']['avg']:+.2f}R ({result['p']['n']}) · "
        f"🟣 Unseen {result['u']['avg']:+.2f}R ({result['u']['n']})\n"
        f"   📈 Total {result['a']['total']:+.0f}R · Worst dip "
        f"{result['a']['dd']:.0f}R · Edge z {result['z']:.1f} · "
        f"Most open {result['open']}"
    )

def build_sections(data, results, split_time, days, first, last):
    sections = []

    pairs_line = ", ".join(
        f"{pair} {len(data[pair]['1h']):,}" for pair in data
    )
    spreads = ", ".join(
        f"{pair.replace('/', '')} {config.PAIR_SETTINGS[pair]['spread_pips']}"
        for pair in data
    )

    sections.append(
        "🌍 <b>JAY FX BACKTEST</b>  🔒 private\n"
        f"{RULE}\n"
        f"🗓 {first:%Y-%m-%d} → {last:%Y-%m-%d}\n"
        f"🔵 Practice → {split_time:%Y-%m-%d} · 🟣 Unseen after\n"
        f"🕯 Hourly candles per pair: {pairs_line}\n"
        f"💵 Spread pips assumed: {spreads}\n"
        f"🔒 Caps: {config.MAX_OPEN_PER_PAIR} per pair · "
        f"{config.MAX_OPEN_TOTAL} total · "
        f"{config.MAX_OPEN_PER_USD_SIDE} per USD side\n"
        "✅ needs unseen +0.05R, 150+ unseen trades, daily z of 1.5+"
    )

    # ---- the old engine, measured ------------------------------------
    old = results.get((ENTRIES[0][0], LADDER_OLD["name"]))

    if old:
        sections.append(
            "🧾 <b>1. WHAT THE OLD FX ENGINE REALLY EARNS</b>\n"
            "Same caps and spreads as everything else.\n"
            f"{RULE}\n" + combo_card("Old entries + old ladder", old["result"])
        )

    # ---- all combinations ------------------------------------------------
    cards = []
    winners = []

    for (entry_name, exit_name), item in results.items():
        cards.append(combo_card(f"{entry_name} | {exit_name}", item["result"]))

        if passes(item["result"]):
            winners.append((entry_name, exit_name, item))

    sections.append(
        "🏁 <b>2. EVERY COMBINATION</b>\n"
        f"{RULE}\n" + "\n\n".join(cards)
    )

    # ---- per pair for the best winner -------------------------------------
    notes = []

    if winners:
        winners.sort(key=lambda w: w[2]["result"]["u"]["avg"], reverse=True)
        entry_name, exit_name, item = winners[0]

        trades = item["trades"]

        rows = []
        good_pairs = []

        for pair in config.FX_PAIRS:
            subset = [t for t in trades if t["pair"] == pair]
            practice = [t for t in subset if t["entry_time"] < split_time]
            unseen = [t for t in subset if t["entry_time"] >= split_time]

            p, u = stats(practice), stats(unseen)

            if not p or not u:
                rows.append(f"⚪ <b>{pair}</b>: too few trades")
                continue

            ok = p["avg"] > 0 and u["avg"] > 0 and u["n"] >= 40
            if ok:
                good_pairs.append(pair)

            rows.append(
                f"{'✅' if ok else '⚠️'} <b>{pair}</b>\n"
                f"   Practice {p['avg']:+.2f}R ({p['n']}) · "
                f"Unseen {u['avg']:+.2f}R ({u['n']})"
            )

        stress = " · ".join(
            f"spread x{m}: {stress_avg(trades, m):+.2f}R" for m in (1.0, 1.5, 2.0)
        )

        sections.append(
            "🏆 <b>3. BEST COMBINATION, PAIR BY PAIR</b>\n"
            f"<b>{esc(entry_name)} | {esc(exit_name)}</b>\n"
            f"{RULE}\n" + "\n".join(rows) + f"\n\n💵 Cost stress, average R: {stress}"
        )

        notes.append(
            f"🏆 Best passing combination: {esc(entry_name)} with "
            f"{esc(exit_name)} at {item['result']['per_day']:.1f} "
            "signals per trading day."
        )

        if good_pairs:
            notes.append(
                "✅ Pairs that held up on their own: " + ", ".join(good_pairs)
            )

        bad = [p for p in config.FX_PAIRS if p not in good_pairs]

        if bad:
            notes.append(
                "⚠️ Pairs that did not hold up alone (do not post them "
                "until they pass): " + ", ".join(bad)
            )
    else:
        notes.append(
            "🔴 No combination passed every check. We do not launch a v2 FX "
            "engine on this evidence. Next step would be pair by pair tuning "
            "or a different entry idea."
        )

    notes.append(
        f"⚠️ {len(results)} combinations were tested, so one can look good "
        "by luck. A winner still runs private (shadow) for 2 weeks first."
    )

    sections.append("✅ <b>4. VERDICT</b>\n" + f"{RULE}\n" + "\n\n".join(notes))

    return sections

# ============================================================
# 6. RUN
# ============================================================

def run(data):
    """data: {pair: {'1h': bars, '4h': bars}}"""

    all_first = min(parse_bar_time(d["1h"][0]["datetime"]) for d in data.values())
    all_last = max(parse_bar_time(d["1h"][-1]["datetime"]) for d in data.values())

    split_time = all_first + (all_last - all_first) * SPLIT_FRACTION

    days = max(1.0, (all_last - all_first).days * 5 / 7)

    signals = {e[0]: [] for e in ENTRIES}

    for pair, d in data.items():
        found = scan_pair(pair, d["1h"], d["4h"])

        for name, items in found.items():
            signals[name].extend(items)

    results = {}

    for entry_name, _, _ in ENTRIES:
        for ladder in (LADDER_V2, LADDER_OLD):
            trades = []

            for signal in signals[entry_name]:
                trade = simulate(signal, ladder, data[signal["pair"]]["1h"])

                if trade:
                    trades.append(trade)

            capped = apply_caps(trades)

            results[(entry_name, ladder["name"])] = {
                "trades": capped,
                "result": evaluate(capped, split_time, days),
            }

    return build_sections(data, results, split_time, days, all_first, all_last)

def pack_messages(sections, limit=3800):
    messages = []
    current = ""

    for section in sections:
        candidate = f"{current}\n\n{section}" if current else section

        if len(candidate) > limit and current:
            messages.append(current)
            current = section
        else:
            current = candidate

    if current:
        messages.append(current)

    return messages

# ============================================================
# 7. ENTRY POINT
# ============================================================

def main():
    _RAN["main"] = True
    print(f"Python {sys.version.split()[0]}")

    notify("⏳ FX backtest started. Downloading candles for 6 pairs. "
           "This takes about 5 to 8 minutes.")

    data = {}
    failed = []

    for pair in config.FX_PAIRS:
        print(f"Downloading {pair}...")

        bars_1h = load_history(pair, "1h", PAGES_1H)
        bars_4h = load_history(pair, "4h", PAGES_4H)

        if len(bars_1h) < 1000 or len(bars_4h) < 300:
            print(f"Skipping {pair}: not enough history.")
            failed.append(pair)
            continue

        data[pair] = {"1h": bars_1h, "4h": bars_4h}

    if failed:
        notify("⚠️ Could not load enough history for: " + ", ".join(failed))

    if not data:
        notify("❌ FX backtest stopped: no pair returned enough history. "
               "Check the TWELVE_DATA_API_KEY secrets and the run log.")
        raise RuntimeError("No pair returned enough history.")

    sections = run(data)

    plain = "\n\n".join(strip_tags(s) for s in sections)

    print(plain)

    with open("fx_backtest_report.txt", "w") as handle:
        handle.write(plain)

    for part in pack_messages(sections):
        notify(part, html_mode=True)

if __name__ == "__main__":
    main()
