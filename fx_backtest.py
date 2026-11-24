"""
JAY FX - Backtest

Answers two questions with real candles:
1. What did the OLD FX engine really earn (hourly rotation, always trades)?
2. Does the new v2 engine (same tested logic as Gold, per pair) do better?

For each pair it downloads about 2.4 years of hourly candles plus 4H candles,
replays every entry rule, and simulates two exit ladders:
- v2 ladder: 1R / 2R / 3R, close 40/30/30, stop to entry after TP1, 72 bar stop
- old FX ladder: 1.0 / 2.0 / 3.2 / 4.5 ATR, 25% each, trailing stop ratchet

All combinations run under the SAME risk caps (one trade per pair, a total
cap, and a cap per USD side) and the same spread assumptions (config.py).
Rules are judged on the first 60% of time (practice) and must hold on the
last 40% (unseen). Results are evidence, not a promise.
"""

import bisect
import io
import math
import re
import html
from collections import defaultdict
from contextlib import redirect_stdout
from datetime import timedelta

import config
import fx_engine
import fx_history
import admin
from indicators import parse_bar_time, closed_bars

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
                feats = fx_engine.features(window_1h, window_4h)
        except Exception:
            feats = None

        for name, kind, params in ENTRIES:
            if kind == "V2":
                if feats is None:
                    continue

                signal, _ = fx_engine.decide(pair, feats, params, now)

            else:
                if rotation[now.hour % len(rotation)] != pair:
                    continue

                if now.weekday() > 4:
                    continue

                signal = fx_engine.legacy_signal(
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


def light(avg):
    return "🟢" if avg >= 0.10 else "🟡" if avg >= 0.0 else "🔴"


def pf_text(s):
    return "∞" if s["pf"] == float("inf") else f"{s['pf']:.2f}"


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


def main():
    data = {}

    for pair in config.FX_PAIRS:
        print(f"Downloading {pair}...")

        bars_1h = fx_history.load(pair, "1h", PAGES_1H)
        bars_4h = fx_history.load(pair, "4h", PAGES_4H)

        if len(bars_1h) < 1000 or len(bars_4h) < 300:
            print(f"Skipping {pair}: not enough history.")
            continue

        data[pair] = {"1h": bars_1h, "4h": bars_4h}

    if not data:
        raise RuntimeError("No pair returned enough history.")

    sections = run(data)

    plain = "\n\n".join(strip_tags(s) for s in sections)

    print(plain)

    with open("fx_backtest_report.txt", "w") as handle:
        handle.write(plain)

    for part in pack_messages(sections):
        admin.notify(part, html=True)


if __name__ == "__main__":
    main()
