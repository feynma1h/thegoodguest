/**
 * Applying a Design Specification to an assembled scene (decision 0131).
 *
 * The spec is a sibling document, not a rewrite of the manifest, so this is
 * the one place the two meet — a pure override pass over `assembleScene`'s
 * output. `PositionedSplat` is unchanged as the renderer's input contract
 * (0053's containment rule): the renderer never learns that a proposal
 * exists, which is exactly why stage 2 could ship on the imperative viewer
 * instead of waiting for R3F (0133).
 *
 * Two rules the shapes here enforce:
 *
 * 1. **A removal HIDES; it does not drop.** Removing the splat from the array
 *    would change the renderer's structural key and unmount the mesh, and
 *    0130 measured that unmount/remount is a full re-download and re-parse.
 *    "Back to measured" must always be one cheap action (0133), so a removed
 *    piece stays in the list carrying `hidden`.
 *
 * 2. **The measurement stays on screen.** Every applied entry yields a
 *    `MeasuredOutline` — the piece's measured footprint, drawn on the floor
 *    in the reveal's contour language, which in this room MEANS measurement
 *    (0097's pen in the paper tone). Not a badge and not a ghost of the
 *    object: 0057 settled that state reads as treatment plus words.
 *
 * The join runs on the same key the server writes (`box:<identifier>` where
 * a RoomPlan box exists, `obj:<object_id>` otherwise) — recomputed here from
 * the manifest so client and server derive it identically rather than the
 * client trusting an index.
 */

import type {
  DesignSpecDoc,
  FusedObject,
  PositionedSplat,
  SceneManifest,
  SpecEntry,
} from "@/lib/api/types";
import type { MeasuredOutline } from "@/components/SplatViewer";

/** The spec key for one manifest object. Mirrors `room_geometry.spec_key`. */
export function specKey(obj: Pick<FusedObject, "object_id"> & {
  roomplan_box?: { identifier?: string } | null;
}): string {
  const ident = obj.roomplan_box?.identifier;
  return ident ? `box:${ident}` : `obj:${obj.object_id}`;
}

/** What happened to one splat, parallel to `splats`. The inventory reads
 * this rather than re-deriving from labels, which collide (two chairs).
 *
 * `turned` is a piece the person corrected, not one they rearranged — it
 * stands exactly where the scan measured it (decision 0157). A piece that was
 * both moved and turned reads as `moved`: where it stands is the bigger claim,
 * and the entry's own description says the rest. */
export type SplatState = "measured" | "moved" | "removed" | "turned";

export interface ProposedScene {
  splats: PositionedSplat[];
  states: SplatState[];
  outlines: MeasuredOutline[];
  /** Entries that changed something renderable, in spec order — what the UI
   * lists as "what's changed". */
  applied: SpecEntry[];
  /** Entries whose key no longer resolves. Surfaced, never swallowed. */
  orphaned: SpecEntry[];
}

/**
 * Overlay a spec on the assembled splats.
 *
 * `manifest` supplies the key for each splat: `assembleScene` produces
 * `PositionedSplat`s in manifest-object order for the objects it could
 * render, so the two are walked together rather than matched by label (two
 * chairs share a label; a key is a key).
 */
export function applyDesignSpec(
  splats: PositionedSplat[],
  manifest: SceneManifest,
  spec: DesignSpecDoc | null,
): ProposedScene {
  if (!spec || spec.entries.length === 0) {
    return {
      splats,
      states: splats.map(() => "measured" as const),
      outlines: [],
      applied: [],
      orphaned: [],
    };
  }
  const byKey = new Map<string, SpecEntry>();
  for (const entry of spec.entries) {
    if (!entry.orphaned) byKey.set(entry.key, entry);
  }

  // Rebuild the key sequence assembleScene walked: renderable objects, in
  // manifest order. A splat with no matching object keeps its transform.
  const renderableKeys: string[] = [];
  for (const obj of manifest.objects ?? []) {
    if (obj.placed && obj.world_transform && obj.splat_gcs_uri) {
      renderableKeys.push(specKey(obj));
    }
  }

  const applied: SpecEntry[] = [];
  const seen = new Set<string>();
  const states: SplatState[] = [];
  const out = splats.map((splat, i) => {
    const key = renderableKeys[i];
    const entry = key ? byKey.get(key) : undefined;
    if (
      !entry ||
      ((entry.action === "move" || entry.action === "turn") &&
        !entry.proposed_transform)
    ) {
      states.push("measured");
      return splat;
    }
    seen.add(key);
    applied.push(entry);
    if (entry.action === "remove") {
      states.push("removed");
      return { ...splat, hidden: true };
    }
    states.push(entry.action === "turn" ? "turned" : "moved");
    return {
      ...splat,
      position: entry.proposed_transform!.position,
      rotation_xyzw: entry.proposed_transform!.rotation_xyzw,
      // A per-axis scale only ever comes from a staged A/B fixture, and a
      // proposal never changes scale — so an existing triple is preserved
      // rather than flattened to the server's uniform number.
      scale: typeof splat.scale === "number"
        ? entry.proposed_transform!.scale
        : splat.scale,
    };
  });

  // Outlines come from the ENTRIES, in spec order, so the drawing order is
  // the order the person made the changes.
  //
  // A piece that was only TURNED gets none, and this is the honest answer
  // rather than a stylistic one (decision 0157). A half turn maps a rectangle
  // onto itself, so the measured footprint is exactly the ground the piece is
  // standing on — drawing it would put a measurement line under an object that
  // never left it, saying "here is where this used to be" about the spot it
  // is currently occupying.
  const outlines: MeasuredOutline[] = [];
  for (const entry of spec.entries) {
    if (entry.orphaned || !seen.has(entry.key)) continue;
    if (entry.departs_from !== "measurement") continue;
    if (!entry.measured_footprint) continue;
    outlines.push(entry.measured_footprint);
  }

  return {
    splats: out,
    states,
    outlines,
    applied,
    orphaned: spec.entries.filter((e) => e.orphaned),
  };
}

/**
 * The line under the composer when a room is showing a proposal.
 *
 * Deliberately not the guest's voice — this is chrome stating a fact about
 * what is on screen, and it must read as the product being straight with
 * you rather than as the guest narrating. Counting is the honest summary: a
 * list of descriptions belongs in the panel, not in one line.
 *
 * A room that has ONLY been corrected does not offer the measured room back,
 * because it never left: a turn changes nothing that was measured (decision
 * 0157), and "the measured room is one step away" would be offering to undo
 * something the person told us about their own home.
 */
export function arrangementNote(applied: SpecEntry[]): string | null {
  if (applied.length === 0) return null;
  const rearranged = applied.filter((e) => e.departs_from === "measurement");
  const moved = rearranged.filter((e) => e.action === "move").length;
  const removed = rearranged.length - moved;
  const turned = applied.filter((e) => e.facing_flipped).length;
  const parts: string[] = [];
  if (moved) parts.push(`${moved} ${moved === 1 ? "piece" : "pieces"} moved`);
  if (removed) parts.push(`${removed} taken out`);
  if (turned) parts.push(`${turned} turned round`);
  const summary = parts.join(", ");
  return rearranged.length
    ? `${summary} — the measured room is one step away`
    : `${summary} — where you told me it faces`;
}

/** What the orphan notice says. Its whole job is to not pretend. */
export function orphanNote(orphaned: SpecEntry[]): string | null {
  if (orphaned.length === 0) return null;
  const names = orphaned.map((e) => e.label).filter(Boolean);
  const what = names.length ? names.join(", ") : `${orphaned.length} of them`;
  return orphaned.length === 1
    ? `A change to the ${what} no longer matches anything in this room — the scan has been reprocessed since. It is not being shown.`
    : `Changes to ${what} no longer match anything in this room — the scan has been reprocessed since. They are not being shown.`;
}
