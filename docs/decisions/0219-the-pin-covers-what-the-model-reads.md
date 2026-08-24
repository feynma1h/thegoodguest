# 0219 — the pin covers what the model reads

**Date:** 2026-08-24
**Status:** Decided and BUILT at `PROMPT_VERSION 7`.

## Context

`PROMPT_SURFACE_SHA256` exists so that no instruction the guest reads can
change without a version bump and an eval trigger. `guest_prompt.py`'s
docstring said so in as many words — *"The pin covers the whole instruction
surface"* — and named decision 0174 as the defect the mechanism failed to
catch, prose outside the pin being reworded through two bumps unnoticed.

`guest_tools.TOOLS` carries several hundred words of instruction the model
reads in the same request as the charter, and none of it was under the pin.

## What we tried

Nothing else was seriously considered; the interesting question was SCOPE, and
there were two live ones.

**Prose only, or the schema too?** The tool descriptions are obviously
instruction — *"Do NOT call it for an idea of your own"*, *"A refusal is a
real answer: say it plainly"*, *"There is exactly one turn available"*. The
schema is less obviously so, and it is pinned anyway. An `enum` the model
chooses from is instruction in the only sense that matters here: `RELATIONS`
reaches the guest through this text and nowhere else, so adding a relation
changes what the guest believes it can do without touching a word of prose.
The same goes for `maxItems` on `changes`.

Serialising the whole structure canonically also makes the cover TOTAL rather
than a list someone has to remember to extend. A description added to a new
property years from now is pinned without anyone thinking about it, which is
the only form of this that survives contact with future lanes.

**Which module owns it?** `guest_prompt` imports `guest_tools`, not the
reverse. The pin belongs where `PROMPT_VERSION` lives, because the two are one
mechanism. There is no cycle: `guest_tools` reaches `design_spec`,
`room_geometry` and `spec_solver`, none of which reach back.

**The recorded objection was checked and is false.** When this hole was found
on 2026-08-21 it was left deliberately, on the grounds that widening a pin
turns other lanes' evals red and that is a scheduling call. `selection`,
`social-layer` and `ios-surfaces` touch zero files under
`services/api-public/`, so there was nothing to schedule around.

## What we chose

The tools join the digest, schema and all. `PROMPT_VERSION 7`, and **the
charter is unchanged at this bump** — the version moves because the mechanism
now covers more, not because the guest is told anything different.

Three tests, all by construction rather than by reading the digest's value:

- every string the structure carries, at any depth, moves the pin when
  mutated;
- adding or dropping a whole tool moves it;
- and the harness reproduces the live digest when nothing is mutated, without
  which the other two prove nothing.

They drive the REAL recipe by reloading the module over a substituted
`guest_tools.TOOLS`, rather than recomputing the hash locally. A test that
rebuilt the recipe would keep passing after someone narrowed the real one,
which is exactly the failure being guarded against — verified by narrowing it
to the tool names and watching the test go red.

## Why

**A safety mechanism advertising a guarantee it does not provide is worse than
no mechanism**, and this repo's standards forbid it in as many words: no claim
in a doc or comment that contradicts the code. Anyone reading `guest_prompt`'s
docstring would have concluded the guest's instructions were pinned. Two of
the three places they live were.

**It is the same hole 0174 came through, one file over.** 0175 closed it for
the arrangement block on exactly this reasoning — prose outside the pin *"could
be reworded with no version bump and no eval trigger"* — and stopped at the
edge of the module. The tools were never argued about; they were not looked at.

**The pin's value is entirely in being total.** A hash over most of the
instruction surface does not give a weaker guarantee than a hash over all of
it — it gives a false one, because the failure mode is a lane editing the part
nobody remembered.

## What would change this decision

- **A tool's schema starts carrying per-scene data.** Everything in `TOOLS`
  today is static, which is what makes a compile-time digest meaningful. A
  field computed per room would have to be excluded explicitly and loudly,
  the way the facts block is — it is data the prompt renders, not instruction,
  and `FACTS_VERSION` is its version.
- **The tool set grows enough that every solver change trips this.**
  `RELATIONS` is `spec_solver`'s, so a lane adding a relation now needs a
  `PROMPT_VERSION` bump and an eval run. That is correct — a new relation is a
  new capability the guest reads about — but if it becomes routine the answer
  is to run the evals, never to drop the enum from the digest.
