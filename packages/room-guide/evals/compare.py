"""Puts two models' eval runs side by side, with what each judge made of them.

    python -m evals.compare <out> claude-opus-5-5 claude-sonnet-5-5 --judges judge-opus judge-sonnet

Run it from packages/room-guide, after run.py and judge.py. It writes
`<out>/comparison.md` and prints it.

Read by: a developer comparing models or prompts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.judge import CRITERIA

SHORT = {"claude-opus-5-5": "Opus 5.5", "claude-sonnet-5-5": "Sonnet 5.5"}


def _load(p: Path) -> dict | None:
    return json.loads(p.read_text()) if p.exists() else None


def comparison(out: Path, m1: str, m2: str, judges: list[str]) -> str:
    s = {m: _load(out / m / "summary.json") for m in (m1, m2)}
    if not all(s.values()):
        raise SystemExit("run both models first")
    rooms = sorted({p.parent.name for m in (m1, m2) for p in (out / m).glob("*/result.json")})
    res = {m: {r: _load(out / m / r / "result.json") for r in rooms} for m in (m1, m2)}
    js = {j: d for j in judges if (d := _load(out / j / "judge.json"))}
    n1, n2 = SHORT.get(m1, m1), SHORT.get(m2, m2)

    def row(label, f):
        return f"| {label} | {f(m1)} | {f(m2)} |"

    lines = [f"| | {n1} | {n2} |", "|---|---|---|",
             row("Planted problems the rules pass let the analyzer find",
                 lambda m: f"{s[m]['planted_found']} of {s[m]['planted']}"),
             row("A card offered that fixes the planted problem",
                 lambda m: f"{s[m]['card_fixes_planted']} of {s[m]['planted']}"),
             row("Rooms with nothing planted where it raised a serious problem",
                 lambda m: f"{s[m]['clean_rooms_with_problems']} of {s[m]['rooms'] - s[m]['planted']}"),
             row("Rules passes that fell back to the defaults", lambda m: str(s[m]["rules_defaults"])),
             row("Turns flagged (over four sentences, or a number from nowhere)",
                 lambda m: f"{s[m]['flagged_turns']} of {s[m]['turns']}"),
             row("Words per turn", lambda m: str(s[m]["words_per_turn"])),
             row("Rules pass, seconds (mean)", lambda m: str(s[m]["rules_seconds"])),
             row("A turn, seconds (mean)", lambda m: str(s[m]["turn_seconds"])),
             row("Cost, all rooms", lambda m: f"${s[m]['billed_usd']:.2f}"),
             row("Cost per room", lambda m: f"${s[m]['billed_usd'] / max(s[m]['rooms'], 1):.3f}")]
    for j, d in js.items():
        judge = SHORT.get(d["judge"], d["judge"])
        lines.append(row(f"Rooms won, judged by {judge} (both readings agree)",
                         lambda m, d=d: f"{d['wins'][m]} (ties {d['ties']})"))
        for c in CRITERIA:
            lines.append(row(f"{c.capitalize()}, judged by {judge} (of {d['out_of']})",
                             lambda m, d=d, c=c: str(d["totals"][m][c])))

    head = ["| Room | Found " + n1 + " | Found " + n2 + " | Fixing card " + n1 + " | Fixing card " + n2
            + "".join(f" | Winner ({SHORT.get(d['judge'], d['judge'])})" for d in js.values()) + " |",
            "|---" * (5 + len(js)) + "|"]
    for r in rooms:
        a, b = res[m1][r], res[m2][r]

        def found(x):
            if x is None:
                return "not run"
            if not x["expect"]:
                return "nothing planted"
            return "yes" if all(x["found"].values()) else "no"

        def card(x):
            if x is None or not x["expect"]:
                return "-"
            return "yes" if x["card_fixes_planted"] else "no"

        wins = []
        for d in js.values():
            v = next((v for v in d["rooms"] if v["room"] == r), None)
            wins.append(SHORT.get(v["winner"], v["winner"]) if v else "-")
        head.append(f"| {r} | {found(a)} | {found(b)} | {card(a)} | {card(b)}"
                    + "".join(f" | {w}" for w in wins) + " |")
    text = "\n".join(lines + [""] + head) + "\n"
    (out / "comparison.md").write_text(text)
    return text


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("first")
    ap.add_argument("second")
    ap.add_argument("--judges", nargs="*", default=[])
    a = ap.parse_args(argv)
    print(comparison(a.out, a.first, a.second, a.judges))


if __name__ == "__main__":
    main()
