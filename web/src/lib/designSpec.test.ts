import { describe, expect, it } from "vitest";

import type {
  DesignSpecDoc,
  FusedObject,
  PositionedSplat,
  SceneManifest,
  SpecEntry,
} from "@/lib/api/types";
import {
  applyDesignSpec,
  arrangementNote,
  orphanNote,
  specKey,
} from "@/lib/designSpec";

const obj = (
  id: string,
  ident: string | null,
  pos: [number, number, number],
  over: Partial<FusedObject> = {},
): FusedObject =>
  ({
    object_id: id,
    label: id.replace(/_\d+$/, ""),
    placed: true,
    method: "depth_fit",
    splat_gcs_uri: `gs://o/${id}.ply`,
    world_transform: { position: pos, rotation_xyzw: [0, 0, 0, 1], scale: 1 },
    ...(ident ? { roomplan_box: { identifier: ident } } : {}),
    ...over,
  }) as FusedObject;

const manifest = (objects: FusedObject[]): SceneManifest => ({
  scene_id: "s1",
  manifest_version: 2,
  objects,
});

const splat = (label: string, pos: [number, number, number]): PositionedSplat => ({
  url: `https://x/${label}.spz`,
  label,
  position: pos,
  rotation_xyzw: [0, 0, 0, 1],
  scale: 1,
});

const entry = (over: Partial<SpecEntry> = {}): SpecEntry => ({
  key: "box:IDENT-BED",
  action: "move",
  label: "bed",
  measured_transform: {
    position: [1, 0.5, 2],
    rotation_xyzw: [0, 0, 0, 1],
    scale: 1,
  },
  proposed_transform: {
    position: [3, 0.5, 0.5],
    rotation_xyzw: [0, 0, 0, 1],
    scale: 1,
  },
  measured_footprint: {
    center_world: [1, 0.5, 2],
    half_extents_m: [0.9, 0.3, 1.1],
    yaw_rad: 0.4,
  },
  solver: {
    relation: "against_wall",
    anchor_resolved_to: "wall_00",
    constraints_applied: ["keeps_height"],
    reasoning: "because",
  },
  description: "the bed is against the wall",
  origin: { turn_index: 0, client_msg_id: "c1" },
  orphaned: false,
  ...over,
});

const doc = (entries: SpecEntry[]): DesignSpecDoc => ({
  spec_version: 1,
  scene_id: "s1",
  entries,
  updated_at: "2026-08-09T00:00:00+00:00",
});

const ROOM = {
  manifest: manifest([
    obj("bed_0", "IDENT-BED", [1, 0.5, 2]),
    obj("chair_0", "IDENT-CHAIR", [3, 0.5, 3]),
    obj("mirror_0", null, [0, 1.2, 1]),
  ]),
  splats: [splat("bed", [1, 0.5, 2]), splat("chair", [3, 0.5, 3]),
           splat("mirror", [0, 1.2, 1])],
};

describe("specKey — the same rule the server writes", () => {
  it("prefers the box identifier and namespaces the fallback", () => {
    expect(specKey({ object_id: "obj_003", roomplan_box: { identifier: "D22" } }))
      .toBe("box:D22");
    expect(specKey({ object_id: "obj_021" })).toBe("obj:obj_021");
    expect(specKey({ object_id: "obj_021", roomplan_box: null })).toBe("obj:obj_021");
  });
});

describe("applyDesignSpec", () => {
  it("returns the measured room untouched when there is no spec", () => {
    for (const spec of [null, doc([])]) {
      const out = applyDesignSpec(ROOM.splats, ROOM.manifest, spec);
      expect(out.splats).toBe(ROOM.splats);
      expect(out.states).toEqual(["measured", "measured", "measured"]);
      expect(out.outlines).toEqual([]);
      expect(out.applied).toEqual([]);
    }
  });

  it("moves the piece the entry names and nothing else", () => {
    const out = applyDesignSpec(ROOM.splats, ROOM.manifest, doc([entry()]));
    expect(out.splats[0].position).toEqual([3, 0.5, 0.5]);
    expect(out.splats[1]).toBe(ROOM.splats[1]);
    expect(out.splats[2]).toBe(ROOM.splats[2]);
    expect(out.states).toEqual(["moved", "measured", "measured"]);
  });

  it("joins on the KEY, not on the label — two chairs share a label", () => {
    const twoChairs = {
      manifest: manifest([
        obj("chair_0", "IDENT-A", [1, 0.5, 1]),
        obj("chair_1", "IDENT-B", [3, 0.5, 3]),
      ]),
      splats: [splat("chair", [1, 0.5, 1]), splat("chair", [3, 0.5, 3])],
    };
    const out = applyDesignSpec(
      twoChairs.splats, twoChairs.manifest,
      doc([entry({ key: "box:IDENT-B", label: "second chair" })]),
    );
    expect(out.states).toEqual(["measured", "moved"]);
    expect(out.splats[0].position).toEqual([1, 0.5, 1]);
  });

  it("keys an object with no RoomPlan box on its object_id", () => {
    const out = applyDesignSpec(
      ROOM.splats, ROOM.manifest,
      doc([entry({ key: "obj:mirror_0", label: "mirror" })]),
    );
    expect(out.states).toEqual(["measured", "measured", "moved"]);
  });

  it("HIDES a removal rather than dropping it — undo must stay cheap", () => {
    // Dropping the splat would change SplatViewer's structural key and
    // unmount the mesh, which decision 0130 measured as a full re-download.
    const out = applyDesignSpec(
      ROOM.splats, ROOM.manifest,
      doc([entry({ action: "remove", proposed_transform: null })]),
    );
    expect(out.splats).toHaveLength(3);
    expect(out.splats[0].hidden).toBe(true);
    expect(out.splats[0].position).toEqual([1, 0.5, 2]);
    expect(out.states[0]).toBe("removed");
  });

  it("leaves the measurement on the floor for every applied entry", () => {
    const out = applyDesignSpec(ROOM.splats, ROOM.manifest, doc([entry()]));
    expect(out.outlines).toEqual([entry().measured_footprint]);
  });

  it("draws no outline for an entry that carries no measured footprint", () => {
    const out = applyDesignSpec(
      ROOM.splats, ROOM.manifest,
      doc([entry({ measured_footprint: null })]),
    );
    expect(out.splats[0].position).toEqual([3, 0.5, 0.5]);
    expect(out.outlines).toEqual([]);
  });

  it("never applies an orphaned entry, and reports it", () => {
    const gone = entry({ key: "box:IDENT-GONE", orphaned: true });
    const out = applyDesignSpec(ROOM.splats, ROOM.manifest, doc([entry(), gone]));
    expect(out.applied).toHaveLength(1);
    expect(out.orphaned).toEqual([gone]);
    expect(out.outlines).toHaveLength(1);
  });

  it("ignores an entry for a piece that is not rendered", () => {
    const withUnplaced = manifest([
      obj("bed_0", "IDENT-BED", [1, 0.5, 2]),
      obj("door_0", "IDENT-DOOR", [0, 0, 0], { placed: false }),
    ]);
    const out = applyDesignSpec(
      [splat("bed", [1, 0.5, 2])], withUnplaced,
      doc([entry({ key: "box:IDENT-DOOR", label: "door" })]),
    );
    expect(out.splats[0].position).toEqual([1, 0.5, 2]);
    expect(out.applied).toEqual([]);
  });

  it("preserves a per-axis scale — a proposal never rescales anything", () => {
    const stretched: PositionedSplat[] = [
      { ...splat("bed", [1, 0.5, 2]), scale: [1, 1.4, 1] },
    ];
    const out = applyDesignSpec(
      stretched, manifest([obj("bed_0", "IDENT-BED", [1, 0.5, 2])]),
      doc([entry()]),
    );
    expect(out.splats[0].scale).toEqual([1, 1.4, 1]);
  });

  it("does not mutate its inputs", () => {
    const before = JSON.stringify(ROOM.splats);
    applyDesignSpec(ROOM.splats, ROOM.manifest, doc([entry()]));
    expect(JSON.stringify(ROOM.splats)).toBe(before);
  });

  it("survives a malformed move entry rather than rendering it half-applied", () => {
    const out = applyDesignSpec(
      ROOM.splats, ROOM.manifest,
      doc([entry({ proposed_transform: null })]),
    );
    expect(out.splats[0]).toBe(ROOM.splats[0]);
    expect(out.states[0]).toBe("measured");
  });
});

describe("the chrome's copy", () => {
  it("counts rather than listing, and always names the way back", () => {
    expect(arrangementNote([])).toBeNull();
    expect(arrangementNote([entry()])).toBe(
      "1 piece moved — the measured room is one step away",
    );
    expect(arrangementNote([entry(), entry({ key: "b" })])).toBe(
      "2 pieces moved — the measured room is one step away",
    );
    expect(
      arrangementNote([entry(), entry({ key: "b", action: "remove" })]),
    ).toBe("1 piece moved, 1 taken out — the measured room is one step away");
  });

  it("says plainly that an orphaned change is not being shown", () => {
    expect(orphanNote([])).toBeNull();
    const one = orphanNote([entry({ orphaned: true })]);
    expect(one).toContain("the bed");
    expect(one).toContain("not being shown");
    expect(one).toContain("reprocessed");
    const many = orphanNote([
      entry({ orphaned: true }),
      entry({ key: "b", label: "chair", orphaned: true }),
    ]);
    expect(many).toContain("bed, chair");
    expect(many).toContain("are not being shown");
  });
});
