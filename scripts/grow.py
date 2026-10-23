"""Grow the catalogues when they are running low, so nobody has to look at frames.

    python scripts/grow.py                  # grow if the headroom is under the threshold
    python scripts/grow.py --force          # grow regardless
    python scripts/grow.py --dry-run        # say what it would do

This is the step that makes the project survive its third week. Sixty subjects is two videos;
after that the themes run out and somebody has to curate more by hand, every week, which is
exactly the thing a system meant to run without anyone cannot depend on. So:

  1. count the videos' worth of fresh subjects (core/headroom.py);
  2. if that is under HEADROOM_VIDEOS, ask the language model for new concrete subjects in the
     themes that are thinnest;
  3. run the same three builders that built the first sixty - clips verified by a vision model,
     facts checked by a judge, sounds checked at their source and by a judge - on just the new
     ones;
  4. stop cleanly when the daily Cloudflare allowance runs out, keep what was finished, and
     carry on next time. A subject is only added to the list once it has been tried, so a
     half-finished run never leaves one that cannot make a card.

Everything the builders refuse is recorded with the reason, as before. Nothing here is a model
deciding by itself what goes on a children's channel unchecked: a proposed subject that has no
verified clip, no checked fact is simply never used.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from core import config, db, headroom
from core.llm import QuotaExhausted, complete_json, LLMError
from core.logger import get_logger

log = get_logger("grow")

HEADROOM_VIDEOS = 3        # below this many fresh videos' worth, grow
BATCH = 16                 # new subjects per run: enough to matter, few enough to finish
HIT_RATE = 0.4             # share of curated candidates that end up with footage, measured
SUBJECTS = ROOT / "assets" / "subjects.json"

SYSTEM = """You list things for a learning video for children aged two to six.

Every item has to be a single, concrete, familiar thing a child can SEE and NAME, that appears
in real footage: an animal, a vehicle, a fruit or vegetable, a bird, an insect, a planet, a
machine. Not an idea, not a place, not a person, not a brand, not a species name only a
biologist uses."""


POOL_FILE = ROOT / "assets" / "subject-pool.json"


def from_pool(theme, existing, count):
    """Candidates from the curated pool, which costs nothing and is the right granularity.

    The model used to propose these. It offered "horse cart" as a farm animal, and it offered
    species no verifier can confirm: sparrow, finch, toucan and hummingbird all came back from
    the describer as "bird", goose as "duck", pony as "horse". Those refusals are correct - a
    clip we cannot show IS a finch must not be labelled finch to a three-year-old - so the
    answer was not a looser check but a pool written at the level a small child names things.
    """
    try:
        book = json.loads(POOL_FILE.read_text(encoding="utf-8"))
        pool = book.get("pool") or {}
        terms = book.get("search_terms") or {}
    except Exception:                                            # noqa: BLE001
        return []
    # Already tried and nothing confirmed: the describer said "bird" twelve times for a stork,
    # and it will say it again tomorrow. Such a subject is tried again only if its search term
    # has changed since, which is the one thing that could change the answer.
    from pipeline import catalogue as _cat
    clips = _cat.load()

    def tried_and_failed(subject):
        entry = clips.get(subject)
        if not entry or entry.get("clips"):
            return False
        return entry.get("search_term", subject) == terms.get(subject, subject)

    return [s for s in pool.get(theme, [])
            if s not in existing and not tried_and_failed(s)][:count]


def propose(theme, existing, count, account, token):
    prompt = f"""Theme: {theme}

Already in the list: {', '.join(sorted(existing))}

Give {count} MORE items for this theme, different from those. Rules:
- one or two words, lower case, the name a three-year-old would use ("fire engine", not "emergency vehicle");
- real and photographable; something a stock-footage library will have;
- no brands, no people, no fictional creatures.

Return JSON: {{"subjects": ["...", "..."]}}"""
    data = complete_json(prompt, SYSTEM, account, token, max_tokens=400, temperature=0.8)
    raw = (data or {}).get("subjects") if isinstance(data, dict) else None
    out = []
    for item in raw or []:
        name = re.sub(r"\s+", " ", str(item).strip().lower())
        if (re.fullmatch(r"[a-z]+( [a-z]+)?", name) and name not in existing
                and name not in out):
            out.append(name)
    return out[:count]


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch", type=int, default=BATCH)
    args = parser.parse_args(argv)

    cfg = config.load_config()
    db.init_db()
    groups = json.loads(SUBJECTS.read_text(encoding="utf-8"))
    recent = db.subjects_used_recently(headroom.RECENT_VIDEOS)
    left = headroom.videos_left(recent, cfg.get("cards_per_video", 25))
    fresh = len(headroom.fresh_subjects(recent))
    print(f"{fresh} fresh subjects = {left} video(s) of {cfg.get('cards_per_video', 25)} cards")
    if left >= HEADROOM_VIDEOS and not args.force:
        print(f"at least {HEADROOM_VIDEOS} videos of headroom; nothing to do")
        return 0

    # The themes that cannot fill a video, neediest first - not the thinnest overall. A video
    # is one theme now, so a theme below the floor is a video that cannot be made, while the
    # total count across all themes says nothing about whether tomorrow has a video in it.
    from pipeline import catalogue as _cat, plan as _plan
    sizes = _plan.theme_sizes(groups, _cat.load(), json.loads(
        (ROOT / "assets" / "facts.json").read_text(encoding="utf-8")))
    floor = int(cfg.get("min_theme_cards", _plan.MIN_THEME_CARDS))
    target = int(cfg.get("cards_per_video", 25))
    # Closest to the floor first, not thinnest: a theme two short of fifteen is a video next
    # week, one seven short is not, and every theme over the line is a day that has a video.
    short = sorted(((floor - n, t) for t, n in sizes.items() if n < floor), key=lambda r: r)
    # How many candidates each needs: the shortfall, over the hit rate the curated pool has
    # measured (6 of 12 for insects, 3 of 15 for birds), rounded up and capped by the batch.
    plan_for = {}
    budget = args.batch
    for missing, theme in short:
        want = min(budget, max(3, int(missing / HIT_RATE + 0.999)))
        if want <= 0:
            break
        plan_for[theme] = want
        budget -= want
    themes = list(plan_for) or headroom.thinnest_themes(groups, recent)
    print("theme sizes: " + ", ".join(f"{t} {n}" for t, n in
                                      sorted(sizes.items(), key=lambda kv: kv[1])))
    print(f"below the {floor}-card floor: "
          f"{', '.join(t for t, n in sizes.items() if n < floor) or 'none'}")
    print(f"growing: {', '.join(themes)}")
    if args.dry_run:
        return 0

    account, token, _pixabay = config.credentials()
    if not (account and token):
        print("needs CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN")
        return 2

    existing = {s for items in groups.values() for s in items}
    added = {}
    try:
        for theme in themes:
            per_theme = plan_for.get(theme, 3)
            new = from_pool(theme, existing, per_theme)
            if len(new) < per_theme:
                # The pool is finite. When a theme runs through it, the model fills in - with
                # the same rules, and the verifier still has the last word.
                new += [s for s in propose(theme, existing | set(new), per_theme - len(new),
                                           account, token) if s not in new]
            if new:
                added[theme] = new
                existing.update(new)
    except QuotaExhausted:
        print("the daily allowance is spent before any subject was proposed; try again later")
        return 0
    except LLMError as e:
        print(f"could not ask for subjects: {str(e)[:100]}")
        return 1
    flat = [s for items in added.values() for s in items]
    if not flat:
        print("the model proposed nothing usable")
        return 0
    print("proposed:", {t: v for t, v in added.items()})

    import build_catalogue
    import build_facts
    import build_sounds
    args_for = [a for s in flat for a in ("--subject", s)]
    stopped = False
    for name, module in (("clips", build_catalogue), ("facts", build_facts),
                         ("sounds", build_sounds)):
        print(f"\n== {name} ==")
        try:
            code = module.main(args_for)
        except QuotaExhausted:
            print("the daily allowance ran out part-way; what was finished is saved")
            stopped = True
            break
        if code not in (0, None):
            stopped = True

    # A subject joins the list only if it came out of the builders with a clip and a fact.
    complete = set(headroom.complete_subjects())
    kept = {t: [s for s in v if s in complete] for t, v in added.items()}
    for theme, names in kept.items():
        groups[theme] = sorted(set(groups[theme]) | set(names))
    SUBJECTS.write_text(json.dumps(groups, indent=2, sort_keys=True), encoding="utf-8")
    total = sum(len(v) for v in kept.values())
    print(f"\n{total} of {len(flat)} proposed subjects are complete and now on the list"
          f"{' (the allowance ran out before the rest could be tried)' if stopped else ''}")
    for theme, names in kept.items():
        print(f"  {theme}: {', '.join(names) or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
