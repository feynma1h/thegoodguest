// Writes out/third-party-notices.txt once `next build` has produced the static
// export. `npm run build` runs it, so every Hosting deploy carries the file.
//
// The export ships code, a stylesheet and fonts written by other people, and
// their licences ask for their notices to travel with them. The bundler strips
// licence comments, so this collects the notices instead:
//
//   - every runtime package in package-lock.json, with the licence text it
//     ships (dev-only and optional platform packages are left out);
//   - the packages Next.js vendors under next/dist/compiled;
//   - tailwindcss, a build tool whose generated stylesheet ships;
//   - the fonts next/font self-hosts, read from the built font files.
//
// That is more than the browser receives: a build with source maps on
// 2026-09-13 found 22 of these packages in the client bundle. Listing a
// package that does not ship costs nothing, and unlike a hand-kept list this
// cannot fall behind when a dependency changes.

import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { brotliDecompressSync } from "node:zlib";

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUT = path.join(WEB, "out");
const MODULES = path.join(WEB, "node_modules");
const COMPILED = path.join(MODULES, "next", "dist", "compiled");
const OFL_TEXT = path.join(WEB, "scripts", "OFL-1.1.txt");
const LICENCE_FILE = /^(licen[cs]e|copying|notice)([.-][\w.-]*)?$/i;
const APACHE_2 = /^\s*Apache License\s+Version 2\.0, January 2004/;
const RULE = "=".repeat(72);

const readJson = (file) => JSON.parse(readFileSync(file, "utf8"));
const isDir = (file) => statSync(file).isDirectory();

function licenceTexts(dir) {
  return readdirSync(dir)
    .filter((name) => LICENCE_FILE.test(name) && !isDir(path.join(dir, name)))
    .sort()
    .map((name) => readFileSync(path.join(dir, name), "utf8").trim());
}

function declaredLicence(pkg) {
  if (typeof pkg.license === "string") return pkg.license;
  if (pkg.license?.type) return pkg.license.type;
  if (Array.isArray(pkg.licenses)) return pkg.licenses.map((l) => l.type ?? l).join(" OR ");
  return null;
}

function describe(dir, fallbackName) {
  const manifest = path.join(dir, "package.json");
  const pkg = existsSync(manifest) ? readJson(manifest) : {};
  return {
    name: pkg.name ?? fallbackName,
    version: pkg.version,
    licence: declaredLicence(pkg),
    texts: licenceTexts(dir),
  };
}

function runtimePackages() {
  const lock = readJson(path.join(WEB, "package-lock.json"));
  return (
    Object.entries(lock.packages)
      .filter(([key, meta]) => key.startsWith("node_modules/") && !meta.dev && !meta.optional && !meta.devOptional)
      .map(([key]) => path.join(WEB, key))
      // A package that is not installed cannot have been bundled.
      .filter((dir) => existsSync(path.join(dir, "package.json")))
      .map((dir) => describe(dir))
  );
}

function vendoredByNext() {
  const found = [];
  const walk = (dir) => {
    if (dir !== COMPILED) {
      // Next's own build tooling is vendored here too, some of it with no
      // licence text and no declared licence; an entry would say nothing.
      const pkg = describe(dir, path.relative(COMPILED, dir));
      if (pkg.texts.length > 0 || pkg.licence) found.push(pkg);
    }
    for (const name of readdirSync(dir)) {
      const child = path.join(dir, name);
      if (isDir(child)) walk(child);
    }
  };
  walk(COMPILED);
  return found;
}

// WOFF2 names its tables by index into this list (WOFF2 specification, 5.1).
const WOFF2_TAGS = [
  "cmap", "head", "hhea", "hmtx", "maxp", "name", "OS/2", "post", "cvt ", "fpgm", "glyf", "loca",
  "prep", "CFF ", "VORG", "EBDT", "EBLC", "gasp", "hdmx", "kern", "LTSH", "PCLT", "VDMX", "vhea",
  "vmtx", "BASE", "GDEF", "GPOS", "GSUB", "EBSC", "JSTF", "MATH", "CBDT", "CBLC", "COLR", "CPAL",
  "SVG ", "sbix", "acnt", "avar", "bdat", "bloc", "bsln", "cvar", "fdsc", "feat", "fmtx", "fvar",
  "gvar", "hsty", "just", "lcar", "mort", "morx", "opbd", "prop", "trak", "Zapf", "Silf", "Glat",
  "Gloc", "Feat", "Sill",
];

function readBase128(bytes, cursor) {
  let value = 0;
  for (let i = 0; i < 5; i += 1) {
    const byte = bytes[cursor.at++];
    value = value * 128 + (byte & 0x7f);
    if (!(byte & 0x80)) return value;
  }
  throw new Error("malformed UIntBase128 in a WOFF2 table directory");
}

function nameRecords(table) {
  const count = table.readUInt16BE(2);
  const strings = table.readUInt16BE(4);
  const names = {};
  for (let i = 0; i < count; i += 1) {
    const record = 6 + i * 12;
    const id = table.readUInt16BE(record + 6);
    const start = strings + table.readUInt16BE(record + 10);
    const end = start + table.readUInt16BE(record + 8);
    // Windows-platform strings are UTF-16BE. The first one for each id wins.
    if (table.readUInt16BE(record) === 3 && names[id] === undefined) {
      names[id] = Buffer.from(table.subarray(start, end)).swap16().toString("utf16le");
    }
  }
  return { family: names[16] ?? names[1], copyright: names[0], licenceUrl: names[14] };
}

// The family, copyright notice and licence URL a WOFF2 file's name table carries.
function fontNames(file) {
  const bytes = readFileSync(file);
  if (bytes.toString("latin1", 0, 4) !== "wOF2") return null;
  const tableCount = bytes.readUInt16BE(12);
  const compressedLength = bytes.readUInt32BE(20);
  const cursor = { at: 48 };
  const tables = [];
  for (let i = 0; i < tableCount; i += 1) {
    const flags = bytes[cursor.at++];
    let tag = WOFF2_TAGS[flags & 0x3f];
    if ((flags & 0x3f) === 63) {
      tag = bytes.toString("latin1", cursor.at, cursor.at + 4);
      cursor.at += 4;
    }
    const version = flags >> 6;
    const originalLength = readBase128(bytes, cursor);
    const transformed = tag === "glyf" || tag === "loca" ? version === 0 : version !== 0;
    tables.push({ tag, length: transformed ? readBase128(bytes, cursor) : originalLength });
  }
  const data = brotliDecompressSync(bytes.subarray(cursor.at, cursor.at + compressedLength));
  let offset = 0;
  for (const { tag, length } of tables) {
    if (tag === "name") return nameRecords(data.subarray(offset, offset + length));
    offset += length;
  }
  return null;
}

function shippedFonts() {
  const media = path.join(OUT, "_next", "static", "media");
  const families = new Map();
  if (!existsSync(media)) return families;
  for (const name of readdirSync(media).filter((n) => n.endsWith(".woff2")).sort()) {
    const font = fontNames(path.join(media, name));
    if (!font?.family) continue;
    const entry = families.get(font.family) ?? { copyrights: new Set(), licenceUrls: new Set() };
    if (font.copyright) entry.copyrights.add(font.copyright.trim());
    if (font.licenceUrl) entry.licenceUrls.add(font.licenceUrl.trim());
    families.set(font.family, entry);
  }
  return new Map([...families].sort(([a], [b]) => a.localeCompare(b)));
}

function heading(title) {
  return `${RULE}\n${title}\n${RULE}`;
}

// One entry per distinct licence text, naming every package that ships it.
function packageEntries(packages, apacheText) {
  const unique = new Map(packages.map((p) => [`${p.name}@${p.version ?? ""}`, p]));
  const groups = new Map();
  for (const pkg of [...unique.values()].sort((a, b) => a.name.localeCompare(b.name))) {
    const key = pkg.texts.length > 0 ? pkg.texts.join("\n\n") : `declared:${pkg.licence ?? ""}`;
    const group = groups.get(key) ?? { texts: pkg.texts, licences: new Set(), names: [] };
    if (pkg.licence) group.licences.add(pkg.licence);
    group.names.push(pkg.version ? `${pkg.name} ${pkg.version}` : pkg.name);
    groups.set(key, group);
  }
  return [...groups.values()].map(({ texts, licences, names }) => {
    const declared = [...licences];
    const subject = names.length === 1 ? "this package" : "these packages";
    let body = texts.join("\n\n");
    if (!body && declared.length === 0) {
      body = `No licence file ships with ${subject}, and none is declared.`;
    } else if (!body) {
      body = `No licence file ships with ${subject}.`;
      if (declared.join() === "Apache-2.0" && apacheText) {
        body += " The Apache License 2.0 text is at the end of this file.";
      }
    }
    const header = declared.length > 0 ? [...names, `Licence: ${declared.join(", ")}`] : names;
    return `${header.join("\n")}\n\n${body}`;
  });
}

function main() {
  if (!existsSync(path.join(OUT, "index.html"))) {
    throw new Error("out/index.html is missing: run `next build` before this script");
  }

  const packages = [...runtimePackages(), describe(path.join(MODULES, "tailwindcss"))];
  const vendored = vendoredByNext();
  const apacheText = [...packages, ...vendored].flatMap((p) => p.texts).find((t) => APACHE_2.test(t));
  const fonts = shippedFonts();

  const sections = [
    "Third-party notices\n\n" +
      "This site is built with open-source software and fonts made by other\n" +
      "people. Their licences ask for these notices to travel with the site, so\n" +
      "they are collected here. Packages that share a licence text are listed\n" +
      "together.",
    heading("Packages"),
    ...packageEntries(packages, apacheText),
    heading("Packages vendored inside next"),
    ...packageEntries(vendored, apacheText),
  ];

  if (fonts.size > 0) {
    sections.push(heading("Fonts"));
    for (const [family, { copyrights, licenceUrls }] of fonts) {
      sections.push([family, ...copyrights, ...[...licenceUrls].map((url) => `Licence: ${url}`)].join("\n"));
    }
    const ofl = [...fonts.values()].some(({ licenceUrls }) => [...licenceUrls].some((url) => /OFL/i.test(url)));
    if (ofl) sections.push(readFileSync(OFL_TEXT, "utf8").trim());
  }

  if (apacheText) sections.push(heading("Apache License 2.0"), apacheText);

  const target = path.join(OUT, "third-party-notices.txt");
  writeFileSync(target, `${sections.join("\n\n")}\n`);
  console.log(
    `third-party-notices.txt: ${packages.length + vendored.length} packages, ${fonts.size} font families`,
  );
}

main();
