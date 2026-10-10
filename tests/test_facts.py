"""Offline tests for the fact rules and the fact catalogue. Run: python tests/test_facts.py

No network: the judge is not called. What is tested is everything around it - the structural
rules, the near-duplicate check, and that the daily plan takes a checked fact rather than
writing one.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.logger
core.logger.LOG_DIR = Path(tempfile.mkdtemp(prefix="yt-kids-test-"))

from pipeline import cards


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


def test_the_structural_rules():
    print("test_the_structural_rules")
    check(not cards.fact_problems("An octopus has eight arms.", "octopus"), "a good fact passes")
    check(cards.fact_problems("The blue whale weighs 150 tonnes.", "whale"),
          "a measurement is refused - a tonne is not a thing anyone has seen")
    check(cards.fact_problems("A whale has twenty teeth.", "whale"),
          "a number past what a three-year-old counts to is refused")
    check(cards.fact_problems("The whale uses echolocation to find food.", "whale"),
          "a word too long for a three-year-old is refused")
    check(cards.fact_problems("Whales swim.", "whale"), "three words is too short")
    check(cards.fact_problems("A duck swims in the water and eats bread and quacks a lot.",
                              "duck"), "and thirteen is too long")
    check(cards.fact_problems("A whale is big", "whale"), "no full stop is refused")
    check(cards.fact_problems("An octopus is clever.", "whale"),
          "a fact that does not name its own subject is refused")


def test_the_comparison_crutch_cannot_come_back():
    """The model was given a list of things a child has seen and used them as a template:
    "the banana is yellow like a spoon", "the octopus has many legs like a cat"."""
    print("test_the_comparison_crutch_cannot_come_back")
    for bad in ("The banana is yellow like a spoon.", "The octopus has many legs like a cat.",
                "A penguin is black and white like a cat."):
        check(cards.fact_problems(bad, bad.split()[1]), f"refused: {bad}")
    check(not cards.fact_problems("A whale is bigger than a bus.", "whale"),
          "but a comparison that is true and helps is still allowed")
    check(cards.fact_problems("The fire truck is big and red now.", "fire truck"),
          "a filler word at the end is refused")


def test_a_reworded_fact_is_the_same_fact():
    print("test_a_reworded_fact_is_the_same_fact")
    have = ["A seahorse swims in the water."]
    check(cards.is_near_duplicate("A seahorse swims in water.", have),
          "dropping 'the' does not make it a new fact")
    check(cards.is_near_duplicate("The seahorse swims in the water.", have),
          "nor does swapping the article")
    check(not cards.is_near_duplicate("A seahorse carries its baby.", have),
          "but a different fact about the same thing is kept")
    check(cards.is_near_duplicate("the a an", have), "a fact with no content counts as seen")


def test_the_prompt_tells_the_model_what_it_already_said():
    print("test_the_prompt_tells_the_model_what_it_already_said")
    text = cards._prompt(["seahorse"], avoid=["A seahorse swims in the water."])
    check("already been written" in text and "swims in the water" in text,
          "the facts already kept are quoted back, so it does not repeat itself")
    check("Not a rewording" in text, "and it is told not to reword them")


def test_the_daily_plan_uses_a_checked_fact_and_never_writes_one():
    print("test_the_daily_plan_uses_a_checked_fact_and_never_writes_one")
    source = (ROOT / "pipeline" / "plan.py").read_text(encoding="utf-8")
    check("write_facts" not in source,
          "pipeline/plan.py does not call the fact writer at all")
    check("facts.json" in source or "_load_facts" in source,
          "it reads the checked ones instead")
    book = json.loads((ROOT / "assets" / "facts.json").read_text(encoding="utf-8")) \
        if (ROOT / "assets" / "facts.json").exists() else {}
    for subject, entry in list(book.items())[:200]:
        for f in entry.get("facts", []):
            check_one = cards.fact_problems(f["fact"], subject)
            check(not check_one, f"{subject}: {f['fact']!r} still passes the rules")
            break


if __name__ == "__main__":
    test_the_structural_rules()
    test_the_comparison_crutch_cannot_come_back()
    test_a_reworded_fact_is_the_same_fact()
    test_the_prompt_tells_the_model_what_it_already_said()
    test_the_daily_plan_uses_a_checked_fact_and_never_writes_one()
    print("ALL FACT TESTS PASSED")
