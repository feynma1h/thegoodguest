import { describe, expect, it } from "vitest";

import type { ShellPlane } from "@/lib/api/types";
import {
  CAPTION_DWELL_MS,
  DONE_BEAT_MS,
  NAMED_ALL_UNDER,
  NAMED_MAX,
  SETTLE_MS,
  contourGeometry,
  namedCount,
  pathLengths,
  pathPointAt,
  planReveal,
  revealHoldMs,
  settleEase,
  splatSize,
  wallSweepOrder,
  windowProgress,
  type ObjectCue,
  type Vec3,
} from "@/lib/reveal";

/* --------------------------------------------------------------- *
 * Fixtures: a 4x3 m room, floor + 4 walls, wound counter-clockwise.
 * --------------------------------------------------------------- */

const FLOOR_CORNERS: Vec3[] = [
  [0, 0, 0],
  [4, 0, 0],
  [4, 0, 3],
  [0, 0, 3],
];

function plane(kind: ShellPlane["kind"], corners: Vec3[]): ShellPlane {
  return {
    kind,
    corners,
    openings: [],
    confidence: null,
    material: { albedo_hex: "#c8c1b7", roughness: 0.8, family: null },
  };
}

/** Wall spanning two floor corners, 2.5 m tall. */
function wall(a: Vec3, b: Vec3): ShellPlane {
  return plane("wall", [a, b, [b[0], 2.5, b[2]], [a[0], 2.5, a[2]]]);
}

const ROOM: ShellPlane[] = [
  plane("floor", FLOOR_CORNERS),
  wall(FLOOR_CORNERS[0], FLOOR_CORNERS[1]), // south
  wall(FLOOR_CORNERS[1], FLOOR_CORNERS[2]), // east
  wall(FLOOR_CORNERS[2], FLOOR_CORNERS[3]), // north
  wall(FLOOR_CORNERS[3], FLOOR_CORNERS[0]), // west
];

const splats = (...sizes: number[]) => sizes.map((scale) => ({ scale }));

/* --------------------------------------------------------------- *
 * The motion vocabulary
 * --------------------------------------------------------------- */

describe("settleEase", () => {
  it("spans exactly 0 to 1", () => {
    expect(settleEase(0)).toBe(0);
    expect(settleEase(1)).toBe(1);
    expect(settleEase(0.5)).toBeCloseTo(0.5, 12);
  });

  it("clamps outside the unit interval", () => {
    expect(settleEase(-3)).toBe(0);
    expect(settleEase(4)).toBe(1);
  });

  // THE operator finding from RP-8 (decision 0080): the old curve
  // (1-(1-t)^3) starts at maximum velocity — "comes down at high speed
  // then slows". A settle must begin at rest and arrive at rest.
  it("begins and ends at rest — the RP-8 note, pinned", () => {
    const h = 1e-5;
    const vStart = (settleEase(h) - settleEase(0)) / h;
    const vEnd = (settleEase(1) - settleEase(1 - h)) / h;
    expect(vStart).toBeLessThan(1e-4);
    expect(vEnd).toBeLessThan(1e-4);

    const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);
    const oldVStart = (easeOutCubic(h) - easeOutCubic(0)) / h;
    expect(oldVStart).toBeGreaterThan(2.9); // what we are moving away from
  });

  it("never reverses (monotone)", () => {
    let prev = -Infinity;
    for (let t = 0; t <= 1; t += 0.01) {
      const v = settleEase(t);
      expect(v).toBeGreaterThanOrEqual(prev);
      prev = v;
    }
  });
});

describe("windowProgress", () => {
  it("clamps before, ramps within, saturates after", () => {
    expect(windowProgress(100, 200, 400)).toBe(0);
    expect(windowProgress(400, 200, 400)).toBeCloseTo(0.5, 12);
    expect(windowProgress(900, 200, 400)).toBe(1);
  });

  it("treats a zero-length window as already done", () => {
    expect(windowProgress(200, 200, 0)).toBe(1);
    expect(windowProgress(199, 200, 0)).toBe(0);
  });
});

/* --------------------------------------------------------------- *
 * Path math (the pen)
 * --------------------------------------------------------------- */

describe("path math", () => {
  it("accumulates arc length along the polyline", () => {
    expect(pathLengths([[0, 0, 0], [3, 0, 0], [3, 0, 4]])).toEqual([0, 3, 7]);
  });

  it("finds an exact fractional point on a segment", () => {
    const path: Vec3[] = [[0, 0, 0], [4, 0, 0], [4, 0, 3]];
    const lengths = pathLengths(path);
    expect(pathPointAt(path, lengths, 2).point).toEqual([2, 0, 0]);
    expect(pathPointAt(path, lengths, 2).segment).toBe(0);
    expect(pathPointAt(path, lengths, 5.5).point).toEqual([4, 0, 1.5]);
    expect(pathPointAt(path, lengths, 5.5).segment).toBe(1);
  });

  it("clamps at both ends rather than extrapolating", () => {
    const path: Vec3[] = [[0, 0, 0], [4, 0, 0]];
    const lengths = pathLengths(path);
    expect(pathPointAt(path, lengths, -10).point).toEqual([0, 0, 0]);
    expect(pathPointAt(path, lengths, 99).point).toEqual([4, 0, 0]);
  });

  it("survives degenerate paths without dividing by zero", () => {
    expect(pathPointAt([], [0], 1).point).toEqual([0, 0, 0]);
    const dup: Vec3[] = [[1, 2, 3], [1, 2, 3]];
    expect(pathPointAt(dup, pathLengths(dup), 0.5).point).toEqual([1, 2, 3]);
  });
});

/* --------------------------------------------------------------- *
 * Contour geometry — the boundary that draws itself
 * --------------------------------------------------------------- */

describe("contourGeometry", () => {
  it("traces the measured floor perimeter, closed", () => {
    const c = contourGeometry(ROOM)!;
    expect(c.loop).toHaveLength(FLOOR_CORNERS.length + 1);
    expect(c.loop[0]).toEqual(c.loop[c.loop.length - 1]);
    expect(c.loop.slice(0, -1)).toEqual(FLOOR_CORNERS);
  });

  it("rises to the measured wall top and closes with a matching loop", () => {
    const c = contourGeometry(ROOM)!;
    expect(c.risers).toHaveLength(4);
    expect(c.risers.every((r) => r.to[1] === 2.5)).toBe(true);
    expect(c.risers.every((r) => r.from[1] === 0)).toBe(true);
    expect(c.topLoop!.every((p) => p[1] === 2.5)).toBe(true);
    // The top loop is the floor loop lifted — same footprint, no invention.
    expect(c.topLoop!.map((p) => [p[0], p[2]])).toEqual(
      c.loop.map((p) => [p[0], p[2]]),
    );
  });

  it("draws no verticals when no walls were measured", () => {
    const c = contourGeometry([plane("floor", FLOOR_CORNERS)])!;
    expect(c.risers).toEqual([]);
    expect(c.topLoop).toBeNull();
    expect(c.loop).toHaveLength(5);
  });

  it("reports the floor's winding both ways", () => {
    expect(contourGeometry(ROOM)!.winding).toBe(1);
    const reversed = [
      plane("floor", [...FLOOR_CORNERS].reverse()),
      ...ROOM.slice(1),
    ];
    expect(contourGeometry(reversed)!.winding).toBe(-1);
  });

  // Nothing is invented: with no measured floor there is no boundary.
  it("returns null with no floor polygon", () => {
    expect(contourGeometry(ROOM.slice(1))).toBeNull();
    expect(contourGeometry([])).toBeNull();
    expect(contourGeometry([plane("floor", [[0, 0, 0], [1, 0, 0]])])).toBeNull();
  });
});

/* --------------------------------------------------------------- *
 * The sweep
 * --------------------------------------------------------------- */

describe("wallSweepOrder", () => {
  it("sweeps one lap in the contour's own direction, from the pen's corner", () => {
    const order = wallSweepOrder(ROOM, contourGeometry(ROOM));
    expect(order).toHaveLength(4);
    expect(new Set(order)).toEqual(new Set([1, 2, 3, 4]));
    // South wall's midpoint sits at the start angle; the lap runs
    // counter-clockwise from there: south, east, north, west.
    expect(order).toEqual([1, 2, 3, 4]);
  });

  it("reverses with the floor's winding", () => {
    const reversed = [
      plane("floor", [...FLOOR_CORNERS].reverse()),
      ...ROOM.slice(1),
    ];
    const order = wallSweepOrder(reversed, contourGeometry(reversed));
    expect(order[0]).toBe(3); // starts at the pen's new first corner
    expect(new Set(order)).toEqual(new Set([1, 2, 3, 4]));
  });

  it("falls back to array order with no contour, and skips non-walls", () => {
    const walls = ROOM.slice(1);
    expect(wallSweepOrder(walls, null)).toEqual([0, 1, 2, 3]);
    expect(wallSweepOrder(ROOM, null)).toEqual([1, 2, 3, 4]);
  });
});

/* --------------------------------------------------------------- *
 * Naming: introductions, then a wave
 * --------------------------------------------------------------- */

describe("namedCount", () => {
  it("names every piece in a small room", () => {
    for (let n = 0; n < NAMED_ALL_UNDER; n++) expect(namedCount(n)).toBe(n);
  });

  it("introduces a few, then lets the rest flow", () => {
    expect(namedCount(NAMED_ALL_UNDER)).toBe(NAMED_MAX);
    expect(namedCount(25)).toBe(NAMED_MAX);
  });
});

describe("splatSize", () => {
  it("reads uniform scale, and the largest axis of the A/B variant", () => {
    expect(splatSize(1.4)).toBe(1.4);
    expect(splatSize([0.3, 2.1, 0.9])).toBe(2.1);
  });
});

/* --------------------------------------------------------------- *
 * The plan
 * --------------------------------------------------------------- */

describe("planReveal", () => {
  const plan = planReveal({ shell: ROOM, splats: splats(2, 1.5, 1, 0.8, 0.5, 0.4, 0.3) });

  it("orders the four movements: outline, surfaces, pieces, quiet", () => {
    const floorCue = plan.surfaces.find((s) => s.index === 0)!;
    const firstObject = plan.objects[0];
    expect(plan.contour!.startMs).toBeLessThan(floorCue.startMs);
    expect(floorCue.startMs).toBeLessThan(firstObject.startMs);
    expect(plan.doneMs).toBeGreaterThan(
      firstObject.startMs + firstObject.durationMs,
    );
  });

  it("materializes the floor before any wall", () => {
    const floorCue = plan.surfaces.find((s) => s.index === 0)!;
    const walls = plan.surfaces.filter((s) => s.index !== 0);
    expect(walls).toHaveLength(4);
    for (const w of walls) expect(w.startMs).toBeGreaterThan(floorCue.startMs);
  });

  it("sweeps the walls one step apart, in sweep order", () => {
    const walls = plan.surfaces.filter((s) => s.index !== 0);
    const starts = walls.map((w) => w.startMs);
    expect([...starts].sort((a, b) => a - b)).toEqual(starts);
    expect(walls.map((w) => w.index)).toEqual([1, 2, 3, 4]);
  });

  // Keeps splat/mesh compositing in the configuration decision 0066's
  // depth probe proved: no object fades against a half-transparent wall.
  it("starts no object until every surface has finished materializing", () => {
    const surfacesEnd = Math.max(
      ...plan.surfaces.map((s) => s.startMs + s.durationMs),
    );
    for (const o of plan.objects) expect(o.startMs).toBeGreaterThan(surfacesEnd);
  });

  it("arrives largest piece first", () => {
    expect(plan.objects.map((o) => o.seq)).toEqual([0, 1, 2, 3, 4, 5, 6]);
    expect(plan.objects.map((o) => o.index)).toEqual([0, 1, 2, 3, 4, 5, 6]);
    const unsorted = planReveal({
      shell: [],
      splats: splats(0.2, 3, 1),
    });
    expect(unsorted.objects.map((o) => o.index)).toEqual([1, 2, 0]);
  });

  it("introduces the first pieces slowly, then quickens into a wave", () => {
    const named = plan.objects.filter((o) => o.named);
    expect(named).toHaveLength(NAMED_MAX);
    expect(named.map((o) => o.seq)).toEqual([0, 1, 2]);

    const gaps = plan.objects
      .slice(1)
      .map((o, i) => o.startMs - plan.objects[i].startMs);
    const introGaps = gaps.slice(0, NAMED_MAX - 1);
    const waveGaps = gaps.slice(NAMED_MAX);
    expect(new Set(introGaps).size).toBe(1);
    expect(new Set(waveGaps).size).toBe(1);
    expect(waveGaps[0]).toBeLessThan(introGaps[0] / 2);
  });

  it("keeps the last name up for its dwell, then clears before the room speaks", () => {
    const lastNamed = plan.objects.filter((o) => o.named).at(-1)!;
    expect(plan.captionsDoneMs).toBe(lastNamed.startMs + CAPTION_DWELL_MS);
    expect(plan.captionsDoneMs).toBeLessThan(plan.doneMs);
  });

  it("leaves a beat of quiet after the last motion", () => {
    const lastMotion = Math.max(
      ...plan.objects.map((o) => o.startMs + o.durationMs),
    );
    expect(plan.doneMs).toBe(lastMotion + DONE_BEAT_MS);
  });

  it("finishes a big real room inside a watchable window", () => {
    // The spike room's shape: 13 walls, 25 pieces. The pre-redesign
    // schedule ran ~22.8 s; the wave is what buys it back.
    const big = planReveal({
      shell: [
        plane("floor", FLOOR_CORNERS),
        ...Array.from({ length: 13 }, () =>
          wall(FLOOR_CORNERS[0], FLOOR_CORNERS[1]),
        ),
      ],
      splats: splats(...Array.from({ length: 25 }, (_, i) => 25 - i)),
    });
    expect(big.doneMs).toBeLessThan(13_000);
    expect(big.objects.filter((o) => o.named)).toHaveLength(NAMED_MAX);
  });

  it("skips the stage build when there is no shell", () => {
    const p = planReveal({ shell: [], splats: splats(1, 2) });
    expect(p.contour).toBeNull();
    expect(p.surfaces).toEqual([]);
    expect(p.objects[0].startMs).toBeLessThan(600);
    expect(p.immediate).toBe(false);
  });

  it("still builds the stage when a room has walls but no measured floor", () => {
    const p = planReveal({ shell: ROOM.slice(1), splats: splats(1) });
    expect(p.contour).toBeNull();
    expect(p.surfaces).toHaveLength(4);
    expect(p.objects[0].startMs).toBeGreaterThan(
      Math.max(...p.surfaces.map((s) => s.startMs + s.durationMs)),
    );
  });

  // A wall with no corners is dropped by the sweep (nothing to sort by);
  // it must still get a cue, or the plane would silently never appear.
  it("gives a cornerless wall a cue rather than dropping it", () => {
    const p = planReveal({
      shell: [...ROOM, plane("wall", [])],
      splats: [],
    });
    expect(p.surfaces.map((s) => s.index).sort((a, b) => a - b)).toEqual([
      0, 1, 2, 3, 4, 5,
    ]);
  });

  // Reduced motion must stay honest: nothing pretends to materialize, and
  // no caption fires.
  it("collapses to the finished room under reduced motion", () => {
    const p = planReveal({ shell: ROOM, splats: splats(1, 2, 3), reducedMotion: true });
    expect(p.immediate).toBe(true);
    expect(p.contour).toBeNull();
    expect(p.doneMs).toBe(0);
    expect(p.captionsDoneMs).toBe(0);
    expect(p.surfaces.every((s) => s.startMs === 0 && s.durationMs === 0)).toBe(true);
    expect(p.objects.every((o) => o.startMs === 0 && o.durationMs === 0)).toBe(true);
    expect(p.objects.every((o) => !o.named)).toBe(true);
    // Every surface and every piece is still addressed — nothing is lost.
    expect(p.surfaces).toHaveLength(ROOM.length);
    expect(p.objects).toHaveLength(3);
  });

  it("is immediate when there is nothing at all to play", () => {
    const p = planReveal({ shell: [], splats: [] });
    expect(p.immediate).toBe(true);
    expect(p.doneMs).toBe(0);
  });

  it("plays a lone piece without a wave", () => {
    const p = planReveal({ shell: [], splats: splats(1) });
    expect(p.objects).toHaveLength(1);
    expect(p.objects[0].named).toBe(true);
    expect(p.doneMs).toBe(p.objects[0].startMs + SETTLE_MS + DONE_BEAT_MS);
  });

  it("assigns every plane and every piece exactly one cue", () => {
    expect(plan.surfaces.map((s) => s.index).sort((a, b) => a - b)).toEqual([
      0, 1, 2, 3, 4,
    ]);
    expect(plan.objects.map((o) => o.index).sort((a, b) => a - b)).toEqual([
      0, 1, 2, 3, 4, 5, 6,
    ]);
  });
});

describe("revealHoldMs — the wave stretches for bytes (decision 0127)", () => {
  const cues = (n: number, step = 100): ObjectCue[] =>
    Array.from({ length: n }, (_, i) => ({
      index: i,
      seq: i,
      startMs: 1000 + i * step,
      durationMs: 900,
      named: i < 3,
    }));

  const all = () => true;
  const none = () => false;

  it("does not hold when every piece has arrived", () => {
    expect(revealHoldMs({ objects: cues(4), isReady: all, t: 5000, delayMs: 0 })).toBe(0);
  });

  it("does not hold before the first cue is even due", () => {
    expect(revealHoldMs({ objects: cues(4), isReady: none, t: 500, delayMs: 0 })).toBe(0);
  });

  it("holds from the moment a due piece is missing", () => {
    // cue 0 is due at 1000; at t=1300 it still has not landed.
    expect(revealHoldMs({ objects: cues(4), isReady: none, t: 1300, delayMs: 0 })).toBe(300);
  });

  it("starts a held cue exactly when it lands, not later", () => {
    // Held to 300 at t=1300; the piece arrives, so at t=1300 the effective
    // start (1000+300) is now — it begins on this very frame.
    const delay = revealHoldMs({ objects: cues(4), isReady: none, t: 1300, delayMs: 0 });
    expect(cues(4)[0].startMs + delay).toBe(1300);
  });

  it("holds the whole wave behind one late piece, preserving spacing", () => {
    // Piece 1 is missing; pieces 2..3 have arrived but must not overtake it.
    const ready = (i: number) => i !== 1;
    const delay = revealHoldMs({ objects: cues(4), isReady: ready, t: 2000, delayMs: 0 });
    expect(delay).toBe(2000 - 1100); // cue 1's own start, not cue 3's
    const starts = cues(4).map((c) => c.startMs + delay);
    expect(starts[2] - starts[1]).toBe(100); // spacing intact, no burst
  });

  it("never decreases — a fired cue cannot be un-fired", () => {
    const held = revealHoldMs({ objects: cues(4), isReady: all, t: 9000, delayMs: 700 });
    expect(held).toBe(700);
  });

  it("grows monotonically as a piece stays missing", () => {
    let d = 0;
    for (const t of [1100, 1400, 1900, 2600]) {
      const next = revealHoldMs({ objects: cues(4), isReady: none, t, delayMs: d });
      expect(next).toBeGreaterThanOrEqual(d);
      d = next;
    }
    expect(d).toBe(1600);
  });

  it("is inert on an empty object list (a shell-only room)", () => {
    expect(revealHoldMs({ objects: [], isReady: none, t: 9999, delayMs: 0 })).toBe(0);
  });

  it("walks by seq, not by array position", () => {
    const shuffled = [...cues(3)].reverse();
    const ready = (i: number) => i === 0;
    // seq 1 is the first missing one, so the hold is measured from ITS start.
    expect(revealHoldMs({ objects: shuffled, isReady: ready, t: 2000, delayMs: 0 })).toBe(
      2000 - 1100,
    );
  });
});
