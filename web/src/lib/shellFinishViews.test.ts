import { describe, expect, it } from "vitest";

import { doorPosition, frameRoom, hiddenPieces, ISO_ELEVATION_RAD, openAtDoor, openCorner, planViews, shortestTurn, stepOrder, type WorldBox } from "./shellFinishViews";
import type { CutawayWall } from "./shellFinish";
import type { Vec3 } from "./shell3d";

// A 4 x 3 m room (see shellFinish.test): walls wound to front the interior.
const walls = (): CutawayWall[] => [
  { corners: [[0, 0, 0], [4, 0, 0], [4, 2, 0], [0, 2, 0]], openings: [] },
  { corners: [[4, 0, 0], [4, 0, 3], [4, 2, 3], [4, 2, 0]], openings: [{ classification: "window" }] },
  { corners: [[4, 0, 3], [0, 0, 3], [0, 2, 3], [4, 2, 3]], openings: [] },
  { corners: [[0, 0, 3], [0, 0, 0], [0, 2, 0], [0, 2, 3]], openings: [] },
];

describe("planViews", () => {
  it("offers one view per corner, best first, at the isometric elevation", () => {
    const v = planViews(walls());
    expect(v).toHaveLength(4);
    expect(v[0].keep.includes(1)).toBe(true); // the window corner leads
    expect(v.every((x) => x.elevation === ISO_ELEVATION_RAD)).toBe(true);
    expect(v[0].score).toBeGreaterThanOrEqual(v[3].score);
  });
  it("steps around the room in azimuth order starting from the best", () => {
    const v = stepOrder(planViews(walls()));
    expect(v[0]).toEqual(planViews(walls())[0]);
    const turns = v.slice(1).map((x) => ((x.azimuth - v[0].azimuth) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI));
    expect([...turns].sort((a, b) => a - b)).toEqual(turns);
  });
  it("prefers the side that does not hide the bed behind a cupboard", () => {
    // Tall cupboard near x=3.5, bed behind it from the +x side.
    const boxes: WorldBox[] = [
      { center: [3.2, 1, 2.4], half: [0.35, 1, 0.35], yaw: 0 },
      { center: [2.7, 0.3, 1.9], half: [0.4, 0.3, 0.4], yaw: 0 },
    ];
    const views = planViews(walls(), boxes);
    expect(views.some((v) => v.hidden > 0)).toBe(true);
    // The leading view is never worse on hidden pieces than a view that hides one.
    expect(views[0].hidden).toBe(Math.min(...views.map((v) => v.hidden)));
  });
});

describe("hiddenPieces", () => {
  it("flags a short piece covered by a closer taller one, not the reverse", () => {
    const tall: WorldBox = { center: [0, 1, 2], half: [0.6, 1, 0.3], yaw: 0 };
    const low: WorldBox = { center: [0, 0.3, 1.2], half: [0.4, 0.3, 0.3], yaw: 0 };
    // Camera on +Z looking toward -Z: tall is closer.
    expect(hiddenPieces([tall, low], 0, 0.6)).toEqual([1]);
    expect(hiddenPieces([tall, low], Math.PI, 0.6)).toEqual([]);
  });
});

describe("framing", () => {
  it("centres on the floor and stands back by the lens", () => {
    const floor: Vec3[] = [[0, 0, 0], [4, 0, 0], [4, 0, 3], [0, 0, 3]];
    const f = frameRoom(floor, 2, 22);
    expect(f.target[0]).toBeCloseTo(2);
    expect(f.target[2]).toBeCloseTo(1.5);
    expect(f.distance).toBeGreaterThan(f.radius * 4);
  });
  it("turns the short way round", () => {
    expect(shortestTurn(3, -3)).toBeCloseTo(2 * Math.PI - 6);
  });
});

describe("opening at the door", () => {
  // The 4 x 3 room again, with a door near the (4, 3) end of the z = 3 wall: u runs from corners[0] (4, 3)
  // toward corners[1] (0, 3), so u 0.05-0.25 is x 3.8-3.0.
  const withDoor = () => {
    const w = walls();
    w[2] = { ...w[2], openings: [{ classification: "door", rect_uv: [[0.05, 0], [0.25, 0.7]] }] };
    return w;
  };
  it("finds the door's floor position", () => {
    const [x, z] = doorPosition(withDoor())!;
    expect(x).toBeCloseTo(3.4);
    expect(z).toBeCloseTo(3);
  });
  it("opens the room at the corner nearest the door", () => {
    const ws = withDoor();
    const first = openAtDoor(planViews(ws), ws)[0];
    const [cx, cz] = openCorner(first.keep, ws)!;
    expect(Math.hypot(cx - 3.4, cz - 3)).toBeLessThan(1);
  });
  it("leaves the order alone when there is no door", () => {
    const v = planViews(walls());
    expect(openAtDoor(v, walls())).toEqual(v);
  });
});
