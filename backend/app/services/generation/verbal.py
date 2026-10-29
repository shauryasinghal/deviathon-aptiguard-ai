"""Verbal-reasoning templates.

Answers are checked against curated lexical/grammar tables, which proves *internal consistency* only.
Linguistic acceptability is inherently a human judgment, so every verbal item carries a mandatory
review requirement and is never treated as machine-proven.
"""
from __future__ import annotations

import random

from app.services.generation.base import Check, GeneratedItem, Template, build_options, expect_correct, pick

LEXICAL_REVIEW = ("Lexical judgment: reviewer must confirm no distractor is an acceptable answer in standard usage "
                  "and the keyed answer is unambiguous.")

# word -> (synonyms, antonyms); tiered by frequency to control difficulty
LEXICON = {
    "easy": {
        "rapid": (["swift", "quick"], ["slow", "sluggish"]), "begin": (["start", "commence"], ["end", "finish"]),
        "honest": (["truthful", "sincere"], ["deceitful", "dishonest"]), "brave": (["courageous", "bold"], ["timid", "cowardly"]),
        "ancient": (["old", "antique"], ["modern", "new"]), "huge": (["enormous", "vast"], ["tiny", "minute"]),
        "happy": (["cheerful", "joyful"], ["sad", "gloomy"]), "rich": (["wealthy", "affluent"], ["poor", "needy"]),
        "polite": (["courteous", "respectful"], ["rude", "impolite"]), "clean": (["spotless", "tidy"], ["dirty", "filthy"]),
        "calm": (["peaceful", "tranquil"], ["agitated", "turbulent"]), "strong": (["sturdy", "powerful"], ["weak", "feeble"]),
    },
    "medium": {
        "abundant": (["plentiful", "ample"], ["scarce", "sparse"]), "candid": (["frank", "forthright"], ["evasive", "guarded"]),
        "diligent": (["industrious", "assiduous"], ["lazy", "negligent"]), "frugal": (["thrifty", "economical"], ["lavish", "wasteful"]),
        "obscure": (["unclear", "vague"], ["evident", "obvious"]), "resilient": (["hardy", "tough"], ["fragile", "brittle"]),
        "hostile": (["antagonistic", "unfriendly"], ["amicable", "friendly"]), "concise": (["succinct", "brief"], ["verbose", "wordy"]),
        "meticulous": (["thorough", "careful"], ["careless", "sloppy"]), "reluctant": (["unwilling", "hesitant"], ["eager", "keen"]),
        "lucid": (["clear", "articulate"], ["confusing", "muddled"]), "prudent": (["sensible", "judicious"], ["reckless", "rash"]),
    },
    "hard": {
        "ephemeral": (["transient", "fleeting"], ["enduring", "permanent"]), "obdurate": (["intransigent", "stubborn"], ["pliant", "amenable"]),
        "laconic": (["terse", "pithy"], ["garrulous", "loquacious"]), "pernicious": (["deleterious", "harmful"], ["benign", "salutary"]),
        "sanguine": (["optimistic", "hopeful"], ["pessimistic", "despondent"]), "prosaic": (["mundane", "humdrum"], ["imaginative", "extraordinary"]),
        "venerate": (["revere", "esteem"], ["despise", "scorn"]), "recondite": (["abstruse", "arcane"], ["accessible", "straightforward"]),
        "magnanimous": (["generous", "charitable"], ["petty", "mean-spirited"]), "insipid": (["bland", "vapid"], ["flavourful", "piquant"]),
        "truculent": (["belligerent", "pugnacious"], ["docile", "conciliatory"]), "ebullient": (["exuberant", "buoyant"], ["subdued", "lethargic"]),
    },
}


def _all_related(word: str) -> set[str]:
    for tier in LEXICON.values():
        if word in tier:
            syn, ant = tier[word]
            return set(syn) | set(ant) | {word}
    return {word}


def _lex_generate(kind: str):
    def gen(rng: random.Random, difficulty: str) -> GeneratedItem:
        tier = LEXICON[difficulty]
        head = pick(rng, sorted(tier))
        syn, ant = tier[head]
        correct = pick(rng, syn if kind == "syn" else ant)
        # distractors: synonyms/antonyms of *other* headwords in the tier, never related to the headword
        pool = []
        for other in sorted(tier):
            if other == head:
                continue
            pool.extend(tier[other][0] + tier[other][1])
        pool = [w for w in pool if w not in _all_related(head)]
        rng.shuffle(pool)
        trap = (pick(rng, ant), "Antonym trap") if kind == "syn" else (pick(rng, syn), "Synonym trap")
        distract = [trap] + [(w, "Unrelated meaning") for w in pool[:4]]
        label = "most nearly the SAME" if kind == "syn" else "most nearly OPPOSITE"
        stem = f"Choose the word {label} in meaning to: {head.upper()}"
        p = {"kind": kind, "head": head, "difficulty_tier": difficulty, "answer": correct}
        opts = build_options(rng, correct, distract)
        rel = "synonym" if kind == "syn" else "antonym"
        return GeneratedItem("VERBAL", "VB-SYN" if kind == "syn" else "VB-ANT", "Synonyms" if kind == "syn" else "Antonyms",
                             "vocabulary", difficulty, stem, opts, f"'{correct}' is a {rel} of '{head}'.", p,
                             tags=["vocabulary", rel], review_requirement=LEXICAL_REVIEW)
    return gen


def _lex_verify(p: dict, item: GeneratedItem) -> list[Check]:
    tier = LEXICON[p["difficulty_tier"]]
    syn, ant = tier[p["head"]]
    valid = set(syn if p["kind"] == "syn" else ant)
    checks = []
    keyed = item.correct_text
    if keyed in valid:
        checks.append(Check("answer_in_lexicon", "pass", f"'{keyed}' is listed as a {'synonym' if p['kind']=='syn' else 'antonym'} of '{p['head']}'"))
    else:
        checks.append(Check("answer_in_lexicon", "fail", f"'{keyed}' is not in the lexicon entry", "critical"))
    leaks = [o["text"] for o in item.options if not o["is_correct"] and o["text"] in valid]
    if leaks:
        checks.append(Check("distractor_not_acceptable", "fail", f"Distractor(s) also acceptable: {leaks}", "critical"))
    checks.append(Check("linguistic_review", "warn", "Verbal item: correctness requires human linguistic confirmation", "warning"))
    return checks


# ---------------------------------------------------------------- analogies
RELATIONS = {
    "worker_place": [("doctor", "hospital"), ("teacher", "school"), ("chef", "kitchen"), ("pilot", "cockpit"),
                     ("judge", "courtroom"), ("librarian", "library"), ("farmer", "field"), ("actor", "stage")],
    "young_adult": [("puppy", "dog"), ("kitten", "cat"), ("calf", "cow"), ("cub", "lion"), ("foal", "horse"),
                    ("tadpole", "frog"), ("duckling", "duck"), ("joey", "kangaroo")],
    "tool_worker": [("scalpel", "surgeon"), ("brush", "painter"), ("chisel", "sculptor"), ("baton", "conductor"),
                    ("stethoscope", "doctor"), ("loom", "weaver"), ("trowel", "mason"), ("needle", "tailor")],
    "part_whole": [("page", "book"), ("petal", "flower"), ("wheel", "car"), ("key", "keyboard"),
                   ("branch", "tree"), ("chapter", "novel"), ("brick", "wall"), ("string", "guitar")],
    "degree": [("warm", "hot"), ("cool", "freezing"), ("drizzle", "downpour"), ("breeze", "gale"),
               ("glad", "ecstatic"), ("tired", "exhausted"), ("hungry", "starving"), ("dislike", "loathe")],
}
REL_TEXT = {"worker_place": "works in", "young_adult": "is the young one of", "tool_worker": "is the tool used by",
            "part_whole": "is a part of", "degree": "is a milder degree of"}
REL_DIFFICULTY = {"easy": ["worker_place", "young_adult"], "medium": ["tool_worker", "part_whole"], "hard": ["degree", "tool_worker"]}


def _analogy_generate(rng: random.Random, difficulty: str) -> GeneratedItem:
    rel = pick(rng, REL_DIFFICULTY[difficulty])
    (a, b), (c, d) = rng.sample(RELATIONS[rel], 2)
    other_words = [w for r, pairs in RELATIONS.items() if r != rel for pair in pairs for w in pair]
    near = [x for pr in RELATIONS[rel] if pr not in ((a, b), (c, d)) for x in pr[:1]]  # same-side words: wrong role
    rng.shuffle(other_words)
    distract = [(pick(rng, near), "Same category but wrong role in the relation")] + [(w, "Different relation") for w in other_words[:4]]
    stem = f"{a.capitalize()} : {b.capitalize()} :: {c.capitalize()} : ?"
    p = {"relation": rel, "pair": [a, b], "probe": c, "answer": d}
    opts = build_options(rng, d.capitalize(), [(x.capitalize(), w) for x, w in distract])
    return GeneratedItem("VERBAL", "VB-ANALOGY", "Word analogies", "relational-reasoning", difficulty, stem, opts,
                         f"A {a} {REL_TEXT[rel]} a {b}; likewise a {c} {REL_TEXT[rel]} a {d}.", p,
                         tags=["analogy"], review_requirement=LEXICAL_REVIEW)


def _analogy_verify(p: dict, item: GeneratedItem) -> list[Check]:
    pairs = RELATIONS[p["relation"]]
    checks = expect_correct(item, p["answer"].capitalize(), "analogy completion")
    if (p["probe"], p["answer"]) not in pairs:
        checks.append(Check("relation_table", "fail", "Answer pair not in relation table", "critical"))
    for o in item.options:
        if not o["is_correct"] and (p["probe"], o["text"].lower()) in pairs:
            checks.append(Check("distractor_not_acceptable", "fail", f"Distractor {o['key']} also completes the relation", "critical"))
    checks.append(Check("linguistic_review", "warn", "Verbal item: relation plausibility requires human confirmation", "warning"))
    return checks


# ---------------------------------------------------------------- subject–verb agreement
SVA_FRAMES = {
    "easy": [("The list of items", "sg", "on the desk"), ("The players", "pl", "on the field"), ("My brother", "sg", "at home"),
             ("These documents", "pl", "ready for review"), ("The box of chocolates", "sg", "in the cupboard"),
             ("The children in the park", "pl", "very noisy"), ("The new manager", "sg", "in a meeting"),
             ("The keys to the cabinet", "pl", "missing")],
    "medium": [("Each of the students", "sg", "ready for the exam"), ("Neither the manager nor the employees", "pl", "aware of the change"),
               ("Everyone in the two teams", "sg", "invited to the dinner"), ("The committee", "sg", "unanimous in its decision"),
               ("Either the coach or the players", "pl", "responsible for the kit"),
               ("The team of engineers", "sg", "confident about the design"), ("Both the director and the producer", "pl", "present at the launch"),
               ("One of the reports", "sg", "incomplete")],
    "hard": [("Neither of the proposals", "sg", "acceptable to the board"), ("The number of applicants", "sg", "higher than expected"),
             ("A number of applicants", "pl", "waiting outside"), ("Not only the teacher but also the students", "pl", "excited about the trip"),
             ("The quality of the apples", "sg", "excellent this season"), ("Mathematics", "sg", "her favourite subject"),
             ("The news about the mergers", "sg", "surprising to investors"), ("The majority of the votes", "pl", "already counted"),
             ("Each of the candidates, along with their mentors,", "sg", "required to attend")],
}
VERBS = {"present": ("is", "are"), "past": ("was", "were"), "perfect": ("has been", "have been")}


def _sva_generate(rng: random.Random, difficulty: str) -> GeneratedItem:
    subject, num, tail = pick(rng, SVA_FRAMES[difficulty])
    tense = pick(rng, sorted(VERBS))
    sg, pl = VERBS[tense]
    answer = sg if num == "sg" else pl
    other_t = [t for t in VERBS if t != tense]
    distract = [(pl if num == "sg" else sg, "Agreement error"),
                (VERBS[other_t[0]][1 if num == "sg" else 0], "Wrong tense and number"),
                ("be", "Non-finite form"), ("being", "Non-finite form")]
    stem = f"Choose the option that correctly completes the sentence: \"{subject} ___ {tail}.\""
    p = {"subject": subject, "number": num, "tense": tense, "answer": answer}
    opts = build_options(rng, answer, distract)
    rule = "singular" if num == "sg" else "plural"
    return GeneratedItem("VERBAL", "VB-SVA", "Subject–verb agreement", "grammar", difficulty, stem, opts,
                         f"The grammatical subject '{subject}' is {rule} here, so the verb is '{answer}'.", p,
                         tags=["grammar", "agreement"],
                         review_requirement="Grammar rule item: reviewer confirms the sentence has one defensible completion.")


def _sva_verify(p: dict, item: GeneratedItem) -> list[Check]:
    sg, pl = VERBS[p["tense"]]
    checks = expect_correct(item, sg if p["number"] == "sg" else pl, "verb form (agreement table)")
    checks.append(Check("linguistic_review", "warn", "Agreement rules for collective/correlative subjects vary by style guide", "warning"))
    return checks


# ---------------------------------------------------------------- reading inference
FRAMES = [
    {"org": "a regional bus operator", "metric": "ridership", "up": "weekday", "down": "weekend", "cause": "the new office shuttle routes",
     "valid": "Changes in commuter demand contributed to the rise in weekday ridership.",
     "extreme": "The operator will soon cancel all weekend services.",
     "contra": "Weekend ridership increased along with weekday ridership.",
     "scope": "Bus fares in the region are lower than in neighbouring regions."},
    {"org": "a public library", "metric": "visits", "up": "evening", "down": "morning", "cause": "the extended evening opening hours",
     "valid": "Longer opening hours are associated with more evening visits.",
     "extreme": "Morning visitors no longer value the library.",
     "contra": "Morning visits rose after the change.",
     "scope": "The library has the largest collection in the state."},
    {"org": "an online grocery store", "metric": "orders", "up": "subscription", "down": "one-time", "cause": "a discounted monthly plan",
     "valid": "Some customers moved from one-time purchases to the discounted plan.",
     "extreme": "One-time orders will disappear entirely within a year.",
     "contra": "One-time orders increased after the plan was launched.",
     "scope": "The store's delivery drivers are paid above the market rate."},
    {"org": "a hospital outpatient department", "metric": "waiting times", "up": "afternoon", "down": "morning", "cause": "a new online booking system",
     "valid": "The booking system changed when patients chose to arrive.",
     "extreme": "The booking system has made the hospital the best in the country.",
     "contra": "Morning waiting times got longer after the system was introduced.",
     "scope": "Most of the hospital's doctors trained abroad."},
    {"org": "a city cycling scheme", "metric": "rentals", "up": "short-trip", "down": "long-trip", "cause": "the new per-minute pricing",
     "valid": "Pricing changes influenced the length of trips riders chose.",
     "extreme": "Nobody in the city will take long cycling trips again.",
     "contra": "Long-trip rentals grew faster than short-trip rentals.",
     "scope": "The city has more cars per person than any other city."},
    {"org": "a university canteen", "metric": "sales", "up": "salad", "down": "fried-snack", "cause": "a new nutrition-labelling display",
     "valid": "Displaying nutrition information may have shifted some purchases towards salads.",
     "extreme": "Students will stop eating fried snacks altogether.",
     "contra": "Fried-snack sales rose sharply after the display was installed.",
     "scope": "The canteen is run by a national catering company."},
    {"org": "a regional airline", "metric": "bookings", "up": "early-morning", "down": "late-evening", "cause": "discounted fares on morning flights",
     "valid": "Fare discounts were followed by more travellers choosing morning flights.",
     "extreme": "Evening flights are no longer profitable for any airline.",
     "contra": "Late-evening bookings increased more than early-morning bookings.",
     "scope": "The airline's pilots have the most flying hours in the industry."},
    {"org": "a municipal water utility", "metric": "complaints", "up": "online", "down": "phone", "cause": "a new mobile reporting app",
     "valid": "The new app gave residents another way to report problems, changing how complaints were filed.",
     "extreme": "Telephone helplines will be abolished across the country.",
     "contra": "Phone complaints rose after the app was launched.",
     "scope": "The city's water is the cleanest in the region."},
    {"org": "a district hospital pharmacy", "metric": "prescriptions filled", "up": "generic-medicine", "down": "branded-medicine", "cause": "a new generic-substitution guideline",
     "valid": "The guideline coincided with a shift from branded towards generic medicines.",
     "extreme": "Doctors in the district have stopped prescribing branded medicines.",
     "contra": "Branded-medicine prescriptions rose after the guideline was issued.",
     "scope": "The pharmacy is open twenty-four hours a day."},
    {"org": "a state electricity board", "metric": "bill payments", "up": "online", "down": "counter", "cause": "a cashback offer for digital payments",
     "valid": "The cashback offer was followed by more consumers paying online.",
     "extreme": "Payment counters will close permanently across the state.",
     "contra": "Counter payments grew faster than online payments.",
     "scope": "The state produces most of its electricity from coal."},
    {"org": "a museum", "metric": "ticket sales", "up": "weekday-evening", "down": "weekend-morning", "cause": "late opening on Thursdays",
     "valid": "Opening late on Thursdays attracted additional evening visitors.",
     "extreme": "Families no longer visit museums at weekends.",
     "contra": "Weekend-morning ticket sales increased after the change.",
     "scope": "The museum's collection is the oldest in the country."},
    {"org": "a coaching institute", "metric": "enrolments", "up": "online-batch", "down": "classroom-batch", "cause": "recorded lecture access for online students",
     "valid": "Access to recorded lectures made the online batch more attractive to some students.",
     "extreme": "Classroom teaching is no longer effective for any student.",
     "contra": "Classroom-batch enrolments increased while online enrolments fell.",
     "scope": "The institute's founder previously worked as an engineer."},
    {"org": "a food-delivery platform", "metric": "orders", "up": "late-night", "down": "lunchtime", "cause": "free delivery after 10 p.m.",
     "valid": "Free late-night delivery coincided with more late-night ordering.",
     "extreme": "Restaurants will stop serving lunch in the city.",
     "contra": "Lunchtime orders rose sharply after the offer began.",
     "scope": "The platform's head office is in another state."},
    {"org": "a public swimming pool", "metric": "attendance", "up": "early-morning", "down": "afternoon", "cause": "a discounted early-bird membership",
     "valid": "The early-bird discount was followed by more swimmers coming early in the morning.",
     "extreme": "Nobody swims in the afternoon any more.",
     "contra": "Afternoon attendance rose more than early-morning attendance.",
     "scope": "The pool was built for an international competition."},
    {"org": "a regional newspaper", "metric": "subscriptions", "up": "digital", "down": "print", "cause": "a bundled e-paper and podcast package",
     "valid": "The bundled digital package coincided with growth in digital subscriptions.",
     "extreme": "Printed newspapers will vanish from the region within a year.",
     "contra": "Print subscriptions grew after the package was introduced.",
     "scope": "The newspaper has won several journalism awards."},
    {"org": "a car-sharing service", "metric": "bookings", "up": "hourly", "down": "full-day", "cause": "a reduced hourly tariff",
     "valid": "The cheaper hourly tariff was associated with more hourly bookings.",
     "extreme": "No customer will ever book a car for a whole day again.",
     "contra": "Full-day bookings increased more than hourly bookings.",
     "scope": "The service uses only electric vehicles."},
]


def _infer_generate(rng: random.Random, difficulty: str) -> GeneratedItem:
    f = pick(rng, FRAMES)
    pct = pick(rng, [9, 12, 14, 18, 22, 27, 31, 36])
    hedge = {"easy": "", "medium": " Management has not yet studied whether other factors were involved.",
             "hard": " A local festival during the same quarter may also have affected the figures, and management cautions against firm conclusions."}[difficulty]
    passage = (f"Last quarter, {f['org']} recorded a {pct}% increase in {f['up']} {f['metric']} while {f['down']} "
               f"{f['metric']} declined slightly. The change followed the introduction of {f['cause']}.{hedge}")
    stem = f"{passage}\n\nWhich of the following can most reasonably be inferred from the passage?"
    p = {"frame": FRAMES.index(f), "pct": pct, "answer": f["valid"]}
    opts = build_options(rng, f["valid"], [(f["extreme"], "Overgeneralisation"), (f["contra"], "Contradicts the passage"),
                                           (f["scope"], "Out of scope")])
    return GeneratedItem("VERBAL", "VB-INFER", "Reading inference", "reading-comprehension", difficulty, stem, opts,
                         "Only the keyed option is supported without going beyond the passage; the others contradict it, "
                         "overgeneralise, or introduce unsupported information.", p, tags=["inference", "comprehension"],
                         review_requirement="Inference item: reviewer must confirm the keyed option is the *most* defensible "
                                            "and that no distractor is arguably supported.")


def _infer_verify(p: dict, item: GeneratedItem) -> list[Check]:
    f = FRAMES[p["frame"]]
    checks = expect_correct(item, f["valid"], "supported inference")
    if f"{p['pct']}%" not in item.stem:
        checks.append(Check("passage_matches_params", "fail", "Passage figures do not match parameters", "critical"))
    checks.append(Check("linguistic_review", "warn", "Inference items cannot be machine-proven; human review mandatory", "warning"))
    return checks


VERBAL_TEMPLATES = [
    Template("VB-SYN", "VERBAL", "Synonyms", "vocabulary", _lex_generate("syn"), _lex_verify),
    Template("VB-ANT", "VERBAL", "Antonyms", "vocabulary", _lex_generate("ant"), _lex_verify),
    Template("VB-ANALOGY", "VERBAL", "Word analogies", "relational-reasoning", _analogy_generate, _analogy_verify),
    Template("VB-SVA", "VERBAL", "Subject–verb agreement", "grammar", _sva_generate, _sva_verify),
    Template("VB-INFER", "VERBAL", "Reading inference", "reading-comprehension", _infer_generate, _infer_verify),
]
