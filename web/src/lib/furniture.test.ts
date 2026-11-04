import { describe, expect, it } from "vitest";

import { parseFurniture } from "@/lib/furniture";

const twin = (over: Record<string, unknown> = {}) => ({
  key: "side-table",
  position: [1, 0, 1],
  yaw: 0,
  source: "boxes",
  category: "table",
  rule: "floor",
  spec: {
    key: "side-table",
    label: "side table",
    box_dims: [0.45, 0.55, 0.4],
    materials: { wood: { color: "#b98b5e" } },
    parts: [{ kind: "box", mat: "wood", size: [0.45, 0.04, 0.4], at: [0, 0.53, 0] }],
  },
  ...over,
});

const bundle = (objects: unknown[], extra: Record<string, unknown> = {}) => ({
  furniture_version: 1,
  scene_id: null,
  objects,
  ...extra,
});

describe("parseFurniture", () => {
  it("accepts a bundle the build tool writes", () => {
    const b = parseFurniture(bundle([twin()]));
    expect(b?.objects).toHaveLength(1);
    expect(b?.objects[0].spec.parts).toHaveLength(1);
  });

  it("accepts an empty bundle", () => {
    expect(parseFurniture(bundle([]))?.objects).toEqual([]);
  });

  it("refuses anything that is not a version-1 bundle", () => {
    expect(parseFurniture(null)).toBeNull();
    expect(parseFurniture("furniture")).toBeNull();
    expect(parseFurniture({ ...bundle([twin()]), furniture_version: 2 })).toBeNull();
    expect(parseFurniture({ furniture_version: 1, objects: "no" })).toBeNull();
  });

  it("refuses a twin without a placement or without parts", () => {
    expect(parseFurniture(bundle([twin({ position: "here" })]))).toBeNull();
    expect(parseFurniture(bundle([twin({ yaw: "0" })]))).toBeNull();
    expect(parseFurniture(bundle([twin({ spec: { key: "x", parts: [], materials: 3 } })]))).toBeNull();
    expect(parseFurniture(bundle([null]))).toBeNull();
  });
});
