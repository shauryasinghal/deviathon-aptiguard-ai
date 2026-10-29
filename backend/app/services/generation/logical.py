"""Logical-reasoning templates with exhaustive deterministic verification.

* Syllogisms are checked by enumerating all 128 set-region models of three terms.
* Ordering puzzles are checked by brute force over all permutations; ambiguous puzzles are rejected.
* Coding and direction items are verified by re-simulating the rule.
"""
from __future__ import annotations

import itertools
import math
import random

from app.services.generation.base import Check, GeneratedItem, Template, build_options, expect_correct, pick

PEOPLE = ["Asha", "Ravi", "Meera", "Kabir", "Nisha", "Arjun", "Farah", "Dev", "Ishaan", "Lena", "Tara", "Omar", "Priya", "Sam"]

# ---------------------------------------------------------------- number series
def _series_terms(p: dict, n: int) -> list[int]:
    t = [p["a"]]
    if p["rule"] == "arith":
        for _ in range(n - 1):
            t.append(t[-1] + p["d"])
    elif p["rule"] == "second_diff":
        d = p["d"]
        for _ in range(n - 1):
            t.append(t[-1] + d)
            d += p["dd"]
    elif p["rule"] == "mul_add":
        for _ in range(n - 1):
            t.append(t[-1] * p["k"] + p["c"])
    else:  # interleaved: two arithmetic series alternate
        a2 = p["a2"]
        seq = []
        x, y = p["a"], a2
        for i in range(n):
            seq.append(x if i % 2 == 0 else y)
            if i % 2 == 0:
                x += p["d"]
            else:
                y += p["d2"]
        return seq
    return t


def _series_generate(rng: random.Random, difficulty: str) -> GeneratedItem:
    if difficulty == "easy":
        p = {"rule": "arith", "a": rng.randint(3, 40), "d": pick(rng, [3, 4, 6, 7, 8, 9, 11, 12, -3, -4])}
    elif difficulty == "medium":
        p = pick(rng, [
            {"rule": "second_diff", "a": rng.randint(2, 20), "d": rng.randint(1, 5), "dd": pick(rng, [2, 3, 4])},
            {"rule": "interleave", "a": rng.randint(2, 15), "a2": rng.randint(30, 60), "d": pick(rng, [3, 4, 5]), "d2": pick(rng, [-2, -3, -5])},
        ])
    else:
        p = {"rule": "mul_add", "a": rng.randint(2, 6), "k": pick(rng, [2, 3]), "c": pick(rng, [1, -1, 2, 3, -2])}
    terms = _series_terms(p, 6)
    shown, ans = terms[:5], terms[5]
    diffs = [b - a for a, b in zip(shown, shown[1:])]
    distract = [(str(shown[-1] + diffs[-1]), "Repeats the last difference"),
                (str(ans + (diffs[-1] - diffs[-2] if len(diffs) > 1 else 2) or ans + 1), "Over-extends the pattern"),
                (str(ans - 1 if ans - 1 != shown[-1] + diffs[-1] else ans + 2), "Off-by-one")]
    stem = f"What number comes next in the series?  {', '.join(map(str, shown))}, ?"
    expl = {
        "arith": f"Each term adds {p.get('d')}.",
        "second_diff": f"Differences increase by {p.get('dd')} each step: {diffs}.",
        "interleave": "Two series alternate: odd positions and even positions each follow their own constant step.",
        "mul_add": f"Each term = previous × {p.get('k')} {'+' if p.get('c', 0) >= 0 else '−'} {abs(p.get('c', 0))}.",
    }[p["rule"]]
    opts = build_options(rng, str(ans), distract, lambda i: str(ans + 3 * i))
    return GeneratedItem("LOGICAL", "LG-SERIES", "Number series", "pattern-recognition", difficulty, stem, opts,
                         f"{expl} Next term = {ans}.", p, tags=["series", "patterns"])


def _series_verify(p: dict, item: GeneratedItem) -> list[Check]:
    terms = _series_terms(p, 6)
    checks = expect_correct(item, str(terms[5]), "next term")
    shown = ", ".join(map(str, terms[:5]))
    if shown not in item.stem:
        checks.append(Check("stem_matches_params", "fail", "Displayed terms do not match parameters", "critical"))
    return checks


# ---------------------------------------------------------------- syllogisms (model enumeration)
TERM_SETS = [
    ("pens", "books", "tables"), ("doctors", "engineers", "artists"), ("roses", "flowers", "plants"),
    ("cars", "buses", "trucks"), ("coins", "notes", "cards"), ("rivers", "lakes", "ponds"),
    ("poets", "singers", "dancers"), ("apples", "mangoes", "grapes"), ("laptops", "tablets", "phones"),
    ("teachers", "students", "parents"), ("chairs", "sofas", "beds"), ("kites", "birds", "planes"),
]
REGIONS = [r for r in itertools.product([0, 1], repeat=3) if any(r)]  # membership in (S, M, P)


def _holds(stmt: tuple, model: set) -> bool:
    q, x, y = stmt
    if q == "all":
        return not any(r[x] and not r[y] for r in model)
    if q == "no":
        return not any(r[x] and r[y] for r in model)
    if q == "some":
        return any(r[x] and r[y] for r in model)
    return any(r[x] and not r[y] for r in model)  # some_not


def _models(premises: list[tuple]):
    for mask in range(1, 1 << len(REGIONS)):
        model = {REGIONS[i] for i in range(len(REGIONS)) if mask >> i & 1}
        if all(any(r[t] for r in model) for t in range(3)) and all(_holds(s, model) for s in premises):
            yield model


def follows(premises: list[tuple], conclusion: tuple) -> bool:
    ms = list(_models(premises))
    return bool(ms) and all(_holds(conclusion, m) for m in ms)


def _say(stmt: tuple, terms: tuple) -> str:
    q, x, y = stmt
    a, b = terms[x], terms[y]
    return {"all": f"All {a} are {b}.", "no": f"No {a} are {b}.", "some": f"Some {a} are {b}.",
            "some_not": f"Some {a} are not {b}."}[q]


def _syll_generate(rng: random.Random, difficulty: str) -> GeneratedItem:
    pools = {"easy": [("all", "all")], "medium": [("all", "some"), ("some", "all"), ("all", "no")],
             "hard": [("some", "no"), ("no", "all"), ("all", "some_not"), ("some", "all")]}
    for _ in range(200):
        terms = pick(rng, TERM_SETS)
        q1, q2 = pick(rng, pools[difficulty])
        # S=0, M=1, P=2 ; premise 1 links S-M, premise 2 links M-P
        p1 = (q1, 0, 1) if rng.random() < 0.8 else (q1, 1, 0)
        p2 = (q2, 1, 2) if rng.random() < 0.7 else (q2, 2, 1)
        premises = [p1, p2]
        if not list(_models(premises)):
            continue
        cands = [(q, x, y) for q in ("all", "no", "some", "some_not") for x, y in [(0, 2), (2, 0)]]
        valid = [c for c in cands if follows(premises, c)]
        invalid = [c for c in cands if not follows(premises, c)]
        if not valid or len(invalid) < 3:
            continue
        if difficulty == "easy":
            valid = [c for c in valid if c[0] == "all"] or valid
        elif difficulty == "hard":
            valid = [c for c in valid if c[0] in ("some", "some_not", "no")] or valid
        correct = pick(rng, valid)
        wrong = rng.sample(invalid, 3)
        p = {"terms": list(terms), "premises": [list(s) for s in premises], "correct": list(correct),
             "wrong": [list(w) for w in wrong]}
        stem = (f"Statements: {_say(p1, terms)} {_say(p2, terms)}\n"
                f"Which of the following conclusions definitely follows from the statements?")
        opts = build_options(rng, _say(correct, terms), [(_say(w, terms), "Possible but not certain") for w in wrong])
        expl = (f"In every arrangement consistent with both statements, '{_say(correct, terms)}' holds. "
                f"Each other option fails in at least one consistent arrangement.")
        return GeneratedItem("LOGICAL", "LG-SYLL", "Syllogisms", "deductive-reasoning", difficulty, stem, opts, expl, p,
                             tags=["syllogism", "deduction"])
    raise RuntimeError("could not construct a valid syllogism")


def _syll_verify(p: dict, item: GeneratedItem) -> list[Check]:
    terms = tuple(p["terms"])
    premises = [tuple(s) for s in p["premises"]]
    n_models = len(list(_models(premises)))
    checks = [Check("premises_consistent", "pass" if n_models else "fail",
                    f"{n_models} set-region models satisfy the premises", "info" if n_models else "critical")]
    following = []
    for o in item.options:
        for q in ("all", "no", "some", "some_not"):
            for x, y in [(0, 2), (2, 0), (0, 1), (1, 0), (1, 2), (2, 1)]:
                if _say((q, x, y), terms).lower() == o["text"].lower():
                    if follows(premises, (q, x, y)):
                        following.append(o["key"])
    key = item.correct_key
    if following == [key]:
        checks.append(Check("answer_recomputed", "pass", f"Exhaustive model check: only option {key} follows"))
    else:
        checks.append(Check("answer_recomputed", "fail", f"Options that follow: {following or 'none'}; key is {key}",
                            "critical", {"following": following}))
    return checks


# ---------------------------------------------------------------- ordering puzzles (brute force uniqueness)
ATTRS = [("is taller than", "the tallest", "the shortest", "tall"), ("is older than", "the oldest", "the youngest", "old"),
         ("scored more than", "the highest scorer", "the lowest scorer", "score")]


def _consistent(perm: tuple, clues: list[tuple]) -> bool:
    rank = {name: i for i, name in enumerate(perm)}  # index 0 = greatest
    return all(rank[a] < rank[b] for a, b in clues)


def _solutions(names: list[str], clues: list[tuple]) -> list[tuple]:
    return [perm for perm in itertools.permutations(names) if _consistent(perm, clues)]


def _ordinal(k: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(k, f"{k}th")


def _order_generate(rng: random.Random, difficulty: str) -> GeneratedItem:
    n = {"easy": 4, "medium": 5, "hard": 6}[difficulty]
    names = rng.sample(PEOPLE, n)
    truth = names[:]
    rng.shuffle(truth)
    rel, top, bottom, _ = pick(rng, ATTRS)
    ask = {"easy": 1, "medium": 3, "hard": pick(rng, [3, 4])}[difficulty]
    pairs = [(truth[i], truth[j]) for i in range(n) for j in range(i + 1, n)]
    rng.shuffle(pairs)
    # prefer non-adjacent comparisons on harder items so more inference is required
    pairs.sort(key=lambda pr: (abs(truth.index(pr[0]) - truth.index(pr[1])) == 1) if difficulty == "hard" else 0)
    clues: list[tuple] = []
    for pr in pairs:
        sols = _solutions(names, clues)
        if len({s[ask - 1] for s in sols}) == 1 and len(clues) >= n - 1:
            break
        clues.append(pr)
    # prune redundant clues: keep a minimal set that still fixes the asked position uniquely
    order = list(range(len(clues)))
    rng.shuffle(order)
    for idx in order:
        trial = [c for k, c in enumerate(clues) if k != idx and c is not None]
        if len({s[ask - 1] for s in _solutions(names, trial)}) == 1:
            clues[idx] = None
    clues = [c for c in clues if c is not None]
    sols = _solutions(names, clues)
    answer = sols[0][ask - 1]
    p = {"names": names, "clues": [list(c) for c in clues], "ask": ask, "relation": rel}
    clue_txt = " ".join(f"{a} {rel} {b}." for a, b in clues)
    question = f"Who is {top}?" if ask == 1 else \
        f"If they are ranked from greatest to least, who is in the {_ordinal(ask)} position?"
    stem = f"Among {', '.join(names[:-1])} and {names[-1]}: {clue_txt} {question}"
    others = [x for x in names if x != answer]
    rng.shuffle(others)
    opts = build_options(rng, answer, [(o, "Inconsistent with at least one clue") for o in others])
    expl = f"The clues force a unique ranking: {' > '.join(sols[0])}. Position {ask} is {answer}."
    if len(sols) > 1:
        expl = f"The clues fix position {ask} as {answer} in all {len(sols)} consistent rankings."
    return GeneratedItem("LOGICAL", "LG-ORDER", "Ordering and ranking", "analytical-reasoning", difficulty, stem, opts,
                         expl, p, tags=["arrangement", "ranking"])


def _order_verify(p: dict, item: GeneratedItem) -> list[Check]:
    sols = _solutions(p["names"], [tuple(c) for c in p["clues"]])
    if not sols:
        return [Check("constraints_consistent", "fail", "Clues are contradictory: no valid ranking", "critical")]
    answers = {s[p["ask"] - 1] for s in sols}
    checks = [Check("constraints_consistent", "pass", f"{len(sols)} ranking(s) satisfy all clues")]
    if len(answers) > 1:
        checks.append(Check("unique_answer", "fail", f"Ambiguous: positions admit {sorted(answers)}", "critical"))
        return checks
    checks.append(Check("unique_answer", "pass", "Exactly one person can occupy the asked position"))
    return checks + expect_correct(item, answers.pop(), "position (brute force)")


# ---------------------------------------------------------------- coding-decoding
WORDS = ["CLOUD", "RIVER", "PLANT", "STONE", "LIGHT", "BRAIN", "TRAIN", "FRAME", "GLASS", "MONEY", "WATER", "HOUSE",
         "SMART", "QUICK", "BLEND", "CHAIR", "PRISM", "TIGER", "NOBLE", "VAPOR"]


def _shift(c: str, k: int) -> str:
    return chr((ord(c) - 65 + k) % 26 + 65)


def _encode(word: str, p: dict) -> str:
    if p["rule"] == "shift":
        return "".join(_shift(c, p["k"]) for c in word)
    if p["rule"] == "reverse_shift":
        return "".join(_shift(c, p["k"]) for c in word[::-1])
    return "".join(_shift(c, p["k"] if i % 2 == 0 else -p["k"]) for i, c in enumerate(word))


def _code_generate(rng: random.Random, difficulty: str) -> GeneratedItem:
    rule = {"easy": "shift", "medium": "reverse_shift", "hard": "alternate"}[difficulty]
    k = pick(rng, [1, 2, 3]) if difficulty != "easy" else pick(rng, [1, 2])
    example, target = rng.sample(WORDS, 2)
    p = {"rule": rule, "k": k, "example": example, "target": target}
    ans = _encode(target, p)
    stem = f"In a certain code language, {example} is written as {_encode(example, p)}. How is {target} written in that code?"
    wrong = [
        ("".join(_shift(c, k) for c in target), "Ignores the reversal/alternation"),
        ("".join(_shift(c, -k) for c in target), "Shifts in the wrong direction"),
        ("".join(_shift(c, k + 1) for c in target[::-1]), "Wrong shift size"),
        (_encode(target, {**p, "k": k + 1}), "Wrong shift size"),
    ]
    expl = {"shift": f"Each letter moves {k} place(s) forward.",
            "reverse_shift": f"Reverse the word, then move each letter {k} place(s) forward.",
            "alternate": f"Letters in odd positions move +{k}, letters in even positions move −{k}."}[rule]
    opts = build_options(rng, ans, wrong)
    return GeneratedItem("LOGICAL", "LG-CODE", "Coding–decoding", "symbolic-reasoning", difficulty, stem, opts,
                         f"{expl} {target} → {ans}.", p, tags=["coding", "ciphers"])


def _code_verify(p: dict, item: GeneratedItem) -> list[Check]:
    checks = []
    if f"is written as {_encode(p['example'], p)}" not in item.stem:
        checks.append(Check("example_consistent", "fail", "Worked example does not follow the stated rule", "critical"))
    return checks + expect_correct(item, _encode(p["target"], p), "code")


# ---------------------------------------------------------------- direction sense
DIRS = {"North": (0, 1), "East": (1, 0), "South": (0, -1), "West": (-1, 0)}
ORDER = ["North", "East", "South", "West"]


def _walk(p: dict) -> tuple[int, int]:
    x = y = 0
    facing = p["start"]
    for turn, dist in p["moves"]:
        if turn == "left":
            facing = ORDER[(ORDER.index(facing) - 1) % 4]
        elif turn == "right":
            facing = ORDER[(ORDER.index(facing) + 1) % 4]
        dx, dy = DIRS[facing]
        x, y = x + dx * dist, y + dy * dist
    return x, y


def _dir_label(x: int, y: int) -> str:
    ns = "North" if y > 0 else "South" if y < 0 else ""
    ew = "East" if x > 0 else "West" if x < 0 else ""
    return f"{ns}-{ew}" if ns and ew else ns or ew or "Start"


def _dir_answer(p: dict) -> str:
    x, y = _walk(p)
    dist = math.hypot(x, y)
    if p["ask"] == "distance":
        return f"{int(dist) if dist.is_integer() else round(dist, 2)} m"
    return f"{int(dist) if dist.is_integer() else round(dist, 2)} m {_dir_label(x, y)}"


def _dir_generate(rng: random.Random, difficulty: str) -> GeneratedItem:
    who = pick(rng, PEOPLE)
    triples = [(3, 4), (6, 8), (5, 12), (9, 12), (8, 15)]
    for _ in range(200):
        start = pick(rng, ORDER)
        if difficulty == "easy":
            a, b = pick(rng, triples)
            moves = [["straight", a], [pick(rng, ["left", "right"]), b]]
            ask = "distance"
        elif difficulty == "medium":
            a, b = pick(rng, triples)
            moves = [["straight", a + 5], [pick(rng, ["left", "right"]), b], [pick(rng, ["left", "right"]), 5]]
            ask = "position"
        else:
            a, b = pick(rng, triples)
            t1, t2 = pick(rng, ["left", "right"]), pick(rng, ["left", "right"])
            moves = [["straight", a + 4], [t1, b + 3], [t2, 4], [pick(rng, ["left", "right"]), 3]]
            ask = "position"
        p = {"start": start, "moves": moves, "ask": ask}
        x, y = _walk(p)
        if math.hypot(x, y).is_integer() and (x, y) != (0, 0):
            break
    ans = _dir_answer(p)
    narr = [f"walks {moves[0][1]} m towards the {start}"]
    for turn, d in moves[1:]:
        narr.append(f"turns {turn} and walks {d} m")
    q = "How far is " + who + " from the starting point?" if ask == "distance" else \
        f"How far and in which direction is {who} from the starting point?"
    stem = f"{who} {', then '.join(narr)}. {q}"
    x, y = _walk(p)
    dist = int(math.hypot(x, y))
    if ask == "distance":
        wrong = [(f"{abs(x) + abs(y)} m", "Adds the legs instead of using Pythagoras"),
                 (f"{abs(abs(x) - abs(y))} m", "Subtracts the legs"), (f"{dist + 2} m", "Arithmetic slip")]
    else:
        wrong = [(f"{dist} m {_dir_label(-x, y)}", "Mirror error on East/West"),
                 (f"{dist} m {_dir_label(x, -y)}", "Mirror error on North/South"),
                 (f"{abs(x) + abs(y)} m {_dir_label(x, y)}", "Adds the legs")]
    opts = build_options(rng, ans, wrong, lambda i: f"{dist + i} m")
    expl = f"Net displacement is ({x}, {y}) metres from the start (East, North positive): {ans}."
    return GeneratedItem("LOGICAL", "LG-DIR", "Direction sense", "spatial-reasoning", difficulty, stem, opts, expl, p,
                         tags=["directions", "spatial"])


def _dir_verify(p: dict, item: GeneratedItem) -> list[Check]:
    return expect_correct(item, _dir_answer(p), "displacement (simulated walk)")


LOGICAL_TEMPLATES = [
    Template("LG-SERIES", "LOGICAL", "Number series", "pattern-recognition", _series_generate, _series_verify),
    Template("LG-SYLL", "LOGICAL", "Syllogisms", "deductive-reasoning", _syll_generate, _syll_verify),
    Template("LG-ORDER", "LOGICAL", "Ordering and ranking", "analytical-reasoning", _order_generate, _order_verify),
    Template("LG-CODE", "LOGICAL", "Coding–decoding", "symbolic-reasoning", _code_generate, _code_verify),
    Template("LG-DIR", "LOGICAL", "Direction sense", "spatial-reasoning", _dir_generate, _dir_verify),
]
