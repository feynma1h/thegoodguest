import { describe, expect, it } from "vitest";

import type { MeasuredOutline, ViewerLabel } from "@/components/SplatViewer";
import type { PositionedSplat, ShellPlane } from "@/lib/api/types";
import { labelsKey, outlinesKey, rendererKey } from "@/lib/viewerKey";

const splat = (over: Partial<PositionedSplat> = {}): PositionedSplat => ({
  url: "https://example.test/bed.spz",
  label: "bed",
  position: [1, 0.4, 2],
  rotation_xyzw: [0, 0, 0, 1],
  scale: 1,
  ...over,
});

const plane = (): ShellPlane => ({
  kind: "floor",
  corners: [
    [0, 0, 0],
    [4, 0, 0],
    [4, 0, 3],
    [0, 0, 3],
  ],
  material: { albedo_hex: "#c8c1b7", roughness: 0.9, family: "stone" },
  openings: [],
  confidence: "high",
});

describe("rendererKey — placement is NOT structure", () => {
  // The whole point of the module: these are the changes stage 2 makes on
  // every proposal, and each one must be free.
  it("is unchanged by a move", () => {
    const before = rendererKey({ splats: [splat()] });
    const after = rendererKey({ splats: [splat({ position: [3.2, 0.4, 0.7] })] });
    expect(after).toBe(before);
  });

  it("is unchanged by a rotation", () => {
    const before = rendererKey({ splats: [splat()] });
    const after = rendererKey({
      splats: [splat({ rotation_xyzw: [0, 0.7071, 0, 0.7071] })],
    });
    expect(after).toBe(before);
  });

  it("is unchanged by a rescale", () => {
    const before = rendererKey({ splats: [splat()] });
    expect(rendererKey({ splats: [splat({ scale: 1.4 })] })).toBe(before);
    expect(rendererKey({ splats: [splat({ scale: [1, 1.2, 1] })] })).toBe(before);
  });

  it("is unchanged by hiding a piece — a removal must be free to undo", () => {
    const before = rendererKey({ splats: [splat()] });
    expect(rendererKey({ splats: [splat({ hidden: true })] })).toBe(before);
  });

  it("is unchanged when every placement field moves at once", () => {
    const before = rendererKey({ splats: [splat(), splat({ url: "b.spz" })] });
    const after = rendererKey({
      splats: [
        splat({ position: [9, 9, 9], rotation_xyzw: [1, 0, 0, 0], scale: 2 }),
        splat({ url: "b.spz", hidden: true, position: [-1, 0, -1] }),
      ],
    });
    expect(after).toBe(before);
  });
});

describe("rendererKey — structure IS structure", () => {
  it("changes when a splat file changes", () => {
    expect(rendererKey({ splats: [splat({ url: "other.spz" })] })).not.toBe(
      rendererKey({ splats: [splat()] }),
    );
  });

  it("changes when the set of splats changes", () => {
    expect(rendererKey({ splats: [splat(), splat({ url: "b.spz" })] })).not.toBe(
      rendererKey({ splats: [splat()] }),
    );
  });

  it("changes when a clip volume appears or moves", () => {
    const bare = rendererKey({ splats: [splat()] });
    const clipped = rendererKey({
      splats: [
        splat({
          clip: {
            center_world: [1, 0.4, 2],
            half_extents_m: [0.9, 0.3, 1.1],
            yaw_rad: 0.4,
          },
        }),
      ],
    });
    expect(clipped).not.toBe(bare);
    const moved = rendererKey({
      splats: [
        splat({
          clip: {
            center_world: [1, 0.4, 2],
            half_extents_m: [0.9, 0.3, 1.1],
            yaw_rad: 1.2,
          },
        }),
      ],
    });
    expect(moved).not.toBe(clipped);
  });

  it("changes when the shell arrives or its material is re-baked", () => {
    const none = rendererKey({ splats: [splat()] });
    const withShell = rendererKey({ splats: [splat()], shell: [plane()] });
    expect(withShell).not.toBe(none);
    const rebaked = rendererKey({
      splats: [splat()],
      shell: [{ ...plane(), material: { albedo_hex: "#aab9c3", roughness: 0.9, family: null } }],
    });
    expect(rebaked).not.toBe(withShell);
  });

});

// The renderer key used to carry these too, on the reasoning that they are
// "cheap to rebuild and rare to change" (decision 0188). Both halves were
// wrong in the way that matters: the key is GLOBAL, so what it costs is
// never the keyed object but everything else in the scene — and an outline
// is not rare at all, it appears on the first proposal of a session. The
// pair of expectations below is the guard, and it has to be a pair: an
// outline that changes NEITHER key would satisfy the first assertion by
// simply never being drawn.
describe("rendererKey — decorations are not structure", () => {
  const outline: MeasuredOutline = {
    center_world: [1, 0.4, 2],
    half_extents_m: [0.9, 0.3, 1.1],
    yaw_rad: 0.4,
  };
  const badge: ViewerLabel = { kind: "box", text: "1", position: [0, 1, 0] };

  // That the renderer key cannot CHANGE with an outline is held by the type
  // system, not by an assertion: `ViewerKeyInput` has no such field, so
  // putting one back is a deliberate edit rather than an accident. What a
  // test can hold is the other half — that leaving the renderer alone did
  // not simply stop drawing them.
  it("gives an outline its own key, which is not a constant", () => {
    expect(outlinesKey([outline])).not.toBe(outlinesKey(null));
    expect(outlinesKey([outline, outline])).not.toBe(outlinesKey([outline]));
    // Absent and empty mean the same thing: nothing to draw.
    expect(outlinesKey([])).toBe(outlinesKey(null));
  });

  it("gives walk badges their own key, which is not a constant", () => {
    expect(labelsKey([badge])).not.toBe(labelsKey(null));
    expect(labelsKey([])).toBe(labelsKey(null));
  });

  it("rebuilds an outline that moved, resized or turned", () => {
    const base = outlinesKey([outline]);
    expect(outlinesKey([{ ...outline, center_world: [2, 0.4, 2] }])).not.toBe(base);
    // Half-extents were absent from the old key, so an outline that changed
    // only its size silently kept the shape it was first drawn with.
    expect(outlinesKey([{ ...outline, half_extents_m: [1.4, 0.3, 1.1] }])).not.toBe(
      base,
    );
    expect(outlinesKey([{ ...outline, yaw_rad: 1.2 }])).not.toBe(base);
  });

  it("rebuilds a badge that changed text, place or kind", () => {
    const base = labelsKey([badge]);
    expect(labelsKey([{ ...badge, text: "2" }])).not.toBe(base);
    expect(labelsKey([{ ...badge, position: [0, 2, 0] }])).not.toBe(base);
    expect(labelsKey([{ ...badge, kind: "wall" }])).not.toBe(base);
  });

  it("is unchanged by an equal-but-fresh array", () => {
    expect(outlinesKey([{ ...outline }])).toBe(outlinesKey([outline]));
    expect(labelsKey([{ ...badge }])).toBe(labelsKey([badge]));
  });
});
