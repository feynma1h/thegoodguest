/**
 * The viewer's change signatures — what a given change costs SplatViewer,
 * expressed as one string per effect (decisions 0133/0188).
 *
 * SplatViewer has one effect that BUILDS the renderer and several that
 * UPDATE what it holds. Each is keyed on a signature from this module, and
 * the whole point is that they are separate: anything in `rendererKey`
 * tears the renderer down and constructs it again, which for splats means
 * a full re-download and re-parse — 275.8 MB and 25–56 s on the reference
 * room before the compressed tier, 47.2 MB and 14–19 s after (0123/0125),
 * with nothing served from cache (0188 confirmed the re-fetch is real).
 * Anything in the other keys costs only its own rebuild.
 *
 * So the rule this module exists to hold is one line: **the renderer key
 * carries only what a change genuinely needs a new renderer for.** Note
 * what that is NOT. It is not "expensive things belong in the key" — the
 * key's cost is never the cost of the keyed object, it is the cost of
 * everything else in the scene. A measured outline is a five-vertex line
 * and was in the renderer key on exactly that reasoning ("cheap to
 * rebuild"); because the key is global, adding one reloaded the room.
 *
 * Why each field sits where it does:
 *   - `url`      — a different file is a different thing to load. Renderer.
 *   - `clip`     — an SDF edit parented into the mesh, i.e. a different
 *                  GEOMETRY of the same file. Renderer. It is also why a
 *                  move needs no clip rebuild: the volume is expressed in
 *                  the mesh's own frame, so it travels with the object.
 *   - `shell`    — room surfaces: real geometry, materials and a light
 *                  rig, and fixed for a scene's lifetime (assets are
 *                  fetched once). Renderer, because it never changes while
 *                  the renderer is alive. If a shell ever updates in place,
 *                  it needs its own effect like the two below.
 *   - position / rotation / scale / hidden — placement. In no key at all;
 *     applied straight to the live meshes. (`hidden` in particular: a
 *     removal the person can undo must not cost a re-download, per 0130's
 *     measurement that unmount/remount does.)
 *   - `outlines` — measured footprints a proposal leaves behind. They
 *     appear, change and clear WHILE the renderer is alive, which is the
 *     whole reason they get their own key and their own effect.
 *   - `labels`   — dev-workbench badges. Same shape, same treatment; today
 *     the workbench sets them once, which is precisely why this copy of the
 *     defect was never seen.
 *
 * Consumers: components/SplatViewer.tsx (its one caller), and the tests
 * beside this file, which are the actual guard — the cost of getting this
 * wrong is invisible on screen and shows up only as a room that reloads.
 */

import type { PositionedSplat, ShellPlane } from "@/lib/api/types";
import type { MeasuredOutline, ViewerLabel } from "@/components/SplatViewer";

export interface ViewerKeyInput {
  splats: PositionedSplat[];
  shell?: ShellPlane[] | null;
}

/** What SplatViewer must construct a renderer for. Deliberately narrow. */
export function rendererKey({ splats, shell = null }: ViewerKeyInput): string {
  const splatPart = splats
    .map(
      (s) =>
        `${s.url}#${
          s.clip
            ? `${s.clip.center_world.join(",")}/` +
              `${s.clip.half_extents_m.join(",")}/${s.clip.yaw_rad}`
            : "-"
        }`,
    )
    .join("|");
  const shellPart =
    shell
      ?.map((p) => `${p.kind}:${p.material.albedo_hex ?? "-"}:${p.corners.length}`)
      .join(",") ?? "none";
  return `${splatPart}|shell:${shellPart}`;
}

/** The measured footprints on the floor. Rebuilt in place; costs a few
 * lines of geometry and touches nothing else in the scene. */
export function outlinesKey(outlines?: MeasuredOutline[] | null): string {
  // Absent and empty are one signature: both mean nothing to draw, and a
  // room with no proposal passes an empty array rather than null.
  if (!outlines || outlines.length === 0) return "none";
  return outlines
    .map(
      (o) =>
        `${o.center_world.join(",")}/${o.half_extents_m.join(",")}/${o.yaw_rad}`,
    )
    .join(",");
}

/** The dev-workbench badges. Rebuilt in place, same as the outlines. */
export function labelsKey(labels?: ViewerLabel[] | null): string {
  if (!labels || labels.length === 0) return "none";
  return labels.map((l) => `${l.kind}${l.text}@${l.position.join(",")}`).join(",");
}
