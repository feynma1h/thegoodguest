import { describe, expect, it, vi } from "vitest";

import { loadShellExtras, NO_EXTRAS, shellExtras } from "./shellExtras";

const hex = "#c9c4bb";
const finish = (walls: number) => ({
  finish_version: 2,
  scene_id: "s",
  wall_count: walls,
  trim: { hex, baseboard_h_m: 0.09, baseboard_d_m: 0.014, casing_w_m: 0.07, casing_d_m: 0.016 },
  walls: Array.from({ length: walls }, (_, i) => ({
    wall_id: `wall_0${i}`,
    paint: { hex, source: "measured", sheen: 0.1, grain: 0.03 },
    openings: [],
  })),
  floor: null,
});
const furniture = {
  furniture_version: 1,
  scene_id: "s",
  objects: [{ key: "k", position: [0, 0, 0], yaw: 0, source: "boxes", spec: { key: "k", label: "k", box_dims: [1, 1, 1], materials: {}, parts: [] } }],
};

describe("shellExtras", () => {
  it("is empty for nothing, junk or a finish that does not fit the shell", () => {
    expect(shellExtras(4, null, null)).toEqual(NO_EXTRAS);
    expect(shellExtras(4, "finish", furniture)).toEqual(NO_EXTRAS);
    expect(shellExtras(4, finish(3), furniture)).toEqual(NO_EXTRAS);
  });
  it("draws a fitting finish alone, or with twins", () => {
    expect(shellExtras(4, finish(4), null).furniture).toBeNull();
    expect(shellExtras(4, finish(4), null).finish?.wall_count).toBe(4);
    expect(shellExtras(4, finish(4), furniture).furniture?.objects).toHaveLength(1);
  });
  it("draws neither twins nor anything without a finish, and ignores bad twins", () => {
    expect(shellExtras(4, null, furniture)).toEqual(NO_EXTRAS);
    expect(shellExtras(4, finish(4), { furniture_version: 9 }).furniture).toBeNull();
    expect(shellExtras(4, finish(4), { furniture_version: 1, objects: 7 }).finish).not.toBeNull();
  });
  it("never throws on malformed documents", () => {
    expect(() => shellExtras(1, 3, { objects: 7 })).not.toThrow();
    expect(() => shellExtras(1, { finish_version: 2, wall_count: 1, walls: [null], trim: null }, 5)).not.toThrow();
  });
});

describe("loadShellExtras", () => {
  const urls = { finish_url: "https://signed/finish.json", furniture_url: "https://signed/furniture.json" };
  const serve = (docs: Record<string, unknown>) =>
    vi.fn(async (url: string) => {
      if (!(url in docs)) throw new Error("404");
      return docs[url];
    });

  it("makes no request when the flag is off or there are no links", async () => {
    const get = serve({});
    expect(await loadShellExtras(urls, 4, get, false)).toEqual(NO_EXTRAS);
    expect(await loadShellExtras({ finish_url: null, furniture_url: null }, 4, get, true)).toEqual(NO_EXTRAS);
    expect(await loadShellExtras({}, 4, get, true)).toEqual(NO_EXTRAS);
    expect(get).not.toHaveBeenCalled();
  });
  it("fetches both files, each from its own link, and validates them", async () => {
    const get = serve({ [urls.finish_url]: finish(4), [urls.furniture_url]: furniture });
    const out = await loadShellExtras(urls, 4, get, true);
    expect(out.finish?.wall_count).toBe(4);
    expect(out.furniture?.objects).toHaveLength(1);
    expect(get).toHaveBeenCalledTimes(2);
  });
  it("draws the finish when the furniture link is missing or fails", async () => {
    const only = await loadShellExtras({ finish_url: urls.finish_url }, 4, serve({ [urls.finish_url]: finish(4) }), true);
    expect(only.finish).not.toBeNull();
    expect(only.furniture).toBeNull();
    const failing = await loadShellExtras(urls, 4, serve({ [urls.finish_url]: finish(4) }), true);
    expect(failing.finish).not.toBeNull();
    expect(failing.furniture).toBeNull();
  });
  it("leaves the room alone when the finish cannot be fetched or does not fit", async () => {
    expect(await loadShellExtras(urls, 4, serve({ [urls.furniture_url]: furniture }), true)).toEqual(NO_EXTRAS);
    expect(await loadShellExtras(urls, 5, serve({ [urls.finish_url]: finish(4), [urls.furniture_url]: furniture }), true)).toEqual(NO_EXTRAS);
  });
});
