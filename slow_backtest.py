"""
JAY CRYPTO + SILVER - Slower-timeframe test

The hourly test showed no reliable edge on Bitcoin and Ethereum (best result
+0.02R after costs). Two ideas can still work, and this tests both:

1. SLOW lane: trade on 4H candles with the DAILY trend. Stops are bigger, so
   costs matter far less, and 3 to 7 years of history covers bull and bear
   phases. Assets: BTC, ETH, silver (XAG/USD).
2. SILVER fast lane: silver on hourly candles with the 4H trend, exactly like
   Gold. Only runs if silver data can be loaded.

It first CHECKS silver data and tells you the exact reason if it fails.

Judged on the first 60% (practice), must hold on the last 40% (unseen).
SLOW lane pass bar: practice > 0, unseen >= +0.05R, 60+ unseen trades,
trade-level t-stat >= 2.0 over the whole period.
FAST silver pass bar: unseen >= +0.05R, 150+ unseen trades, daily z >= 2.0.

Needs fx_backtest.py (the single-file version) in the same folder.
"""

import bisect
import io
from collections import defaultdict
from contextlib import redirect_stdout
from datetime import timedelta

import fx_backtest as fb

# We only borrow the tools inside fx_backtest.py, not its main().
fb._RAN["main"] = True

ASSETS = ["BTC/USD", "ETH/USD", "XAG/USD"]

# Round-trip cost per trade as a share of price. ASSUMPTIONS: edit to match.
COST_PCT = {"BTC/USD": 0.0005, "ETH/USD": 0.0007, "XAG/USD": 0.0008}

GROUP = {"BTC/USD": "CRYPTO", "ETH/USD": "CRYPTO", "XAG/USD": "METAL"}

MAX_OPEN_PER_ASSET = 1
MAX_OPEN_TOTAL = 3
CRYPTO_SIDE_CAPS = (1, 2)

SLOW_MIN_UNSEEN = 60
SLOW_MIN_T = 2.0
FAST_MIN_UNSEEN = 150
FAST_MIN_Z = 2.0
MIN_UNSEEN_R = 0.05

PAGES_4H = 3
PAGES_1D = 1
PAGES_1H = 3

ENTRIES = [
    ("v2 strict", fb.PARAMS_STRICT),
    ("v2 pullbacks + ADX 10", fb.PARAMS_BE),
]

LADDER_SLOW_V2 = dict(fb.LADDER_V2, max_hold=60, name="v2 ladder 1R/2R/3R")
LADDER_SLOW_OLD = dict(fb.LADDER_OLD, max_hold=120, name="old ladder")

RULE = fb.RULE


# ============================================================
# GENERIC SCAN AND SIMULATION (any timeframe)
# ============================================================

def scan(asset, sig_bars, trend_bars, sig_h, trend_h, common_start, entries):
    sig_starts = [fb.parse_bar_time(b["datetime"]) for b in sig_bars]
    trend_starts = [fb.parse_bar_time(b["datetime"]) for b in trend_bars]

    out = {name: [] for name, _ in entries}

    for i in range(230, len(sig_bars)):
        now = sig_starts[i] + timedelta(hours=sig_h)

        if now < common_start:
            continue

        if (sig_starts[i] - sig_starts[i - 1]).total_seconds() > 4 * sig_h * 3600:
            continue

        cut = bisect.bisect_right(trend_starts, now - timedelta(hours=trend_h))

        if cut < 205:
            continue

        try:
            with redirect_stdout(io.StringIO()):
                feats = fb.features(sig_bars[i - 218:i + 1], trend_bars[cut - 219:cut])
        except Exception:
            continue

        for name, params in entries:
            signal, _ = fb.decide(asset, feats, params, now)

            if signal:
                signal["index"] = i
                out[name].append(signal)

    return out


def simulate(signal, profile, bars, bar_hours, cost_multiple=1.0):
    asset = signal["pair"]

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

    for j in range(i + 1, len(bars)):
        high = bars[j]["high"]
        low = bars[j]["low"]

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
            realized += remaining * sign * (bars[j]["close"] - entry)
            remaining = 0.0
            exit_index = j
            break

    if exit_index is None:
        return None

    realized -= entry * COST_PCT[asset] * cost_multiple

    return {
        "pair": asset,
        "direction": signal["direction"],
        "entry_time": signal["time"],
        "exit_time": fb.parse_bar_time(bars[exit_index]["datetime"])
        + timedelta(hours=bar_hours),
        "r": realized / risk,
        "risk": risk,
        "cost_price": entry * COST_PCT[asset],
    }


def apply_caps(trades, crypto_side_cap):
    kept = []
    open_now = []

    for trade in sorted(trades, key=lambda t: t["entry_time"]):
        open_now = [o for o in open_now if o["exit_time"] > trade["entry_time"]]

        if sum(1 for o in open_now if o["pair"] == trade["pair"]) >= MAX_OPEN_PER_ASSET:
            continue

        if len(open_now) >= MAX_OPEN_TOTAL:
            continue

        if GROUP[trade["pair"]] == "CRYPTO":
            same_side = sum(
                1
                for o in open_now
                if GROUP[o["pair"]] == "CRYPTO"
                and o["direction"] == trade["direction"]
            )

            if same_side >= crypto_side_cap:
                continue

        kept.append(trade)
        open_now.append(trade)

    return kept


# ============================================================
# EVALUATION
# ============================================================

def evaluate(trades, split_time, days):
    result = fb.evaluate(trades, split_time, days)

    if result:
        a = result["a"]
        result["t"] = a["avg"] / a["se"] if a["se"] > 0 else 0.0

    return result


def slow_pass(result):
    return bool(
        result
        and result["p"]["avg"] > 0
        and result["u"]["avg"] >= MIN_UNSEEN_R
        and result["u"]["n"] >= SLOW_MIN_UNSEEN
        and result["t"] >= SLOW_MIN_T
    )


def fast_pass(result):
    return bool(
        result
        and result["p"]["avg"] > 0
        and result["u"]["avg"] >= MIN_UNSEEN_R
        and result["u"]["n"] >= FAST_MIN_UNSEEN
        and result["z"] >= FAST_MIN_Z
    )


def card(icon, name, result):
    if not result:
        return f"⚪ {fb.esc(name)}: too few trades"

    return (
        f"{icon} <b>{fb.esc(name)}</b>\n"
        f"   📡 {result['per_day']:.2f}/day · "
        f"🔵 {result['p']['avg']:+.2f}R ({result['p']['n']}) · "
        f"🟣 {result['u']['avg']:+.2f}R ({result['u']['n']}) · "
        f"t {result['t']:.1f} · z {result['z']:.1f} · dip {result['a']['dd']:.0f}R"
    )


def by_year(trades):
    groups = defaultdict(list)

    for trade in trades:
        groups[trade["entry_time"].year].append(trade)

    rows = []

    for year in sorted(groups):
        s = fb.stats(groups[year])
        rows.append(f"{year}: {s['n']} trades, {s['avg']:+.2f}R each")

    return rows


def probe_silver():
    """Ask Twelve Data for 5 silver candles and report exactly what comes back."""

    result = fb.td_get(
        "time_series",
        {"symbol": "XAG/USD", "interval": "1h", "outputsize": 5, "format": "JSON"},
        timeout=30,
    )

    if isinstance(result, dict) and result.get("values"):
        return True, "Silver data is available."

    message = result.get("message") if isinstance(result, dict) else str(result)

    return False, f"Silver data NOT available: {message}"


# ============================================================
# RUN
# ============================================================

def run_slow(data, silver_note):
    sections = []

    common_start = max(
        fb.parse_bar_time(d["sig"][0]["datetime"]) for d in data.values()
    ) + timedelta(days=60)

    last = max(fb.parse_bar_time(d["sig"][-1]["datetime"]) for d in data.values())
    split_time = common_start + (last - common_start) * fb.SPLIT_FRACTION
    days = max(1.0, (last - common_start).days)

    signals = {name: [] for name, _ in ENTRIES}

    for asset, d in data.items():
        found = scan(asset, d["sig"], d["trend"], 4, 24, common_start, ENTRIES)

        for name, items in found.items():
            signals[name].extend(items)

    def build(entry_name, ladder, cost_multiple, side_cap):
        trades = []

        for signal in signals[entry_name]:
            trade = simulate(
                signal, ladder, data[signal["pair"]]["sig"], 4, cost_multiple
            )

            if trade:
                trades.append(trade)

        return apply_caps(trades, side_cap)

    counts = ", ".join(f"{a} {len(data[a]['sig']):,}" for a in data)

    sections.append(
        "🐢 <b>JAY CRYPTO + SILVER SLOW TEST (4H candles, daily trend)</b>  🔒 private\n"
        f"{RULE}\n"
        f"🗓 {common_start:%Y-%m-%d} → {last:%Y-%m-%d}\n"
        f"🔵 Practice → {split_time:%Y-%m-%d} · 🟣 Unseen after\n"
        f"🕯 4H candles: {counts}\n"
        f"🪙 {fb.esc(silver_note)}\n"
        "✅ needs unseen +0.05R, 60+ unseen trades, t-stat 2.0+, "
        "positive on practice"
    )

    rows = []

    for entry_name, _ in ENTRIES:
        net = evaluate(build(entry_name, LADDER_SLOW_V2, 1.0, 2), split_time, days)
        gross = evaluate(build(entry_name, LADDER_SLOW_V2, 0.0, 2), split_time, days)

        if net and gross:
            rows.append(
                f"<b>{fb.esc(entry_name)}</b>\n"
                f"   Before costs: {gross['a']['avg']:+.3f}R per trade\n"
                f"   After costs:  {net['a']['avg']:+.3f}R per trade"
            )

    sections.append(
        "📉 <b>1. EDGE BEFORE AND AFTER COSTS</b>\n"
        f"{RULE}\n" + "\n\n".join(rows)
    )

    cards = []
    winners = []

    for entry_name, _ in ENTRIES:
        for ladder in (LADDER_SLOW_V2, LADDER_SLOW_OLD):
            for side_cap in CRYPTO_SIDE_CAPS:
                trades = build(entry_name, ladder, 1.0, side_cap)
                result = evaluate(trades, split_time, days)
                ok = slow_pass(result)

                label = f"{entry_name} | {ladder['name']} | BTC+ETH same side cap {side_cap}"

                if ok:
                    winners.append((label, result, trades))

                cards.append(card("✅" if ok else "⚠️", label, result))

    sections.append(
        "🏁 <b>2. EVERY COMBINATION</b>\n" f"{RULE}\n" + "\n\n".join(cards)
    )

    notes = []

    if winners:
        winners.sort(key=lambda w: w[1]["u"]["avg"], reverse=True)
        label, result, trades = winners[0]

        asset_rows = []
        good = []

        for asset in data:
            subset = [t for t in trades if t["pair"] == asset]
            p = fb.stats([t for t in subset if t["entry_time"] < split_time])
            u = fb.stats([t for t in subset if t["entry_time"] >= split_time])

            if not p or not u:
                asset_rows.append(f"⚪ {asset}: too few trades")
                continue

            ok = p["avg"] > 0 and u["avg"] > 0 and u["n"] >= 20

            if ok:
                good.append(asset)

            asset_rows.append(
                f"{'✅' if ok else '⚠️'} <b>{asset}</b>: practice "
                f"{p['avg']:+.2f}R ({p['n']}) · unseen {u['avg']:+.2f}R ({u['n']})"
            )

        sides = []

        for name in ("BUY", "SELL"):
            s = fb.stats([t for t in trades if t["direction"] == name])

            if s:
                sides.append(f"{name}: {s['n']} trades, {s['avg']:+.2f}R each")

        stress = " · ".join(
            f"cost x{m}: "
            f"{sum(t['r'] - (m - 1.0) * t['cost_price'] / t['risk'] for t in trades) / len(trades):+.2f}R"
            for m in (1.0, 2.0, 4.0)
        )

        sections.append(
            "🏆 <b>3. BEST SLOW COMBINATION IN DETAIL</b>\n"
            f"<b>{fb.esc(label)}</b>\n{RULE}\n"
            + "\n".join(asset_rows)
            + "\n\nBy side: " + " · ".join(sides)
            + "\n\nBy year:\n" + "\n".join(by_year(trades))
            + f"\n\n💵 Cost stress: {stress}"
        )

        notes.append(f"🏆 Passed: {fb.esc(label)} at {result['per_day']:.2f} signals a day.")

        if good:
            notes.append("✅ Assets that held up alone: " + ", ".join(good))

        weak = [a for a in data if a not in good]

        if weak:
            notes.append("⚠️ Leave out until they pass: " + ", ".join(weak))

        notes.append(
            "⚠️ 8 combinations were tested and the sample is smaller than on "
            "hourly data. A winner runs privately for 2 to 4 weeks first."
        )
    else:
        notes.append(
            "🔴 No slow combination passed either. BTC and ETH have no "
            "reliable edge with this engine on any timeframe we tried."
        )

    sections.append("✅ <b>4. SLOW LANE VERDICT</b>\n" f"{RULE}\n" + "\n\n".join(notes))

    return sections


def run_silver_fast(bars_1h, bars_4h):
    common_start = fb.parse_bar_time(bars_1h[0]["datetime"]) + timedelta(days=15)
    last = fb.parse_bar_time(bars_1h[-1]["datetime"])
    split_time = common_start + (last - common_start) * fb.SPLIT_FRACTION
    days = max(1.0, (last - common_start).days * 5 / 7)

    found = scan("XAG/USD", bars_1h, bars_4h, 1, 4, common_start, ENTRIES)

    cards = []
    winners = []

    for entry_name, _ in ENTRIES:
        for ladder in (fb.LADDER_V2, fb.LADDER_OLD):
            trades = []

            for signal in found[entry_name]:
                trade = simulate(signal, ladder, bars_1h, 1)

                if trade:
                    trades.append(trade)

            capped = apply_caps(trades, 2)
            result = evaluate(capped, split_time, days)
            ok = fast_pass(result)

            label = f"{entry_name} | {ladder['name']}"

            if ok:
                winners.append((label, result))

            cards.append(card("✅" if ok else "⚠️", label, result))

    notes = []

    if winners:
        winners.sort(key=lambda w: w[1]["u"]["avg"], reverse=True)
        label, result = winners[0]

        notes.append(
            f"🏆 Silver on hourly candles passed: {fb.esc(label)}, "
            f"{result['per_day']:.1f} signals per trading day, unseen "
            f"{result['u']['avg']:+.2f}R, z {result['z']:.1f}."
        )
    else:
        notes.append("🔴 Silver on hourly candles did not pass.")

    return [
        "🥈 <b>SILVER ON HOURLY CANDLES (like Gold)</b>\n"
        f"{RULE}\n" + "\n\n".join(cards) + "\n\n" + "\n\n".join(notes)
    ]


# ============================================================
# ENTRY POINT
# ============================================================

def load_assets():
    ok, silver_note = probe_silver()

    assets = ASSETS if ok else [a for a in ASSETS if a != "XAG/USD"]

    data = {}
    failed = []

    for asset in assets:
        print(f"Downloading {asset} 4H and daily...")

        sig = fb.load_history(asset, "4h", PAGES_4H)
        trend = fb.load_history(asset, "1day", PAGES_1D)

        if len(sig) < 600 or len(trend) < 300:
            failed.append(asset)
            continue

        data[asset] = {"sig": sig, "trend": trend}

    return data, failed, ok, silver_note


def main():
    fb.notify(
        "⏳ Slow-timeframe test started (BTC, ETH, silver check). "
        "About 5 to 8 minutes."
    )

    data, failed, silver_ok, silver_note = load_assets()

    fb.notify("🪙 " + silver_note)

    if failed:
        fb.notify("⚠️ Not enough history for: " + ", ".join(failed))

    if not data:
        fb.notify("❌ Slow test stopped: no asset returned history.")
        raise RuntimeError("No asset returned enough history.")

    sections = run_slow(data, silver_note)

    if silver_ok:
        bars_1h = fb.load_history("XAG/USD", "1h", PAGES_1H)
        bars_4h = fb.load_history("XAG/USD", "4h", 1)

        if len(bars_1h) > 1500 and len(bars_4h) > 300:
            sections += run_silver_fast(bars_1h, bars_4h)

    plain = "\n\n".join(fb.strip_tags(section) for section in sections)

    print(plain)

    with open("slow_backtest_report.txt", "w") as handle:
        handle.write(plain)

    for part in fb.pack_messages(sections):
        fb.notify(part, html_mode=True)


if __name__ == "__main__":
    main()
