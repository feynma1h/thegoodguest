import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";

import { MockApiClient, MOCK_READY_SCENE_ID, MOCK_V3_SCENE_ID } from "@/lib/api/mock";
import type { SceneAssets } from "@/lib/api/types";
import { roomTitle } from "@/lib/voice";
import { measureRoom, type RoomMeasure } from "./measure";
import { WORDMARK_ASPECT } from "@/components/wordmarkGeometry";
import { PALETTE } from "./palette";
import { CARD_FRAMES, CARD_SUBTITLE, formatM, layoutCard, type CardLayout, type CardVariant, type XY, DOMAIN } from "./layout";

function heroAssets(): SceneAssets {
  return JSON.parse(
    readFileSync(path.resolve(__dirname, "../../../public/hero/room.json"), "utf8"),
  ) as SceneAssets;
}

const TITLE = roomTitle("2026-08-21T09:00:00Z");

function heroCard(variant: CardVariant = "landscape") {
  const assets = heroAssets();
  const measure = measureRoom(assets.shell, assets.manifest)!;
  return { measure, layout: layoutCard({ measure, title: TITLE, variant }) };
}

function textOf(layout: CardLayout): string[] {
  return layout.ops.filter((o) => o.kind === "text").map((o) => o.text);
}

function pointsOf(layout: CardLayout): XY[] {
  const pts: XY[] = [];
  for (const op of layout.ops) {
    if (op.kind === "stroke" || op.kind === "fill") pts.push(...op.points);
    if (op.kind === "rect") pts.push(op.at, [op.at[0] + op.w, op.at[1] + op.h]);
    // The wordmark is 4.07x wider than it is tall.
    if (op.kind === "wordmark")
      pts.push(op.at, [op.at[0] + op.height * WORDMARK_ASPECT, op.at[1] + op.height]);
  }
  return pts;
}

/* ------------------------------------------------------------------ *
 * The measurement survives the projection
 * ------------------------------------------------------------------ */

describe("the card draws at one uniform scale", () => {
  it("reproduces every measured wall length at the stated px/m", () => {
    const { measure, layout } = heroCard();
    const s = layout.claims.scalePxPerM;
    expect(s).toBeGreaterThan(0);
    for (const wall of measure.walls) {
      const drawn = Math.hypot(
        (wall.b.x - wall.a.x) * s,
        (wall.b.z - wall.a.z) * s,
      );
      expect(drawn / wall.lengthM).toBeCloseTo(s, 9);
    }
  });

  it("puts the contour on the card at exactly that scale", () => {
    const { measure, layout } = heroCard();
    const s = layout.claims.scalePxPerM;
    // The floor fill is the contour; compare its edge lengths to the world.
    const fill = layout.ops.find((o) => o.kind === "fill")!;
    expect(fill.points).toHaveLength(measure.contour.length);
    for (let i = 0; i < measure.contour.length; i++) {
      const j = (i + 1) % measure.contour.length;
      const world = Math.hypot(
        measure.contour[j].x - measure.contour[i].x,
        measure.contour[j].z - measure.contour[i].z,
      );
      const card = Math.hypot(
        fill.points[j][0] - fill.points[i][0],
        fill.points[j][1] - fill.points[i][1],
      );
      expect(card / world).toBeCloseTo(s, 9);
    }
  });

  it("never scales an axis on its own", () => {
    // The definition of a similarity: EVERY pairwise distance carries the
    // same factor. Stronger than comparing bounding boxes, and it holds
    // under the plan's rotation, which a bounding-box test would not —
    // it catches per-axis scale, shear and skew alike.
    const { measure, layout } = heroCard();
    const s = layout.claims.scalePxPerM;
    const fill = layout.ops.find((o) => o.kind === "fill")!;
    for (let i = 0; i < measure.contour.length; i++) {
      for (let j = i + 1; j < measure.contour.length; j++) {
        const world = Math.hypot(
          measure.contour[j].x - measure.contour[i].x,
          measure.contour[j].z - measure.contour[i].z,
        );
        const card = Math.hypot(
          fill.points[j][0] - fill.points[i][0],
          fill.points[j][1] - fill.points[i][1],
        );
        expect(card / world).toBeCloseTo(s, 9);
      }
    }
  });

  it("lays the dimensioned wall flat, with its label the right way up", () => {
    // The plan is rotated so the datum wall is horizontal (a capture's
    // world yaw is the phone's heading at scan start, not a measurement).
    // Its consequence on the card is that the printed length never reads
    // bottom-to-top.
    for (const variant of ["landscape", "square"] as CardVariant[]) {
      const { layout } = heroCard(variant);
      const label = layout.ops.find(
        (o) => o.kind === "text" && o.text === layout.claims.datum!.text,
      );
      expect(label!.kind).toBe("text");
      expect((label as { rotateDeg: number }).rotateDeg).toBeCloseTo(0, 9);
    }
  });

  it("puts the dimension line below the room, never through it", () => {
    const { layout } = heroCard();
    const fill = layout.ops.find((o) => o.kind === "fill")!;
    const floorBottom = Math.max(...fill.points.map((p) => p[1]));
    const label = layout.ops.find(
      (o) => o.kind === "text" && o.text === layout.claims.datum!.text,
    ) as { at: XY };
    expect(label.at[1]).toBeGreaterThan(floorBottom);
  });
});

/* ------------------------------------------------------------------ *
 * Every number on the card is derived
 * ------------------------------------------------------------------ */

describe("the card types no numbers", () => {
  it("prints the dimension the measurement gives it", () => {
    const { measure, layout } = heroCard();
    expect(layout.claims.datum!.wallId).toBe(measure.datum!.wallId);
    expect(layout.claims.datum!.text).toBe(formatM(measure.datum!.lengthM));
    expect(textOf(layout)).toContain(formatM(measure.datum!.lengthM));
  });

  it("prints the ceiling and the floor area from the shell", () => {
    const { measure, layout } = heroCard();
    expect(layout.claims.ceilingText).toBe(formatM(measure.ceilingM!));
    expect(layout.claims.floorText).toBe(`${measure.floorAreaM2.toFixed(1)} m²`);
    expect(textOf(layout)).toContain("3.0 m");
    expect(textOf(layout)).toContain("10.7 m²");
  });

  it("keeps one decimal of meters and never more", () => {
    // scene_facts._format_m's rule: RoomPlan does not measure to the
    // centimetre, so a second decimal is a claim the scan cannot support.
    const { layout } = heroCard();
    for (const text of textOf(layout)) {
      expect(text).not.toMatch(/\d+\.\d\d+\s*m/);
    }
  });

  it("omits the count rather than printing zero", () => {
    // The hero ships with an empty object array by design (0122).
    const { measure, layout } = heroCard();
    expect(measure.pieceCount).toBe(0);
    expect(layout.claims.pieceText).toBeNull();
    expect(textOf(layout)).not.toContain("PIECES");
    expect(textOf(layout)).not.toContain("0");
  });

  it("prints a count when there is one, and singularises it", async () => {
    const assets = await new MockApiClient().getSceneAssets(MOCK_READY_SCENE_ID);
    const measure = measureRoom(assets.shell, assets.manifest)!;
    const layout = layoutCard({ measure, title: TITLE });
    expect(layout.claims.pieceText).toBe(String(measure.pieceCount));
    expect(textOf(layout)).toContain("PIECES");

    const one: RoomMeasure = { ...measure, pieceCount: 1 };
    expect(textOf(layoutCard({ measure: one, title: TITLE }))).toContain("PIECE");
  });

  it("carries the floor's measured colour and never an invented one", () => {
    const { measure, layout } = heroCard();
    expect(layout.claims.floorAlbedoHex).toBe(measure.floorAlbedoHex);
    const swatch = layout.ops.filter(
      (o) => o.kind === "rect" && o.fill === measure.floorAlbedoHex,
    );
    expect(swatch).toHaveLength(1);

    // An unobserved floor gets the neutral ink wash, no swatch, no hue.
    const unobserved: RoomMeasure = { ...measure, floorAlbedoHex: null };
    const plain = layoutCard({ measure: unobserved, title: TITLE });
    expect(plain.claims.floorAlbedoHex).toBeNull();
    expect(
      // From the token, not retyped -- a hardcoded hex here is the same
      // drift palette.test.ts exists to catch.
      plain.ops.filter((o) => o.kind === "rect" && o.fill !== PALETTE.paper),
    ).toHaveLength(0);
  });
});

/* ------------------------------------------------------------------ *
 * What the card must not carry (social-layer.md §6.2)
 * ------------------------------------------------------------------ */

describe("the card carries nothing on the forbidden list", () => {
  it("names no object — a count is not an inventory", async () => {
    const assets = await new MockApiClient().getSceneAssets(MOCK_READY_SCENE_ID);
    const measure = measureRoom(assets.shell, assets.manifest)!;
    const layout = layoutCard({ measure, title: TITLE });
    const labels = (assets.manifest.objects ?? []).map((o) => o.label);
    expect(labels.length).toBeGreaterThan(0);
    const blob = JSON.stringify(layout).toLowerCase();
    for (const label of labels) {
      expect(blob).not.toContain(label.toLowerCase());
    }
  });

  it("carries no identifier that resolves to the account or the scene", async () => {
    for (const sceneId of [MOCK_READY_SCENE_ID, MOCK_V3_SCENE_ID]) {
      const assets = await new MockApiClient().getSceneAssets(sceneId);
      const measure = measureRoom(assets.shell, assets.manifest)!;
      const blob = JSON.stringify(layoutCard({ measure, title: TITLE }));
      expect(blob).not.toContain(sceneId);
      expect(blob).not.toContain(assets.scene_id);
      // No id of any shape: no UUID, no gs:// URI, no signed URL.
      expect(blob).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}/i);
      expect(blob).not.toContain("gs://");
      expect(blob).not.toMatch(/https?:\/\//);
    }
  });

  it("carries no likeness — the display list has no image op at all", () => {
    const { layout } = heroCard();
    const kinds = new Set(layout.ops.map((o) => o.kind));
    expect([...kinds].sort()).toEqual(["fill", "glow", "rect", "stroke", "text", "wordmark"]);
  });

  it("carries no user-authored text — only the derived title and fixed copy", () => {
    // A room's name is private and does not travel (social-layer.md §9): a
    // name would be the first user-authored content shown to a stranger,
    // which is a moderation surface arriving through the side door (0207).
    const { layout } = heroCard();
    const derived = new Set([
      TITLE,
      CARD_SUBTITLE,
      // Tracked from the constants, not retyped: a rename must not be
      // able to stale this guard, which is the only thing standing
      // between a new string and an artifact that leaves the browser.
      // The product NAME is deliberately absent -- the card carries the
      // mark, which is a drawing rather than a string.
      DOMAIN,
      "CEILING",
      "FLOOR",
      "3.0 m",
      "10.7 m²",
      formatM(heroCard().measure.datum!.lengthM),
    ]);
    for (const text of textOf(layout)) {
      expect(derived.has(text), `unexpected string on the card: ${text}`).toBe(true);
    }
  });

  it("prints the derived date title, verbatim", () => {
    const { layout } = heroCard();
    expect(layout.claims.title).toBe(TITLE);
    expect(TITLE).toBe(roomTitle("2026-08-21T09:00:00Z"));
    expect(textOf(layout)).toContain(TITLE);
  });
});

/* ------------------------------------------------------------------ *
 * The frames
 * ------------------------------------------------------------------ */

describe("both frames", () => {
  it.each(["landscape", "square"] as CardVariant[])(
    "%s stays inside its own edges",
    (variant) => {
      const { layout } = heroCard(variant);
      expect(layout.width).toBe(CARD_FRAMES[variant].w);
      expect(layout.height).toBe(CARD_FRAMES[variant].h);
      for (const [x, y] of pointsOf(layout)) {
        expect(x).toBeGreaterThanOrEqual(-0.5);
        expect(x).toBeLessThanOrEqual(layout.width + 0.5);
        expect(y).toBeGreaterThanOrEqual(-0.5);
        expect(y).toBeLessThanOrEqual(layout.height + 0.5);
      }
    },
  );

  it.each(["landscape", "square"] as CardVariant[])(
    "%s draws the same room, only bigger or smaller",
    (variant) => {
      const { measure, layout } = heroCard(variant);
      // Same measurement, same claims — the frame changes the scale and
      // nothing else about what is asserted.
      expect(layout.claims.datum!.text).toBe(formatM(measure.datum!.lengthM));
      expect(layout.claims.floorText).toBe(`${measure.floorAreaM2.toFixed(1)} m²`);
    },
  );
});
