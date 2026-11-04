/**
 * Furniture twins (tools/furniture_models.py -> furniture.json).
 *
 * A twin is a small parametric model of one real piece: parts (rounded
 * boxes, cylinders, lathes, tubes, extrusions) with explicit metre
 * dimensions and named materials, written as a JSON spec by a vision model
 * that has looked at the capture's photos of the piece, and checked by
 * rendering it from the capture's own camera poses. Parts live in the
 * piece's box frame: origin = centre of the footprint ON THE FLOOR,
 * +y up, x/z = the box's axes. furniture.json carries each spec with its
 * world placement already resolved from the scan's boxes.
 *
 * Conventions the viewer reads: a part named `lamp-shade` is the room's light
 * at night; meshes named `glass-*` in a twin of category `window` are panes
 * that glow by day. Drawn only with the finish (NEXT_PUBLIC_SHELL_FINISH=1).
 */

export type Vec3 = [number, number, number];

export interface TexSpec {
  kind: "quilt" | "wood" | "weave" | "lattice" | "ribbon" | "stripe" | "grid";
  /** Metres one repeat of the texture covers. */
  tile_m?: number;
  /** Colours the pattern draws with (hex). */
  palette?: string[];
  /** Pattern-specific numbers (cell size, grain strength, ...). */
  p?: Record<string, number>;
  seed?: number;
}

export interface MatSpec {
  color: string;
  rough?: number;
  metal?: number;
  clearcoat?: number;
  opacity?: number;
  /** Draw both faces (thin cloth, lamp shades). */
  double?: boolean;
  emissive?: string;
  emissive_intensity?: number;
  tex?: TexSpec;
  /** 0..1 strength of a fine fabric/grain bump, 0 = smooth. */
  bump?: number;
}

interface PartBase {
  /** Material name in `materials`. */
  mat: string;
  at?: Vec3;
  /** Euler degrees (XYZ), applied about the part's own centre. */
  rot?: Vec3;
  name?: string;
  /** Swap the texture's u/v (turns wood grain by 90 degrees). */
  uvSwap?: boolean;
  noShadow?: boolean;
}

export type Part =
  | (PartBase & { kind: "box"; size: Vec3; bevel?: number })
  | (PartBase & { kind: "cyl"; r: number; rTop?: number; h: number; seg?: number })
  | (PartBase & { kind: "sphere"; r: Vec3 | number })
  /** Surface of revolution about y: profile = [radius, y] pairs, bottom to top. */
  | (PartBase & { kind: "lathe"; profile: [number, number][]; seg?: number })
  /** A round tube along a smooth path. */
  | (PartBase & { kind: "tube"; path: Vec3[]; r: number; closed?: boolean; seg?: number })
  /** A 2D outline in the x/y plane, extruded `depth` along z, with a soft bevel. */
  | (PartBase & { kind: "extrude"; outline: [number, number][]; depth: number; bevel?: number })
  /** A shelf row of upright books along x, standing on y = at.y. */
  | (PartBase & { kind: "books"; w: number; depth: number; hmin: number; hmax: number; tmin?: number; tmax?: number; mats: string[]; seed?: number })
  /** A pleated hanging cloth of `w` x `h`, `folds` pleats of amplitude `amp`. */
  | (PartBase & { kind: "drape"; w: number; h: number; folds: number; amp: number; /** Pleat depth reference: full height of the cloth this strip belongs to, and how far this strip's bottom is above that cloth's bottom (a header strip then pleats like the panel below it). */ hemH?: number; hemOff?: number });

export interface FurnitureSpec {
  key: string;
  label: string;
  /** Free text: what the model is, what was not recoverable. */
  note?: string;
  /** Box dims the spec was written against (w, h, d) — sanity check. */
  box_dims: Vec3;
  materials: Record<string, MatSpec>;
  parts: Part[];
}

export interface FurniturePlacement {
  key: string;
  /** World position of the footprint centre ON THE FLOOR (x, y, z metres). */
  position: Vec3;
  /** World rotation about y, radians (the box's yaw plus any fix). */
  yaw: number;
  /** Where the placement came from: `boxes`, or `boxes+fixed` when a rule or a hand fix moved it. */
  source: string;
  /** The box's category (`window` marks the wall the day light comes through). */
  category?: string;
  /** The placement rule tools/furniture_placement.py applied (floor, wall, over, on, opening). */
  rule?: string;
  /** Every move the rules or a hand fix made, each with its reason. */
  fixes?: { rule: string; why: string }[];
  /** "wall": the piece hangs on or stands against a wall (its local +z faces the room) and is hidden
   * with that wall when the diorama camera looks in from outside. */
  mount?: "wall";
  spec: FurnitureSpec;
}

export interface FurnitureBundle {
  furniture_version: 1;
  scene_id: string | null;
  objects: FurniturePlacement[];
  /** Viewer-side, not in furniture.json: "photo" keeps the light the render-vs-photo
   * loop was calibrated in; "diorama" (default) is the designed look. */
  look?: "photo" | "diorama";
  /** Viewer-side: which time of day the room opens in (the diorama look only). Default "day". */
  mode?: "day" | "night";
}

export function parseFurniture(raw: unknown): FurnitureBundle | null {
  if (!raw || typeof raw !== "object") return null;
  const b = raw as Partial<FurnitureBundle>;
  if (b.furniture_version !== 1 || !Array.isArray(b.objects)) return null;
  for (const o of b.objects) {
    if (!o || !o.spec || !Array.isArray(o.position) || typeof o.yaw !== "number") return null;
    if (!Array.isArray(o.spec.parts) || typeof o.spec.materials !== "object") return null;
  }
  return b as FurnitureBundle;
}
