"""
JAY FX - Cost-aware test

The first backtest showed every FX combination losing after spreads. This
test asks whether an edge exists once we refuse to trade when the spread is
too expensive relative to the stop, and shows results BEFORE spreads (gross)
next to AFTER spreads (net).

Needs fx_backtest.py in the same folder (the single-file version).
Entries: old rotation, v2 strict, v2 pullbacks + ADX 10.
Filters: none, cost gate 0.10R / 0.07R / 0.05R, London+NY hours + gate 0.07R.
Exits: v2 ladder and old FX ladder. Same risk caps as before.

Pass bar (stricter, 30 combinations are tested):
practice > 0, unseen >= +0.05R, 150+ unseen trades, daily z >= 2.0.
"""

import fx_backtest as fb

# We only borrow the tools inside fx_backtest.py, not its main().
fb._RAN["main"] = True

config = fb.config

MIN_Z = 2.0

FILTERS = [
    ("no filter", None, None),
    ("cost gate 0.10R", 0.10, None),
    ("cost gate 0.07R", 0.07, None),
    ("cost gate 0.05R", 0.05, None),
    ("London+NY hours, cost gate 0.07R", 0.07, (7, 17)),
]

LADDERS = [fb.LADDER_V2, fb.LADDER_OLD]


def cost_in_r(signal):
    """Spread cost as a share of one unit of risk (1.5 ATR)."""

    settings = config.PAIR_SETTINGS[signal["pair"]]
    cost_price = settings["spread_pips"] * settings["pip"]

    return cost_price / (1.5 * signal["atr"])


def keep(signal, gate, hours):
    if gate is not None and cost_in_r(signal) > gate:
        return False

    if hours and not (hours[0] <= signal["time"].hour < hours[1]):
        return False

    return True


def passes(result):
    return bool(
        result
        and result["p"]["avg"] > 0
        and result["u"]["avg"] >= fb.MIN_UNSEEN_R
        and result["u"]["n"] >= fb.MIN_UNSEEN_TRADES
        and result["z"] >= MIN_Z
    )


def run_trades(signals, ladder, data):
    trades = []

    for signal in signals:
        trade = fb.simulate(signal, ladder, data[signal["pair"]]["1h"])

        if trade:
            trades.append(trade)

    return fb.apply_caps(trades)


def run_gross(signals, ladder, data):
    """Same trades with zero spread cost."""

    saved = {
        pair: values["spread_pips"]
        for pair, values in config.PAIR_SETTINGS.items()
    }

    for values in config.PAIR_SETTINGS.values():
        values["spread_pips"] = 0.0

    try:
        return run_trades(signals, ladder, data)
    finally:
        for pair, spread in saved.items():
            config.PAIR_SETTINGS[pair]["spread_pips"] = spread


def line(icon, name, result):
    if not result:
        return f"⚪ {fb.esc(name)}: too few trades"

    return (
        f"{icon} <b>{fb.esc(name)}</b>\n"
        f"   📡 {result['per_day']:.1f}/day · "
        f"🔵 {result['p']['avg']:+.2f}R ({result['p']['n']}) · "
        f"🟣 {result['u']['avg']:+.2f}R ({result['u']['n']}) · "
        f"z {result['z']:.1f}"
    )


def average_cost_by_pair(signals):
    rows = []

    for pair in config.FX_PAIRS:
        costs = [cost_in_r(s) for s in signals if s["pair"] == pair]

        if costs:
            rows.append(
                f"   {pair}: {sum(costs) / len(costs):.2f}R per trade "
                f"({config.PAIR_SETTINGS[pair]['spread_pips']} pip spread)"
            )

    return rows


def run(data):
    all_first = min(
        fb.parse_bar_time(d["1h"][0]["datetime"]) for d in data.values()
    )
    all_last = max(
        fb.parse_bar_time(d["1h"][-1]["datetime"]) for d in data.values()
    )

    split_time = all_first + (all_last - all_first) * fb.SPLIT_FRACTION
    days = max(1.0, (all_last - all_first).days * 5 / 7)

    signals = {entry[0]: [] for entry in fb.ENTRIES}

    for pair, d in data.items():
        found = fb.scan_pair(pair, d["1h"], d["4h"])

        for name, items in found.items():
            signals[name].extend(items)

    sections = []

    v2_signals = signals[fb.ENTRIES[1][0]]

    sections.append(
        "🧮 <b>JAY FX COST-AWARE TEST</b>  🔒 private\n"
        f"{fb.RULE}\n"
        f"🗓 {all_first:%Y-%m-%d} → {all_last:%Y-%m-%d}\n"
        f"🔵 Practice → {split_time:%Y-%m-%d} · 🟣 Unseen after\n"
        "Average spread cost per trade, in R (v2 strict signals):\n"
        + "\n".join(average_cost_by_pair(v2_signals))
        + "\n✅ needs unseen +0.05R, 150+ unseen trades, daily z of 2.0+"
    )

    # ---- gross vs net --------------------------------------------------
    rows = []

    for entry_name, _, _ in fb.ENTRIES:
        net = fb.evaluate(
            run_trades(signals[entry_name], fb.LADDER_V2, data),
            split_time,
            days,
        )
        gross = fb.evaluate(
            run_gross(signals[entry_name], fb.LADDER_V2, data),
            split_time,
            days,
        )

        if net and gross:
            rows.append(
                f"<b>{fb.esc(entry_name)}</b>\n"
                f"   Before spreads: {gross['a']['avg']:+.3f}R per trade\n"
                f"   After spreads:  {net['a']['avg']:+.3f}R per trade"
            )

    sections.append(
        "📉 <b>1. HOW MUCH EDGE IS THERE BEFORE SPREADS?</b>\n"
        "v2 ladder, no filter.\n"
        f"{fb.RULE}\n" + "\n\n".join(rows)
    )

    # ---- the matrix ----------------------------------------------------
    cards = []
    winners = []

    for entry_name, _, _ in fb.ENTRIES:
        for filter_name, gate, hours in FILTERS:
            chosen = [
                s for s in signals[entry_name] if keep(s, gate, hours)
            ]

            for ladder in LADDERS:
                trades = run_trades(chosen, ladder, data)
                result = fb.evaluate(trades, split_time, days)

                label = f"{entry_name} | {filter_name} | {ladder['name']}"

                icon = "✅" if passes(result) else "⚠️"

                if passes(result):
                    winners.append((label, result, trades))

                cards.append(line(icon, label, result))

    chunk = 10

    for start in range(0, len(cards), chunk):
        sections.append(
            f"🏁 <b>2. EVERY COMBINATION ({start // chunk + 1} of "
            f"{(len(cards) + chunk - 1) // chunk})</b>\n"
            f"{fb.RULE}\n" + "\n\n".join(cards[start:start + chunk])
        )

    # ---- verdict -------------------------------------------------------
    notes = []

    if winners:
        winners.sort(key=lambda w: w[1]["u"]["avg"], reverse=True)

        notes.append("🏆 Combinations that passed, best unseen result first:")

        for label, result, _ in winners[:5]:
            notes.append(
                f"• {fb.esc(label)}: {result['per_day']:.1f}/day, unseen "
                f"{result['u']['avg']:+.2f}R, z {result['z']:.1f}"
            )

        best_trades = winners[0][2]

        pair_rows = []

        for pair in config.FX_PAIRS:
            subset = [t for t in best_trades if t["pair"] == pair]
            practice = [t for t in subset if t["entry_time"] < split_time]
            unseen = [t for t in subset if t["entry_time"] >= split_time]

            p, u = fb.stats(practice), fb.stats(unseen)

            if p and u:
                pair_rows.append(
                    f"{pair}: practice {p['avg']:+.2f}R ({p['n']}), "
                    f"unseen {u['avg']:+.2f}R ({u['n']})"
                )

        notes.append("Pair by pair for the best one:\n" + "\n".join(pair_rows))
        notes.append(
            "⚠️ 30 combinations were tested, so one can look good by luck. "
            "A winner runs privately for 2 weeks before anything goes public."
        )
    else:
        notes.append(
            "🔴 Nothing passed, even with cost gates. On hourly candles FX "
            "does not beat its own spread on this evidence. The honest "
            "options are a slower timeframe, or stop posting FX trade "
            "signals and use the channel for market analysis."
        )

    sections.append("✅ <b>3. VERDICT</b>\n" + f"{fb.RULE}\n" + "\n\n".join(notes))

    return sections


def main():
    fb.notify(
        "⏳ FX cost-aware test started. Downloading candles for 6 pairs. "
        "About 6 to 9 minutes."
    )

    data = {}
    failed = []

    for pair in config.FX_PAIRS:
        print(f"Downloading {pair}...")

        bars_1h = fb.load_history(pair, "1h", fb.PAGES_1H)
        bars_4h = fb.load_history(pair, "4h", fb.PAGES_4H)

        if len(bars_1h) < 1000 or len(bars_4h) < 300:
            failed.append(pair)
            continue

        data[pair] = {"1h": bars_1h, "4h": bars_4h}

    if failed:
        fb.notify("⚠️ Could not load enough history for: " + ", ".join(failed))

    if not data:
        fb.notify("❌ Cost-aware test stopped: no pair returned history.")
        raise RuntimeError("No pair returned enough history.")

    sections = run(data)

    plain = "\n\n".join(fb.strip_tags(section) for section in sections)

    print(plain)

    with open("fx_costtest_report.txt", "w") as handle:
        handle.write(plain)

    for part in fb.pack_messages(sections):
        fb.notify(part, html_mode=True)


if __name__ == "__main__":
    main()
