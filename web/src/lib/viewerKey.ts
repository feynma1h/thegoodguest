/**
 * The renderer's structural signature — what SplatViewer BUILDS, as opposed
 * to where it puts things (decision 0133).
 *
 * SplatViewer's build effect is keyed on this string. Anything in the key
 * tears the renderer down and constructs it again, which for splats means a
 * full re-download and re-parse: 275.8 MB and 25–56 s on the reference room
 * before the compressed tier, 47.2 MB after (0123/0125). Anything NOT in the
 * key is applied to the live meshes instead, and costs a matrix write.
 *
 * So the rule this module exists to hold is one line: **structure belongs in
 * the key, placement does not.** A splat's position used to sit here, which
 * meant a proposed move reloaded the entire room — the one blocker stage 2
 * had to clear before it could ship at all.
 *
 * Why each field is on the side it is on:
 *   - `url`      — a different file is a different thing to load. Structure.
 *   - `clip`     — an SDF edit parented into the mesh, i.e. a different
 *                  GEOMETRY of the same file. Structure. It is also why a
 *                  move needs no clip rebuild: the volume is expressed in
 *                  the mesh's own frame, so it travels with the object.
 *   - position / rotation / scale / hidden — placement. Never in the key.
 *     (`hidden` in particular: a removal the person can undo must not cost
 *     a re-download, per 0130's measurement that unmount/remount does.)
 *   - shell / labels / outlines — built objects with no placement seam of
 *     their own; they are cheap to rebuild and rare to change. Structure.
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
  labels?: ViewerLabel[] | null;
  outlines?: MeasuredOutline[] | null;
}

export function rendererKey({
  splats,
  shell = null,
  labels = null,
  outlines = null,
}: ViewerKeyInput): string {
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
  const labelPart =
    labels?.map((l) => `${l.kind}${l.text}@${l.position.join(",")}`).join(",") ??
    "none";
  const outlinePart =
    outlines?.map((o) => `${o.center_world.join(",")}/${o.yaw_rad}`).join(",") ??
    "none";
  return (
    `${splatPart}|shell:${shellPart}|labels:${labelPart}|outlines:${outlinePart}`
  );
}
