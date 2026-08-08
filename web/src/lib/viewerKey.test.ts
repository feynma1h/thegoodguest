import { describe, expect, it } from "vitest";

import type { PositionedSplat, ShellPlane } from "@/lib/api/types";
import { rendererKey } from "@/lib/viewerKey";

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

  it("changes when walk badges or measured outlines change", () => {
    const bare = rendererKey({ splats: [splat()] });
    expect(
      rendererKey({
        splats: [splat()],
        labels: [{ kind: "box", text: "1", position: [0, 1, 0] }],
      }),
    ).not.toBe(bare);
    expect(
      rendererKey({
        splats: [splat()],
        outlines: [
          {
            center_world: [1, 0.4, 2],
            half_extents_m: [0.9, 0.3, 1.1],
            yaw_rad: 0.4,
          },
        ],
      }),
    ).not.toBe(bare);
  });
});
