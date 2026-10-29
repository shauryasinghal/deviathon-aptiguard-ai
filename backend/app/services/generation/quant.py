"""Quantitative-reasoning templates. Answers are recomputed from stored parameters during validation."""
from __future__ import annotations

import itertools
import random
from fractions import Fraction

from app.services.generation.base import Check, GeneratedItem, Template, build_options, expect_correct, fmt_num, pick

ITEMS = ["a laptop", "a bicycle", "a smartwatch", "a textbook", "a pair of headphones", "a desk chair",
         "a monthly metro pass", "a cricket bat", "a backpack", "an electric kettle"]
PEOPLE = ["Asha", "Ravi", "Meera", "Kabir", "Nisha", "Arjun", "Farah", "Dev", "Ishaan", "Lena", "Tara", "Omar"]
VEHICLES = ["a train", "a bus", "a cyclist", "a delivery van", "a ferry", "a car"]


# ---------------------------------------------------------------- percentage change
def _pct_compute(p: dict) -> Fraction:
    if p["mode"] == "successive":
        return (1 + Fraction(p["x"], 100)) * (1 - Fraction(p["y"], 100)) * 100 - 100
    return Fraction(p["new"] - p["old"], p["old"]) * 100


def _pct_generate(rng: random.Random, difficulty: str) -> GeneratedItem:
    thing = pick(rng, ITEMS)
    if difficulty == "hard":
        x, y = pick(rng, [(a, b) for a in (5, 10, 15, 20, 25, 30, 40, 50) for b in (5, 10, 15, 20, 25, 30, 40, 50)])
        p = {"mode": "successive", "x": x, "y": y, "thing": thing}
        ans = _pct_compute(p)
        stem = (f"The price of {thing} is first increased by {x}% and the new price is then reduced by {y}%. "
                f"What is the net percentage change in the original price?")
        fmt = lambda v: (f"{fmt_num(abs(v))}% {'increase' if v > 0 else 'decrease'}" if v != 0 else "No change")
        correct = fmt(ans)
        distract = [(fmt(Fraction(x - y)), "Adds percentages naively"),
                    (fmt(-ans if ans != 0 else Fraction(5)), "Sign error"),
                    (fmt(Fraction(x * y, 100)), "Uses only the cross term")]
        expl = (f"Multiply the factors: (1 + {x}/100) × (1 − {y}/100) = {fmt_num(1 + ans / 100, decimals=4)}. "
                f"Net change = {fmt_num(ans)}%.")
    else:
        if difficulty == "easy":
            old = pick(rng, [200, 400, 500, 800, 1200, 1500, 2000, 2500])
            pct = pick(rng, [10, 20, 25, 40, 50])
            sign = 1
        else:
            old = pick(rng, [160, 240, 320, 480, 640, 800, 960, 1600])
            pct = pick(rng, [12.5, 37.5, 15, 35, 62.5, 7.5])
            sign = pick(rng, [1, -1])
        new = int(old + sign * old * pct / 100)
        p = {"mode": "simple", "old": old, "new": new, "thing": thing}
        ans = _pct_compute(p)
        verb = "rises" if new > old else "falls"
        stem = f"The price of {thing} {verb} from ₹{old} to ₹{new}. What is the percentage {'increase' if new > old else 'decrease'}?"
        correct = fmt_num(abs(ans), "%")
        wrong_base = Fraction(abs(new - old), new) * 100
        distract = [(fmt_num(wrong_base, "%"), "Divides by the new price instead of the original"),
                    (fmt_num(abs(new - old) / 10, "%"), "Treats the rupee change as a percentage scale"),
                    (fmt_num(abs(ans) + 5, "%"), "Arithmetic slip")]
        expl = f"Change = {abs(new - old)}; percentage = {abs(new - old)}/{old} × 100 = {fmt_num(abs(ans))}%."
    if p["mode"] == "successive":
        fb = lambda i: fmt(ans + (5 * i if ans >= 0 else -5 * i))
    else:
        fb = lambda i: fmt_num(abs(ans) + 2.5 * i, "%")
    opts = build_options(rng, correct, distract, fb)
    return GeneratedItem("QUANT", "QT-PCT", "Percentage change", "percentages", difficulty, stem, opts, expl, p,
                         tags=["percentages", "arithmetic"])


def _pct_verify(p: dict, item: GeneratedItem) -> list[Check]:
    ans = _pct_compute(p)
    if p["mode"] == "successive":
        exp = f"{fmt_num(abs(ans))}% {'increase' if ans > 0 else 'decrease'}" if ans != 0 else "No change"
    else:
        exp = fmt_num(abs(ans), "%")
    return expect_correct(item, exp, "percentage change")


# ---------------------------------------------------------------- speed / distance / time
_AVG_PAIRS = [(a, b) for a in range(10, 121, 5) for b in range(a + 5, 151, 5)
              if (2 * a * b) % (a + b) == 0 and b <= 3 * a]
def _sdt_compute(p: dict) -> Fraction:
    if p["mode"] == "proportional":
        return Fraction(p["d2"] * p["t"], p["d"])
    if p["mode"] == "average":
        return Fraction(2 * p["v1"] * p["v2"], p["v1"] + p["v2"])
    # crossing: lengths in metres, speeds in km/h, opposite directions -> seconds
    rel = Fraction(p["v1"] + p["v2"]) * Fraction(5, 18)
    return Fraction(p["l1"] + p["l2"]) / rel


def _sdt_generate(rng: random.Random, difficulty: str) -> GeneratedItem:
    who = pick(rng, VEHICLES)
    if difficulty == "easy":
        speed = pick(rng, [40, 45, 50, 60, 72, 80])
        t = pick(rng, [2, 3, 4, 5])
        d = speed * t
        d2 = speed * pick(rng, [6, 7, 8, 9])
        p = {"mode": "proportional", "d": d, "t": t, "d2": d2, "who": who}
        ans = _sdt_compute(p)
        stem = f"{who.capitalize()} covers {d} km in {t} hours at a constant speed. How many hours will it take to cover {d2} km?"
        correct = fmt_num(ans, "hours")
        distract = [(fmt_num(ans + 1, "hours"), "Off-by-one"), (fmt_num(Fraction(d2, t), "hours"), "Divides distance by time"),
                    (fmt_num(ans - 1, "hours"), "Off-by-one")]
        expl = f"Speed = {d}/{t} = {speed} km/h. Time = {d2}/{speed} = {fmt_num(ans)} hours."
        fb = lambda i: fmt_num(ans + i + 1, "hours")
    elif difficulty == "medium":
        v1, v2 = pick(rng, _AVG_PAIRS)
        p = {"mode": "average", "v1": v1, "v2": v2, "who": who}
        ans = _sdt_compute(p)
        stem = (f"{who.capitalize()} travels from town P to town Q at {v1} km/h and returns along the same route at "
                f"{v2} km/h. What is its average speed for the whole journey?")
        correct = fmt_num(ans, "km/h")
        distract = [(fmt_num(Fraction(v1 + v2, 2), "km/h"), "Arithmetic mean of speeds (ignores time weighting)"),
                    (fmt_num(Fraction(v2 - v1), "km/h"), "Difference of speeds"),
                    (fmt_num(ans + 4, "km/h"), "Arithmetic slip")]
        expl = f"For equal distances, average speed = 2·v1·v2/(v1+v2) = 2·{v1}·{v2}/{v1 + v2} = {fmt_num(ans)} km/h."
        fb = lambda i: fmt_num(ans + 2 * i, "km/h")
    else:
        rel_ms = pick(rng, [10, 15, 20, 25, 30])
        total = rel_ms * rng.randint(8, 20)
        l1 = int(round(total * rng.uniform(0.35, 0.65) / 10) * 10)
        l2 = total - l1
        kmh = rel_ms * 18 // 5
        v1 = 9 * rng.randint(1, kmh // 9 - 1)
        v2 = kmh - v1
        p = {"mode": "crossing", "l1": l1, "l2": l2, "v1": v1, "v2": v2}
        ans = _sdt_compute(p)
        stem = (f"Two trains of lengths {l1} m and {l2} m run on parallel tracks in opposite directions at {v1} km/h "
                f"and {v2} km/h. How long do they take to cross each other completely?")
        correct = fmt_num(ans, "seconds")
        same_dir = (Fraction(l1 + l2) / (Fraction(abs(v1 - v2) or 1) * Fraction(5, 18)))
        distract = [(fmt_num(same_dir, "seconds"), "Uses relative speed for the same direction"),
                    (fmt_num(Fraction(l1 + l2) / Fraction(v1 + v2), "seconds"), "Forgets km/h → m/s conversion"),
                    (fmt_num(Fraction(max(l1, l2)) / (Fraction(v1 + v2) * Fraction(5, 18)), "seconds"), "Uses one train's length")]
        expl = (f"Relative speed = ({v1}+{v2}) km/h = {fmt_num(Fraction(v1 + v2) * Fraction(5, 18))} m/s. "
                f"Distance = {l1}+{l2} = {l1 + l2} m. Time = {fmt_num(ans)} s.")
        fb = lambda i: fmt_num(ans + 3 * i, "seconds")
    opts = build_options(rng, correct, distract, fb)
    return GeneratedItem("QUANT", "QT-SDT", "Speed, distance and time", "rates", difficulty, stem, opts, expl, p,
                         tags=["rates", "speed-distance-time"])


def _sdt_verify(p: dict, item: GeneratedItem) -> list[Check]:
    unit = {"proportional": "hours", "average": "km/h", "crossing": "seconds"}[p["mode"]]
    return expect_correct(item, fmt_num(_sdt_compute(p), unit), "value")


# ---------------------------------------------------------------- work and time
_WORK_PAIRS = [(a, b) for a in range(4, 41) for b in range(a + 2, 61) if (a * b) % (a + b) == 0]
_WORK_TRIPLES = [(a, b, c) for a in range(4, 31) for b in range(a + 1, 41) for c in range(b + 1, 61)
                 if (a * b * c) % (a * b + b * c + a * c) == 0][:200]
_WORK_LEAVES = [((a, b), k) for (a, b) in _WORK_PAIRS for k in range(2, a)
                if (1 - k * Fraction(a + b, a * b)) > 0 and (k + (1 - k * Fraction(a + b, a * b)) * b).denominator == 1][:300]
def _work_compute(p: dict) -> Fraction:
    rates = [Fraction(1, d) for d in p["days"]]
    if p["mode"] == "together":
        return 1 / sum(rates)
    # A and B work together for k days, then A leaves; time for B to finish (total days)
    done = p["k"] * (rates[0] + rates[1])
    return p["k"] + (1 - done) / rates[1]


def _work_generate(rng: random.Random, difficulty: str) -> GeneratedItem:
    a, b = pick(rng, PEOPLE), pick(rng, [n for n in PEOPLE])
    while b == a:
        b = pick(rng, PEOPLE)
    if difficulty == "easy":
        days = pick(rng, _WORK_PAIRS)
        p = {"mode": "together", "days": list(days), "names": [a, b]}
        ans = _work_compute(p)
        stem = f"{a} can complete a task in {days[0]} days and {b} can complete it in {days[1]} days. Working together, how many days will they take?"
        distract = [(fmt_num(Fraction(sum(days), 2), "days"), "Averages the two durations"),
                    (fmt_num(Fraction(sum(days)), "days"), "Adds the durations"), (fmt_num(ans + 2, "days"), "Arithmetic slip")]
    elif difficulty == "medium":
        c = pick(rng, [n for n in PEOPLE if n not in (a, b)])
        days = pick(rng, _WORK_TRIPLES)
        p = {"mode": "together", "days": list(days), "names": [a, b, c]}
        ans = _work_compute(p)
        stem = (f"{a}, {b} and {c} can finish a job alone in {days[0]}, {days[1]} and {days[2]} days respectively. "
                f"How many days will they take working together?")
        distract = [(fmt_num(Fraction(sum(days), 3), "days"), "Averages the durations"),
                    (fmt_num(Fraction(min(days), 3), "days"), "Divides the fastest time by three"),
                    (fmt_num(ans + 1, "days"), "Arithmetic slip")]
    else:
        days, k = pick(rng, _WORK_LEAVES)
        p = {"mode": "a_leaves", "days": list(days), "k": k, "names": [a, b]}
        ans = _work_compute(p)
        stem = (f"{a} alone can finish a job in {days[0]} days and {b} alone in {days[1]} days. They start together, "
                f"but {a} leaves after {k} days. In how many days from the start is the job completed?")
        rem = ans - k
        distract = [(fmt_num(rem, "days"), "Reports only the remaining days"),
                    (fmt_num(1 / (Fraction(1, days[0]) + Fraction(1, days[1])), "days"), "Assumes both work throughout"),
                    (fmt_num(ans + 2, "days"), "Arithmetic slip")]
    expl = "Add the daily work rates (1/days for each person) and invert to get the time." if p["mode"] == "together" else \
        f"Together they finish {k}×(1/{days[0]} + 1/{days[1]}) of the job; {b} completes the rest at 1/{days[1]} per day."
    opts = build_options(rng, fmt_num(ans, "days"), distract, lambda i: fmt_num(ans + i + 2, "days"))
    return GeneratedItem("QUANT", "QT-WORK", "Work and time", "rates", difficulty, stem, opts,
                         expl + f" Answer: {fmt_num(ans)} days.", p, tags=["work-time", "rates"])


def _work_verify(p: dict, item: GeneratedItem) -> list[Check]:
    return expect_correct(item, fmt_num(_work_compute(p), "days"), "duration")


# ---------------------------------------------------------------- interest
def _int_compute(p: dict) -> Fraction:
    P, r, t = p["P"], Fraction(p["r"], 100), p["t"]
    if p["mode"] == "simple":
        return P * r * t
    if p["mode"] == "compound":
        return P * (1 + r) ** t - P
    return P * r * r  # CI - SI for 2 years


def _int_generate(rng: random.Random, difficulty: str) -> GeneratedItem:
    who = pick(rng, PEOPLE)
    if difficulty == "easy":
        P, r, t = pick(rng, [5000, 6000, 8000, 12000, 15000, 18000, 24000]), pick(rng, [4, 5, 6, 8, 10, 12]), pick(rng, [2, 3, 4, 5])
        p = {"mode": "simple", "P": P, "r": r, "t": t}
        stem = f"{who} invests ₹{P} at {r}% simple interest per annum. What interest is earned in {t} years?"
        ans = _int_compute(p)
        distract = [(f"₹{fmt_num(P * Fraction(r, 100))}", "Interest for one year only"),
                    (f"₹{fmt_num(P + ans)}", "Gives the amount instead of interest"),
                    (f"₹{fmt_num(P * (1 + Fraction(r, 100)) ** t - P)}", "Uses compound interest")]
        expl = f"SI = P×R×T/100 = {P}×{r}×{t}/100 = ₹{fmt_num(ans)}."
    elif difficulty == "medium":
        P, r = pick(rng, [4000, 5000, 8000, 10000, 12000, 16000, 20000, 25000]), pick(rng, [4, 5, 10, 15, 20])
        p = {"mode": "compound", "P": P, "r": r, "t": 2}
        stem = f"{who} deposits ₹{P} at {r}% per annum compounded annually. What is the compound interest after 2 years?"
        ans = _int_compute(p)
        distract = [(f"₹{fmt_num(P * Fraction(r, 100) * 2)}", "Uses simple interest"),
                    (f"₹{fmt_num(P + ans)}", "Gives the amount instead of interest"),
                    (f"₹{fmt_num(ans + P * Fraction(r, 100) / 2)}", "Compounding slip")]
        expl = f"Amount = {P}(1+{r}/100)² = ₹{fmt_num(P + ans)}; CI = amount − principal = ₹{fmt_num(ans)}."
    else:
        P, r = pick(rng, [5000, 8000, 10000, 12000, 15000, 20000, 25000]), pick(rng, [4, 5, 6, 8, 10, 12])
        p = {"mode": "difference", "P": P, "r": r, "t": 2}
        stem = (f"On a principal of ₹{P}, what is the difference between compound interest (compounded annually) "
                f"and simple interest for 2 years at {r}% per annum?")
        ans = _int_compute(p)
        distract = [(f"₹{fmt_num(P * Fraction(r, 100))}", "Gives one year's simple interest"),
                    (f"₹{fmt_num(ans * 2)}", "Doubles the second-order term"),
                    (f"₹{fmt_num(ans / 2)}", "Halves the second-order term")]
        expl = f"For 2 years, CI − SI = P(R/100)² = {P}×({r}/100)² = ₹{fmt_num(ans)}."
    opts = build_options(rng, f"₹{fmt_num(ans)}", distract, lambda i: f"₹{fmt_num(ans + 50 * i)}")
    return GeneratedItem("QUANT", "QT-INT", "Simple and compound interest", "interest", difficulty, stem, opts, expl, p,
                         tags=["interest", "finance"])


def _int_verify(p: dict, item: GeneratedItem) -> list[Check]:
    return expect_correct(item, f"₹{fmt_num(_int_compute(p))}", "interest")


# ---------------------------------------------------------------- ratio partition
def _mix_tuples() -> list[tuple[int, int, int, int, int]]:
    from math import gcd
    out = []
    for a in range(2, 8):
        for b in range(1, 6):
            if gcd(a, b) != 1:
                continue
            for k in (2, 3, 4, 5, 6):
                for x in (4, 6, 8, 10, 12, 15, 20):
                    num, den = a * k, b * k + x
                    g = gcd(num, den)
                    c, d = num // g, den // g
                    if c <= 12 and d <= 12 and (c, d) != (a, b):
                        out.append((a, b, c, d, x))
    return out


_MIX_TUPLES = _mix_tuples()
def _ratio_compute(p: dict) -> Fraction:
    if p["mode"] == "share":
        return Fraction(p["total"] * p["ratio"][p["ask"]], sum(p["ratio"]))
    # mixture: a:b ratio, add x of B -> new ratio c:d ; find original quantity of A
    # a k : b k + x = c : d  =>  d a k = c (b k + x)  => k = c x / (d a - c b)
    a, b = p["ratio"]
    c, d = p["new_ratio"]
    k = Fraction(c * p["added"], d * a - c * b)
    return a * k


def _ratio_generate(rng: random.Random, difficulty: str) -> GeneratedItem:
    names = rng.sample(PEOPLE, 3)
    if difficulty in ("easy", "medium"):
        ratio = list(pick(rng, [(2, 3), (3, 5), (4, 7), (5, 3)] if difficulty == "easy" else [(2, 3, 5), (3, 4, 5), (1, 2, 4), (5, 6, 9)]))
        total = sum(ratio) * pick(rng, [120, 150, 200, 250, 400])
        ask = rng.randrange(len(ratio))
        p = {"mode": "share", "ratio": ratio, "total": total, "ask": ask, "names": names[: len(ratio)]}
        ans = _ratio_compute(p)
        who = " and ".join([", ".join(names[: len(ratio) - 1]), names[len(ratio) - 1]]) if len(ratio) > 2 else f"{names[0]} and {names[1]}"
        stem = f"₹{total} is divided among {who} in the ratio {':'.join(map(str, ratio))}. What is {names[ask]}'s share?"
        distract = [(f"₹{fmt_num(Fraction(total, len(ratio)))}", "Equal split ignoring ratio"),
                    (f"₹{fmt_num(Fraction(total * ratio[(ask + 1) % len(ratio)], sum(ratio)))}", "Picks another person's share"),
                    (f"₹{fmt_num(Fraction(total * ratio[ask], max(ratio)))}", "Divides by the largest term")]
        expl = f"{names[ask]}'s share = {total} × {ratio[ask]}/{sum(ratio)} = ₹{fmt_num(ans)}."
        correct = f"₹{fmt_num(ans)}"
        fb = lambda i: f"₹{fmt_num(ans + 25 * i)}"
    else:
        a, b, c, d, added = pick(rng, _MIX_TUPLES)
        liquid = pick(rng, ["milk", "juice concentrate", "syrup", "acid solution"])
        p = {"mode": "mixture", "ratio": [a, b], "new_ratio": [c, d], "added": added, "liquid": liquid}
        ans = _ratio_compute(p)
        stem = (f"A mixture contains {liquid} and water in the ratio {a}:{b}. When {added} litres of water are added, the "
                f"ratio becomes {c}:{d}. How many litres of {liquid} does the mixture contain?")
        correct = fmt_num(ans, "litres")
        k = ans / a
        distract = [(fmt_num(b * k, "litres"), "Gives the original water quantity"),
                    (fmt_num((a + b) * k, "litres"), "Gives the original total"),
                    (fmt_num(ans + added, "litres"), "Adds the water to the milk")]
        expl = f"Let milk = {a}k, water = {b}k. ({a}k)/({b}k+{added}) = {c}/{d} ⇒ k = {fmt_num(k)}; milk = {fmt_num(ans)} litres."
        fb = lambda i: fmt_num(ans + 5 * i, "litres")
    opts = build_options(rng, correct, distract, fb)
    return GeneratedItem("QUANT", "QT-RATIO", "Ratio and proportion", "ratios", difficulty, stem, opts, expl, p,
                         tags=["ratio", "proportion"])


def _ratio_verify(p: dict, item: GeneratedItem) -> list[Check]:
    v = _ratio_compute(p)
    checks = []
    if v <= 0:
        checks.append(Check("domain", "fail", "Computed quantity is non-positive", "critical"))
    exp = f"₹{fmt_num(v)}" if p["mode"] == "share" else fmt_num(v, "litres")
    return checks + expect_correct(item, exp, "share")


# ---------------------------------------------------------------- probability (verified by brute-force enumeration)
def _prob_compute(p: dict) -> Fraction:
    if p["mode"].startswith("coins"):
        outcomes = list(itertools.product((0, 1), repeat=p["n"]))
        if p["mode"] == "coins_exact":
            fav = sum(1 for o in outcomes if sum(o) == p["k"])
        else:
            fav = sum(1 for o in outcomes if sum(o) >= 1)
        return Fraction(fav, len(outcomes))
    outcomes = list(itertools.product(range(1, 7), repeat=p["dice"]))
    tests = {
        "sum_eq": lambda o: sum(o) == p["target"], "sum_ge": lambda o: sum(o) >= p["target"],
        "sum_mult": lambda o: sum(o) % p["m"] == 0, "doublet": lambda o: len(set(o)) == 1,
        "first_greater": lambda o: o[0] > o[1], "at_least_one_six": lambda o: 6 in o,
        "sum_prime": lambda o: sum(o) in (2, 3, 5, 7, 11, 13, 17), "product_even": lambda o: (o[0] * o[1]) % 2 == 0,
        "product_mult3": lambda o: (o[0] * o[1]) % 3 == 0, "diff_eq": lambda o: abs(o[0] - o[1]) == p.get("d", 0),
    }
    fav = sum(1 for o in outcomes if tests[p["mode"]](o))
    return Fraction(fav, len(outcomes))


def _frac(f: Fraction) -> str:
    return f"{f.numerator}/{f.denominator}" if f.denominator != 1 else str(f.numerator)


PROB_CONTEXTS = ["", "At a college fest game stall, ", "In a classroom probability demonstration, ",
                 "During a board-game night, ", "In a quick reasoning warm-up, "]


def _prob_generate(rng: random.Random, difficulty: str) -> GeneratedItem:
    ctx = pick(rng, PROB_CONTEXTS)
    if difficulty == "easy":
        p = pick(rng, [{"mode": "sum_eq", "dice": 2, "target": t} for t in range(3, 12)] +
                 [{"mode": "coins_exact", "n": n, "k": k} for n in (3, 4) for k in range(1, n)])
    elif difficulty == "medium":
        p = pick(rng, [{"mode": "sum_ge", "dice": 2, "target": t} for t in range(5, 12)] +
                 [{"mode": "sum_mult", "dice": 2, "m": m} for m in (3, 4, 5, 6)] +
                 [{"mode": "doublet", "dice": 2}, {"mode": "first_greater", "dice": 2}, {"mode": "sum_prime", "dice": 2},
                  {"mode": "product_even", "dice": 2}, {"mode": "product_mult3", "dice": 2}] +
                 [{"mode": "diff_eq", "dice": 2, "d": d} for d in range(1, 6)])
    else:
        p = pick(rng, [{"mode": "at_least_one_six", "dice": d} for d in (2, 3)] +
                 [{"mode": "coins_atleast1", "n": n} for n in (4, 5, 6)] +
                 [{"mode": "sum_eq", "dice": 3, "target": t} for t in range(4, 15)] +
                 [{"mode": "sum_ge", "dice": 3, "target": t} for t in (14, 15, 16)])
    p["ctx"] = ctx
    lead = ctx or ""
    m = p["mode"]
    if m == "coins_exact":
        stem = f"{lead}{p['n']} fair coins are tossed together. What is the probability of getting exactly {p['k']} head(s)?"
    elif m == "coins_atleast1":
        stem = f"{lead}{p['n']} fair coins are tossed. What is the probability of getting at least one head?"
    elif m == "sum_eq":
        stem = f"{lead}{'Two' if p['dice'] == 2 else 'Three'} fair six-sided dice are rolled. What is the probability that the sum is {p['target']}?"
    elif m == "sum_ge":
        stem = f"{lead}{'Two' if p['dice'] == 2 else 'Three'} fair dice are thrown together. What is the probability that the total is at least {p['target']}?"
    elif m == "sum_prime":
        stem = f"{lead}Two fair dice are thrown. What is the probability that the sum is a prime number?"
    elif m == "product_even":
        stem = f"{lead}Two fair dice are thrown. What is the probability that the product of the numbers is even?"
    elif m == "product_mult3":
        stem = f"{lead}Two fair dice are thrown. What is the probability that the product of the numbers is a multiple of 3?"
    elif m == "diff_eq":
        stem = f"{lead}Two fair dice are thrown. What is the probability that the numbers differ by exactly {p['d']}?"
    elif m == "sum_mult":
        stem = f"{lead}Two fair dice are thrown. What is the probability that the sum is a multiple of {p['m']}?"
    elif m == "doublet":
        stem = f"{lead}Two fair dice are thrown. What is the probability of getting a doublet (both dice show the same number)?"
    elif m == "first_greater":
        stem = f"{lead}Two fair dice, one red and one blue, are rolled. What is the probability that the red die shows a larger number than the blue die?"
    else:
        stem = f"{lead}{p['dice']} fair dice are rolled simultaneously. What is the probability of getting at least one six?"
    stem = stem[0].upper() + stem[1:]
    ans = _prob_compute(p)
    n_out = 2 ** p["n"] if m.startswith("coins") else 6 ** p["dice"]
    fav = int(ans * n_out)
    distract = [(_frac(Fraction(fav + 1, n_out)), "Miscounts favourable outcomes"),
                (_frac(Fraction(max(fav - 1, 1), n_out)), "Misses an ordered outcome"),
                (_frac(1 - ans) if ans != Fraction(1, 2) else _frac(Fraction(fav, n_out + 1)), "Complement confusion"),
                (_frac(Fraction(1, 11)), "Treats sums as equally likely")]
    expl = f"Enumerating all {n_out} equally likely outcomes, {fav} are favourable: probability {_frac(ans)}."
    opts = build_options(rng, _frac(ans), distract, lambda i: _frac(Fraction(i, n_out)))
    return GeneratedItem("QUANT", "QT-PROB", "Probability with dice and coins", "probability", difficulty, stem, opts, expl, p,
                         tags=["probability", "counting"])


def _prob_verify(p: dict, item: GeneratedItem) -> list[Check]:
    checks = expect_correct(item, _frac(_prob_compute(p)), "probability (exhaustive enumeration)")
    for o in item.options:
        try:
            num, _, den = o["text"].partition("/")
            val = Fraction(int(num), int(den or 1))
            if not 0 <= val <= 1:
                checks.append(Check("probability_range", "fail", f"Option {o['key']} outside [0,1]", "critical"))
        except ValueError:
            checks.append(Check("option_format", "warn", f"Option {o['key']} not a fraction", "warning"))
    return checks


QUANT_TEMPLATES = [
    Template("QT-PCT", "QUANT", "Percentage change", "percentages", _pct_generate, _pct_verify),
    Template("QT-SDT", "QUANT", "Speed, distance and time", "rates", _sdt_generate, _sdt_verify),
    Template("QT-WORK", "QUANT", "Work and time", "rates", _work_generate, _work_verify),
    Template("QT-INT", "QUANT", "Simple and compound interest", "interest", _int_generate, _int_verify),
    Template("QT-RATIO", "QUANT", "Ratio and proportion", "ratios", _ratio_generate, _ratio_verify),
    Template("QT-PROB", "QUANT", "Probability with dice and coins", "probability", _prob_generate, _prob_verify),
]
