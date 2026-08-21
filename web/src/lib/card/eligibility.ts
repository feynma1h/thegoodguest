/**
 * Whether a room may produce a card at all.
 *
 * THE RULE (decision 0089, generalised to sharing by 0208): a room may
 * leave its owner's account only if every frame of its scene was segmented
 * on a suppression-armed revision. `person` is a suppression-only concept
 * — segmented so its pixels can be EXCLUDED from surface evidence, never
 * reconstructed — and suppression is not retroactive. A scene segmented
 * before it shipped was never asked about people, so its zero
 * person-detections prove nothing, and its measured wall albedo may be a
 * person standing in front of that wall. That is not hypothetical: it is
 * the shipped defect on `f3d70236`'s wall_03 that 0089 was written to fix,
 * and the Privacy Policy tells users about it in §8.
 *
 * THE EXPOSURE IS INVERTED FROM INTUITION, which is why this file exists
 * beside a feature that ships no splats. A person contaminates a wall's
 * measured ALBEDO, and the shell — geometry and albedo — is exactly what
 * the card draws. The card carrying no object likeness makes it look
 * unrelated to segmentation. It is not: the card is the rung where this
 * rule matters MOST (0208).
 *
 * WHY A DATE AND NOT A FIELD. The rule is not checkable from a room's own
 * data — the manifest records no suppression provenance, and the per-frame
 * `suppressed` union lives inside masks.npz, which the serving path never
 * reads. 0122 established the landing hero's eligibility by hand, comparing
 * timestamps against a revision's deploy time; that is adequate for one
 * curated fixture and inadequate for a feature every person can invoke.
 * The two ways to close it are a conservative `created_at` gate and a
 * manifest provenance field. This is the date gate. Decision 0221 records
 * why, and what would trigger the field.
 *
 * WHAT THE GATE IS AND IS NOT. It is not an access boundary: the shell is
 * already in the browser, because the room page fetched it to render the
 * room. The gate decides whether the product will MANUFACTURE a portable
 * artifact out of a measurement it cannot vouch for. Moving it to the
 * server would protect nothing that is not already served, which is why
 * the card needs no new route.
 *
 * ONE-DIRECTIONAL BY CONSTRUCTION. It refuses some eligible rooms — an
 * older scene re-driven cold on a suppression-armed revision is eligible
 * and this gate still says no. Refusing an eligible room is the safe
 * error; the reverse is not, and there is no reading of this file under
 * which the unsafe error is available.
 */

/**
 * The first suppression-armed perception-obj revision, and its Cloud Run
 * creation time.
 *
 * `perception-obj-00036-l9l` carried decisions 0089 (person suppression)
 * and 0090 (the dedicated runtime SA) and was created 2026-08-07T21:27:53Z.
 * 0122 used this exact revision and timestamp to adjudicate the landing
 * hero by hand; this constant is that adjudication made general.
 *
 * The premise the gate rests on, stated so it can be checked rather than
 * assumed: NO revision serving after this one lacks suppression. Every
 * perception-obj revision since is a descendant of that deploy, and the
 * standing rollback target (`00044-m5p`, image `20260813-222442`) is far
 * later. Rolling traffic back below `00036-l9l` would be a privacy
 * regression in its own right, and it would invalidate this constant —
 * which is the one operational fact that would require revisiting it.
 *
 * IT MOVES FORWARD, NEVER BACK. `PERCEPTION_SUPPRESSED_CONCEPTS` is
 * env-configurable and defaults to "person". If a second concept is ever
 * added, the eligibility boundary advances to that deploy and every room
 * segmented before it is re-stranded (0208's own reopening trigger). Bump
 * this constant then; do not add a second one.
 */
export const SUPPRESSION_ARMED_SINCE = "2026-08-07T21:27:53Z";

/** Millisecond form, resolved once. */
const ARMED_MS = Date.parse(SUPPRESSION_ARMED_SINCE);

export type CardRefusal =
  /** Scanned before person suppression shipped — see the rule above. */
  | "pre_suppression"
  /** No usable `created_at`, so the rule cannot be evaluated. Refuse. */
  | "undated"
  /** The scene never reached `ready`; there is no measurement to draw. */
  | "not_ready";

export type CardEligibility =
  | { eligible: true }
  | { eligible: false; reason: CardRefusal };

/** The room shape this gate needs — a subset of SceneSummary. */
export interface GatedScene {
  status: string;
  created_at: string;
}

/**
 * Whether this room may produce a card.
 *
 * Refuses on anything it cannot positively establish, including a
 * `created_at` it cannot parse. There is deliberately no branch that
 * admits a room on the absence of evidence.
 */
export function cardEligibility(scene: GatedScene): CardEligibility {
  if (scene.status !== "ready") {
    return { eligible: false, reason: "not_ready" };
  }
  const created = Date.parse(scene.created_at ?? "");
  if (!Number.isFinite(created)) {
    return { eligible: false, reason: "undated" };
  }
  // Strictly after: a scene created in the same instant as the deploy is
  // not provably later than it.
  if (created <= ARMED_MS) {
    return { eligible: false, reason: "pre_suppression" };
  }
  return { eligible: true };
}
