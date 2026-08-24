# 0220 — the refusal names a handle a person would have used

**Date:** 2026-08-24
**Status:** Decided and BUILT. Subsumes 0213's detail string; does not replace
it.

## Context

0213 made an ambiguous reference refuse rather than pick, and gave the refusal
a detail the guest can turn into a question: names for the pieces a person
could have meant, a count for the rest — `"black chair, red chair, and 3 more
chairs that nothing separates"`, degrading to `"2 chairs that nothing
separates"`.

The colour gate declines on most objects. Measured across the walk rooms: rp7
8 of 16, rp6g1 9 of 20, spike 14 of 25, and rp6g2 **0 of 45**. So the degraded
form is the majority case, and 0213's own re-open note anticipated this as the
first thing that would change it.

## What we tried

**The count is false from where the person is standing.** Told that nothing
separates their chairs, they are looking at a room where one is by the window
and one is at the desk. That contradicts the product's claim to understand
space structurally, and it is the one tier that asserts something about the
room rather than about the room's notes.

Position is how people refer to furniture. It shipped second only because
colour was cheap (0184), not because colour was primary.

**Three tiers, most human first**: colour where the gate read one and it is
unique; then a measured spatial relation; then a count. The count stays as the
floor, and where every candidate is placed and no tier names any of them the
string is byte-identical to 0213's — which is what makes this additive rather
than a rewrite.

**The three ways a positional handle is true and still wrong**, each a
constraint rather than a nicety:

- **Unique within the candidate set.** "The chair nearest the desk" ranges over
  every chair, so it is computed over all of them including the ones colour
  already named. If the red chair is nearest the desk, no other chair may wear
  that handle.
- **A separation margin.** 0.90 m and 0.95 m from the desk makes the phrase
  true and useless. Set at **0.50 m**, from the data rather than from taste:
  across the four preserved rooms' 24 duplicate-label sets, the margin a valid
  handle actually has is either tiny or generous, so 0.25 m and 0.50 m name
  **exactly the same handles** and 0.75 m starts costing real ones. 0.50 m is
  the top of the free range, and it sits comfortably above
  `scene_facts._SAME_HEIGHT_BAND_M` — the 0.15 m inside which this product
  already refuses to order two centres at all.
- **An anchor the person can find.** "Nearest the desk" in a two-desk room
  moves the ambiguity rather than resolving it. The bound is
  `named_by_bookkeeping`, reused rather than restated: it is already exactly
  the test for whether a name is decodable, so a two-desk room offers no desk
  while a room with a red desk and a black one offers both. Label-uniqueness
  was the other candidate and is strictly narrower for no gain.

**Both ends of the ranking count.** Nearest and furthest are the same
measurement, the same uniqueness test and the same margin, so taking only the
near end would refuse a handle separated by 2.4 m while accepting one at
0.5 m. It is also what rescues the hardest room: rp6g2 holds five placed
chairs and exactly one anchor a person could find, four of them sit within
0.54 m of each other in distance to it, and the fifth is 2.39 m clear at the
far end. Near-only leaves that room a bare count.

**Never-placed pieces are counted apart, and this is load-bearing rather than
tidy.** A "nearest" claim over a set containing pieces with no position is a
minimum over things the room cannot see — the person's actual chair-by-the-desk
may be one the scan never placed, and then the handle points them at a chair
across the room, which is the silent-wrong-piece failure 0213 exists to
prevent. Splitting them also fixes a conflation 0213 shipped: what separates
an unplaced chair from its siblings is precisely that it was never placed,
which the room knows and was not saying.

**Running the tier over the four real rooms found a defect the synthetic tests
could not.** Six sets came back `"1 monitor that nothing separates"` — nonsense
with one placed piece, because there is nothing to separate it from. Those now
say what does tell it apart: it is the one the scan placed. Refusing is still
right there, for 0213's stated reason.

## What we chose

Colour, then a measured spatial relation, then a count — with uniqueness, a
0.50 m margin and an anchor bound, all three pinned as tests.

The numbers are the ones `scene_facts` already derives its nearest-neighbour
comparatives from: the same centre-to-centre distances over the same
`world_transform.position`. So a handle cannot contradict a fact the guest is
reading in the same breath, and no new perception was added — the charter's
rule 4a already told the guest to offer *"what it stands nearest"*, and the
resolver simply had nothing to hand it.

## Why

**Telling someone nothing distinguishes their own furniture is the product
failing at the thing it claims.** Every other tier in this refusal describes
the room's own limits honestly. The count describes them as the room's
limits — which is what makes it the right floor and the wrong default.

**Refusal is only as good as what it hands back.** 0213 put it exactly:
a refusal handing back vocabulary the person cannot decode is not a refusal,
it is the 0184 defect in a refusal's clothes. A count is decodable and
useless; the improvement is not in refusing less but in refusing better.

**The margin is measured because a threshold picked by taste is a guess about
someone else's room.** The distribution turning out bimodal is the finding
that made the choice cheap — there was a free range, and taking its safe end
cost two handles out of nineteen.

## What would change this decision

- **Real traffic shows people answering the positional question wrong.**
  Nobody outside development has used this surface. If a person picks "the
  chair nearest the desk" and means the other one, the margin is too low, and
  the fix is the threshold rather than the tier.
- **Direct manipulation ships.** Clicking a piece supplies a referent with no
  language in it, and every tier here stops mattering for references that
  arrive that way — 0213 already names this as the thing that ends the whole
  problem.
- **A room's pieces carry a measured facing.** "The chair facing the window"
  is a better handle than either colour or distance, and it is unavailable for
  the reason six instrument families are dead on the 180° sign. Decision 0052's
  standing trigger is this one's too.
- **The anchor bound proves too strict in rooms like rp6g2.** Requiring an
  anchor to be decodable leaves that room one landmark for 45 pieces. Loosening
  it means letting a handle rest on something the person cannot find, which is
  the wrong direction; the right one is more pieces getting colour.
