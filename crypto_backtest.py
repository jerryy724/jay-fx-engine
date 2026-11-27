"""
JAY CRYPTO + SILVER - Backtest

Question: does the Gold-style engine have an edge on Bitcoin, Ethereum and
Silver (XAG/USD), after realistic trading costs?

It downloads about 2 years of hourly candles plus 4H candles, replays three
entry methods and two exit ladders, under realistic risk caps:
- Entries: old-style hourly rotation (always trades), v2 strict, v2 with
  pullbacks + ADX floor 10 (the setting that worked on Gold).
- Exits: v2 ladder (1R/2R/3R, close 40/30/30, stop to entry after TP1,
  72 hour stop) and the old FX ladder (1.0/2.0/3.2/4.5 ATR, trailing stop).
- Caps: one trade per asset, 3 in total, and BTC + ETH on the same side
  counted together (tested with a cap of 1 and of 2).
- Costs: a percentage of price per trade (assumptions below, edit them).

Judged on the first 60% (practice) and must hold on the last 40% (unseen).
Pass bar: practice > 0, unseen >= +0.05R, 150+ unseen trades, daily z >= 2.0.

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

# Round-trip cost per trade as a share of price (spread + fees + slippage).
# ASSUMPTIONS: edit them to match your broker or exchange.
COST_PCT = {
    "BTC/USD": 0.0005,   # 0.05%
    "ETH/USD": 0.0007,   # 0.07%
    "XAG/USD": 0.0008,   # 0.08%
}

GROUP = {"BTC/USD": "CRYPTO", "ETH/USD": "CRYPTO", "XAG/USD": "METAL"}

MAX_OPEN_PER_ASSET = 1
MAX_OPEN_TOTAL = 3
CRYPTO_SIDE_CAPS = (1, 2)

MIN_Z = 2.0

ENTRIES = [
    ("OLD-style rotation (one asset per hour, always trades)", "LEGACY", None),
    ("v2 entries, strict", "V2", fb.PARAMS_STRICT),
    ("v2 entries, pullbacks + ADX 10", "V2", fb.PARAMS_BE),
]

LADDERS = [fb.LADDER_V2, fb.LADDER_OLD]

RULE = fb.RULE
PAGES_1H = 3
PAGES_4H = 1


# ============================================================
# 1. FIND SIGNALS FOR ONE ASSET
# ============================================================

def scan_asset(asset, bars_1h, bars_4h, common_start):
    starts_1h = [fb.parse_bar_time(b["datetime"]) for b in bars_1h]
    starts_4h = [fb.parse_bar_time(b["datetime"]) for b in bars_4h]

    out = {entry[0]: [] for entry in ENTRIES}

    for i in range(230, len(bars_1h)):
        now = starts_1h[i] + timedelta(hours=1)

        if now < common_start:
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
                feats = fb.features(window_1h, window_4h)
        except Exception:
            feats = None

        for name, kind, params in ENTRIES:
            if kind == "V2":
                if feats is None:
                    continue

                signal, _ = fb.decide(asset, feats, params, now)

            else:
                if ASSETS[now.hour % len(ASSETS)] != asset:
                    continue

                signal = fb.legacy_signal(
                    asset, bars_1h[max(0, i - 219):i + 1], now
                )

            if signal:
                signal["index"] = i
                out[name].append(signal)

    return out


# ============================================================
# 2. SIMULATE ONE TRADE (cost = share of price)
# ============================================================

def simulate(signal, profile, bars_1h, cost_multiple=1.0):
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

    cost_price = entry * COST_PCT[asset] * cost_multiple
    realized -= cost_price

    return {
        "pair": asset,
        "direction": signal["direction"],
        "entry_time": signal["time"],
        "exit_time": fb.parse_bar_time(bars_1h[exit_index]["datetime"])
        + timedelta(hours=1),
        "r": realized / risk,
        "risk": risk,
        "cost_price": entry * COST_PCT[asset],
        "hold": exit_index - i,
    }


# ============================================================
# 3. PORTFOLIO RULES
# ============================================================

def apply_caps(trades, crypto_side_cap):
    kept = []
    open_now = []

    for trade in sorted(trades, key=lambda t: t["entry_time"]):
        open_now = [o for o in open_now if o["exit_time"] > trade["entry_time"]]

        same_asset = sum(1 for o in open_now if o["pair"] == trade["pair"])

        if same_asset >= MAX_OPEN_PER_ASSET:
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


def passes(result):
    return bool(
        result
        and result["p"]["avg"] > 0
        and result["u"]["avg"] >= fb.MIN_UNSEEN_R
        and result["u"]["n"] >= fb.MIN_UNSEEN_TRADES
        and result["z"] >= MIN_Z
    )


def card(icon, name, result):
    if not result:
        return f"⚪ {fb.esc(name)}: too few trades"

    return (
        f"{icon} <b>{fb.esc(name)}</b>\n"
        f"   📡 {result['per_day']:.1f}/day · "
        f"🔵 {result['p']['avg']:+.2f}R ({result['p']['n']}) · "
        f"🟣 {result['u']['avg']:+.2f}R ({result['u']['n']}) · "
        f"z {result['z']:.1f} · dip {result['a']['dd']:.0f}R"
    )


# ============================================================
# 4. RUN AND REPORT
# ============================================================

def run(data):
    common_start = max(
        fb.parse_bar_time(d["1h"][0]["datetime"]) for d in data.values()
    ) + timedelta(days=15)

    last = max(fb.parse_bar_time(d["1h"][-1]["datetime"]) for d in data.values())

    split_time = common_start + (last - common_start) * fb.SPLIT_FRACTION
    days = max(1.0, (last - common_start).days)

    signals = {entry[0]: [] for entry in ENTRIES}

    for asset, d in data.items():
        found = scan_asset(asset, d["1h"], d["4h"], common_start)

        for name, items in found.items():
            signals[name].extend(items)

    def build(entry_name, ladder, cost_multiple, side_cap):
        trades = []

        for signal in signals[entry_name]:
            trade = simulate(
                signal, ladder, data[signal["pair"]]["1h"], cost_multiple
            )

            if trade:
                trades.append(trade)

        return apply_caps(trades, side_cap)

    sections = []

    counts = ", ".join(f"{a} {len(data[a]['1h']):,}" for a in data)
    costs = ", ".join(
        f"{a.split('/')[0]} {100 * COST_PCT[a]:.2f}%" for a in data
    )

    sections.append(
        "🪙 <b>JAY CRYPTO + SILVER BACKTEST</b>  🔒 private\n"
        f"{RULE}\n"
        f"🗓 {common_start:%Y-%m-%d} → {last:%Y-%m-%d}\n"
        f"🔵 Practice → {split_time:%Y-%m-%d} · 🟣 Unseen after\n"
        f"🕯 Hourly candles: {counts}\n"
        f"💵 Round-trip cost assumed: {costs}\n"
        f"🔒 Caps: {MAX_OPEN_PER_ASSET} per asset · {MAX_OPEN_TOTAL} total · "
        f"BTC+ETH same side tested at 1 and 2\n"
        "✅ needs unseen +0.05R, 150+ unseen trades, daily z of 2.0+"
    )

    # ---- gross versus net -------------------------------------------------
    rows = []

    for entry_name, _, _ in ENTRIES:
        net = fb.evaluate(build(entry_name, fb.LADDER_V2, 1.0, 2), split_time, days)
        gross = fb.evaluate(build(entry_name, fb.LADDER_V2, 0.0, 2), split_time, days)

        if net and gross:
            rows.append(
                f"<b>{fb.esc(entry_name)}</b>\n"
                f"   Before costs: {gross['a']['avg']:+.3f}R per trade\n"
                f"   After costs:  {net['a']['avg']:+.3f}R per trade"
            )

    sections.append(
        "📉 <b>1. HOW MUCH EDGE IS THERE BEFORE COSTS?</b>\n"
        "v2 ladder, BTC+ETH cap 2.\n"
        f"{RULE}\n" + "\n\n".join(rows)
    )

    # ---- every combination --------------------------------------------------
    cards = []
    winners = []

    for entry_name, _, _ in ENTRIES:
        for ladder in LADDERS:
            for side_cap in CRYPTO_SIDE_CAPS:
                trades = build(entry_name, ladder, 1.0, side_cap)
                result = fb.evaluate(trades, split_time, days)

                label = (
                    f"{entry_name} | {ladder['name']} | "
                    f"BTC+ETH same side cap {side_cap}"
                )

                ok = passes(result)

                if ok:
                    winners.append((label, result, trades))

                cards.append(card("✅" if ok else "⚠️", label, result))

    chunk = 6

    for start in range(0, len(cards), chunk):
        sections.append(
            f"🏁 <b>2. EVERY COMBINATION ({start // chunk + 1} of "
            f"{(len(cards) + chunk - 1) // chunk})</b>\n"
            f"{RULE}\n" + "\n\n".join(cards[start:start + chunk])
        )

    # ---- verdict --------------------------------------------------------------
    notes = []

    if winners:
        winners.sort(key=lambda w: w[1]["u"]["avg"], reverse=True)

        notes.append("🏆 Combinations that passed, best unseen result first:")

        for label, result, _ in winners[:5]:
            notes.append(
                f"• {fb.esc(label)}: {result['per_day']:.1f}/day, unseen "
                f"{result['u']['avg']:+.2f}R, z {result['z']:.1f}"
            )

        label, result, trades = winners[0]

        asset_rows = []
        good = []

        for asset in data:
            subset = [t for t in trades if t["pair"] == asset]
            practice = [t for t in subset if t["entry_time"] < split_time]
            unseen = [t for t in subset if t["entry_time"] >= split_time]

            p, u = fb.stats(practice), fb.stats(unseen)

            if not p or not u:
                asset_rows.append(f"⚪ {asset}: too few trades")
                continue

            ok = p["avg"] > 0 and u["avg"] > 0 and u["n"] >= 40

            if ok:
                good.append(asset)

            asset_rows.append(
                f"{'✅' if ok else '⚠️'} <b>{asset}</b>: practice "
                f"{p['avg']:+.2f}R ({p['n']}) · unseen {u['avg']:+.2f}R ({u['n']})"
            )

        buys = [t for t in trades if t["direction"] == "BUY"]
        sells = [t for t in trades if t["direction"] == "SELL"]

        side_rows = []

        for name, subset in (("BUY", buys), ("SELL", sells)):
            s = fb.stats(subset)

            if s:
                side_rows.append(f"{name}: {s['n']} trades, {s['avg']:+.2f}R each")

        stress = " · ".join(
            f"cost x{m}: "
            f"{sum(t['r'] - (m - 1.0) * t['cost_price'] / t['risk'] for t in trades) / len(trades):+.2f}R"
            for m in (1.0, 1.5, 2.0)
        )

        sections.append(
            "🏆 <b>3. BEST COMBINATION IN DETAIL</b>\n"
            f"<b>{fb.esc(label)}</b>\n{RULE}\n"
            + "\n".join(asset_rows)
            + "\n\nBy side: " + " · ".join(side_rows)
            + f"\n💵 Cost stress, average R: {stress}"
        )

        if good:
            notes.append("✅ Assets that held up on their own: " + ", ".join(good))

        weak = [a for a in data if a not in good]

        if weak:
            notes.append(
                "⚠️ Assets that did not hold up alone (leave them out until "
                "they pass): " + ", ".join(weak)
            )

        notes.append(
            "⚠️ 12 combinations were tested, so one can look good by luck. "
            "A winner runs privately for 2 weeks before it goes public."
        )
    else:
        notes.append(
            "🔴 Nothing passed. We do not rebuild the channel on this "
            "evidence. Honest next options: slower timeframes, or a single "
            "asset test."
        )

    sections.append("✅ <b>4. VERDICT</b>\n" + f"{RULE}\n" + "\n\n".join(notes))

    return sections


def main():
    fb.notify(
        "⏳ Crypto + Silver backtest started. Downloading BTC, ETH and XAG "
        "candles. About 3 to 5 minutes."
    )

    data = {}
    failed = []

    for asset in ASSETS:
        print(f"Downloading {asset}...")

        bars_1h = fb.load_history(asset, "1h", PAGES_1H)
        bars_4h = fb.load_history(asset, "4h", PAGES_4H)

        if len(bars_1h) < 1000 or len(bars_4h) < 300:
            failed.append(asset)
            continue

        data[asset] = {"1h": bars_1h, "4h": bars_4h}

    if failed:
        fb.notify("⚠️ Could not load enough history for: " + ", ".join(failed))

    if not data:
        fb.notify("❌ Crypto backtest stopped: no asset returned history.")
        raise RuntimeError("No asset returned enough history.")

    sections = run(data)

    plain = "\n\n".join(fb.strip_tags(section) for section in sections)

    print(plain)

    with open("crypto_backtest_report.txt", "w") as handle:
        handle.write(plain)

    for part in fb.pack_messages(sections):
        fb.notify(part, html_mode=True)


if __name__ == "__main__":
    main()
