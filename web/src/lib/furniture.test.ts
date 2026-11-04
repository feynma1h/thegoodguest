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

describe("parseFurniture emitters", () => {
  const withParts = (parts: unknown[]) => {
    const t = twin();
    return bundle([{ ...t, spec: { ...t.spec, parts } }]);
  };
  const emits = (raw: unknown) =>
    parseFurniture(raw)!.objects[0].spec.parts.map((p) => p.emits);

  it("keeps a part's emits property, on any part", () => {
    const got = emits(withParts([
      { kind: "sphere", r: 0.1, mat: "wood", name: "bulb", emits: true },
      { kind: "sphere", r: 0.1, mat: "wood", name: "ball" },
    ]));
    expect(got).toEqual([true, undefined]);
  });

  it("reads a part named lamp-shade as an emitter, as twins written before the property do", () => {
    expect(emits(withParts([{ kind: "cyl", r: 0.1, h: 0.1, mat: "wood", name: "lamp-shade" }]))).toEqual([true]);
  });

  it("lets a part named lamp-shade opt out", () => {
    expect(emits(withParts([{ kind: "cyl", r: 0.1, h: 0.1, mat: "wood", name: "lamp-shade", emits: false }]))).toEqual([false]);
  });
});
