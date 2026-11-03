// WCAG contrast gate for the Leitsystem tokens. It reads the real stylesheets,
// resolves the OKLCH values the browser would compute for each theme and zone,
// and checks every text and control pair against its target. The expected
// ratios are the approved prototype measurements; a drift of more than 0.01
// means a token value no longer matches the approved design.
import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";

type Declarations = Record<string, string>;
type Rule = { selectors: string[]; declarations: Declarations };
type Oklch = [number, number, number];

const leitsystemCss = readFileSync(
  new URL("./leitsystem.css", import.meta.url),
  "utf8",
);
const tokensCss = readFileSync(
  new URL("./tokens.css", import.meta.url),
  "utf8",
);

/** Flat rules with their media condition; enough for token stylesheets. */
function parseRules(css: string): (Rule & { media: string | null })[] {
  const source = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules: (Rule & { media: string | null })[] = [];
  const pattern = /([^{}]+)\{([^{}]*)\}|@media([^{]+)\{|\}/g;
  let media: string | null = null;
  for (const match of source.matchAll(pattern)) {
    if (match[3] !== undefined) {
      media = match[3].trim();
    } else if (match[1] !== undefined) {
      const declarations: Declarations = {};
      for (const part of match[2].split(";")) {
        const separator = part.indexOf(":");
        if (separator === -1) continue;
        const name = part.slice(0, separator).trim();
        if (name.startsWith("--")) {
          declarations[name] = part
            .slice(separator + 1)
            .replace(/\s+/g, " ")
            .replace(/\(\s/g, "(")
            .replace(/\s\)/g, ")")
            .trim();
        }
      }
      rules.push({
        selectors: match[1].split(",").map((selector) => selector.trim()),
        declarations,
        media,
      });
    } else {
      media = null;
    }
  }
  return rules;
}

const rules = parseRules(leitsystemCss);

function rule(selector: string, media: string | null = null): Declarations {
  const found = rules.filter(
    (candidate) =>
      candidate.media === media && candidate.selectors.includes(selector),
  );
  if (found.length === 0) {
    throw new Error(`No rule for ${selector} (media ${media ?? "none"})`);
  }
  return Object.assign({}, ...found.map((candidate) => candidate.declarations));
}

const base = rule(":root");
const light = { ...base, ...rule(':root[data-theme="light"]') };
const dark = { ...base, ...rule(':root[data-theme="dark"]') };
const systemDark = rule(
  ':root:not([data-theme="light"])',
  "(prefers-color-scheme: dark)",
);
const zoneFormula = rule("[data-zone]");

function resolve(value: string, scope: Declarations, depth = 0): string {
  if (depth > 20) throw new Error(`Cyclic token: ${value}`);
  return value.replace(/var\((--[\w-]+)\)/g, (_, name: string) => {
    const next = scope[name];
    if (next === undefined) throw new Error(`Undefined token ${name}`);
    return resolve(next, scope, depth + 1);
  });
}

function component(value: string): number {
  const calc = /^calc\((.+)\)$/.exec(value);
  if (!calc) return Number(value);
  const factors = calc[1].split("*").map((factor) => Number(factor.trim()));
  return factors.reduce((product, factor) => product * factor, 1);
}

function oklch(name: string, scope: Declarations): Oklch {
  const value = resolve(scope[name] ?? `var(${name})`, scope);
  const match = /^oklch\((.+)\)$/.exec(value);
  if (!match) throw new Error(`${name} is not an oklch() colour: ${value}`);
  const parts = match[1]
    .split("/")[0]
    .trim()
    .match(/calc\([^)]*\)|[\d.]+/g);
  if (!parts || parts.length !== 3) throw new Error(`Bad oklch(): ${value}`);
  return parts.map(component) as Oklch;
}

// Ported from the prototype's tests/contrast.py (OKLab -> linear sRGB).
function linearSrgb([l, c, h]: Oklch): [number, number, number] {
  const a = c * Math.cos((h * Math.PI) / 180);
  const b = c * Math.sin((h * Math.PI) / 180);
  const l3 = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m3 = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s3 = (l - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const clamp = (v: number) => Math.min(1, Math.max(0, v));
  return [
    clamp(4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3),
    clamp(-1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3),
    clamp(-0.0041960863 * l3 - 0.7034186147 * m3 + 1.707614701 * s3),
  ];
}

function contrast(a: Oklch, b: Oklch): number {
  const luminance = (colour: Oklch) => {
    const [r, g, bl] = linearSrgb(colour);
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}

const TEXT = 4.5;
const UI = 3;

// [foreground, background, WCAG target or null for decorative, light, dark]
const pairs: [string, string, number | null, number, number][] = [
  ["--text", "--bg", TEXT, 16.59, 15.51],
  ["--text-2", "--bg", TEXT, 8.11, 9.24],
  ["--text-3", "--bg", TEXT, 5.28, 6.42],
  ["--text-3", "--surface", TEXT, 5.51, 5.94],
  ["--text-2", "--surface-2", TEXT, 7.76, 8.96],
  ["--on-accent", "--accent", TEXT, 7.52, 7.76],
  ["--accent-ink", "--bg", TEXT, 9.94, 10.48],
  ["--accent-ink", "--accent-soft", TEXT, 8.94, 8.03],
  ["--ok", "--ok-soft", TEXT, 4.95, 7.02],
  ["--warn", "--warn-soft", TEXT, 5.0, 7.25],
  ["--danger", "--danger-soft", TEXT, 5.28, 5.26],
  ["--info", "--info-soft", TEXT, 4.99, 6.62],
  ["--ok", "--surface", TEXT, 5.65, 8.39],
  ["--warn", "--surface", TEXT, 5.65, 9.06],
  ["--danger", "--surface", TEXT, 6.08, 6.45],
  ["--info", "--surface", TEXT, 5.75, 7.82],
  ["--rail-text", "--rail-bg", TEXT, 12.48, 11.72],
  ["--rail-text-2", "--rail-bg", TEXT, 8.21, 6.91],
  ["--rail-text", "--rail-active", TEXT, 8.33, 7.42],
  ["--border-strong", "--surface", null, 1.87, 1.86],
  ["--control-border", "--surface", UI, 3.64, 3.53],
];

// Pairs the plan adds on top of the prototype report.
const extraPairs: [string, string, number][] = [
  ["--focus", "--bg", UI],
  ["--focus", "--surface", UI],
  ["--control-border", "--bg", UI],
];

// Zone hues are keyed by the server navigation key. Expected values are the
// prototype's measurements for the matching wayfinding zone.
const zones: {
  zone: string;
  keys: string[];
  light: number;
  dark: number;
  surface: number;
}[] = [
  {
    zone: "uebersicht",
    keys: ["overview-web", "overview-pwa"],
    light: 7.56,
    dark: 8.79,
    surface: 5.63,
  },
  {
    zone: "aktionen",
    keys: ["actions", "public"],
    light: 7.45,
    dark: 8.91,
    surface: 5.54,
  },
  {
    zone: "bestellungen",
    keys: [
      "orders",
      "acquisition-web",
      "acquisition-pwa",
      "sponsors",
      "commitment",
      "pwa",
    ],
    light: 7.68,
    dark: 8.66,
    surface: 5.86,
  },
  {
    zone: "lieferung",
    keys: ["delivery"],
    light: 6.6,
    dark: 9.08,
    surface: 4.91,
  },
  {
    zone: "rechnungen",
    keys: ["invoices"],
    light: 7.11,
    dark: 9.08,
    surface: 5.21,
  },
  {
    zone: "mitglieder",
    keys: ["members"],
    light: 7.85,
    dark: 8.76,
    surface: 5.89,
  },
  {
    zone: "umfragen",
    keys: ["surveys"],
    light: 6.83,
    dark: 9.08,
    surface: 5.1,
  },
  { zone: "aufgaben", keys: ["tasks"], light: 7.84, dark: 8.52, surface: 6.02 },
  { zone: "eingang", keys: ["inbox"], light: 6.94, dark: 9.01, surface: 5.19 },
  {
    zone: "material",
    keys: ["materials"],
    light: 7.27,
    dark: 9.0,
    surface: 5.38,
  },
  {
    zone: "wissen",
    keys: ["knowledge"],
    light: 7.58,
    dark: 8.88,
    surface: 5.64,
  },
  {
    zone: "aktivitaet",
    keys: ["activities"],
    light: 7.43,
    dark: 8.92,
    surface: 5.51,
  },
  {
    zone: "kampagnenseiten",
    keys: ["microsite"],
    light: 7.94,
    dark: 8.73,
    surface: 5.98,
  },
  {
    zone: "recht",
    keys: ["legal", "privacy"],
    light: 7.53,
    dark: 8.88,
    surface: 5.6,
  },
  { zone: "system", keys: ["system"], light: 7.37, dark: 8.95, surface: 5.46 },
];

function zoneScope(theme: Declarations, key: string): Declarations {
  return { ...theme, ...rule(`[data-zone="${key}"]`), ...zoneFormula };
}

const themes = { light, dark } as const;

describe.each(Object.entries(themes))("%s theme", (name, theme) => {
  const index = name === "light" ? 3 : 4;

  test.each(pairs)("%s on %s", (...pair) => {
    const [foreground, background, target] = pair;
    const ratio = contrast(oklch(foreground, theme), oklch(background, theme));
    if (target !== null) expect(ratio).toBeGreaterThanOrEqual(target);
    expect(Math.abs(ratio - (pair[index] as number))).toBeLessThanOrEqual(
      0.011,
    );
  });

  test.each(extraPairs)("%s on %s", (foreground, background, target) => {
    expect(
      contrast(oklch(foreground, theme), oklch(background, theme)),
    ).toBeGreaterThanOrEqual(target);
  });

  test.each(
    zones.flatMap((zone) => zone.keys.map((key) => ({ ...zone, key }))),
  )("zone $key: --zone-ink on --zone-soft", (zone) => {
    const scope = zoneScope(theme, zone.key);
    const ratio = contrast(
      oklch("--zone-ink", scope),
      oklch("--zone-soft", scope),
    );
    const expected = name === "light" ? zone.light : zone.dark;
    expect(ratio).toBeGreaterThanOrEqual(TEXT);
    expect(Math.abs(ratio - expected)).toBeLessThanOrEqual(0.011);
  });
});

describe("zones", () => {
  test("all 15 prototype zones are covered", () => {
    expect(zones).toHaveLength(15);
  });

  test.each(zones)("$zone line keeps 3:1 on the light surface", (zone) => {
    for (const key of zone.keys) {
      const scope = zoneScope(light, key);
      const ratio = contrast(oklch("--zone", scope), oklch("--surface", light));
      expect(ratio).toBeGreaterThanOrEqual(UI);
      expect(Math.abs(ratio - zone.surface)).toBeLessThanOrEqual(0.011);
    }
  });

  test("the root falls back to the overview hue", () => {
    const scope = { ...light, ...zoneFormula };
    const ratio = contrast(
      oklch("--zone-ink", scope),
      oklch("--zone-soft", scope),
    );
    expect(Math.abs(ratio - 7.56)).toBeLessThanOrEqual(0.011);
  });
});

describe("theme switch", () => {
  test("the system dark theme declares exactly the explicit dark tokens", () => {
    expect(systemDark).toEqual(rule(':root[data-theme="dark"]'));
  });

  test("light tokens also apply without a data-theme attribute", () => {
    const root = rules.find(
      (candidate) =>
        candidate.selectors.includes(":root") &&
        candidate.selectors.includes(':root[data-theme="light"]'),
    );
    expect(root?.declarations["--bg"]).toBe("oklch(0.985 0.004 262)");
  });
});

describe("aliases for existing token names", () => {
  const aliasRules = parseRules(tokensCss);
  const aliases = Object.assign(
    {},
    ...aliasRules
      .filter((candidate) => candidate.selectors.includes(":root"))
      .map((candidate) => candidate.declarations),
  ) as Declarations;

  const expected: Record<string, string> = {
    "--background": "--bg",
    "--foreground": "--text",
    "--primary": "--accent",
    "--primary-foreground": "--on-accent",
    "--surface-muted": "--surface-2",
    "--input": "--control-border",
    "--muted": "--text-2",
    "--accent-foreground": "--accent-ink",
    "--danger-text": "--danger",
    "--danger-foreground": "--on-accent",
    "--success": "--ok",
    "--success-text": "--ok",
    "--warning": "--warn",
    "--warning-text": "--warn",
    "--warning-foreground": "--on-accent",
    "--sidebar": "--rail-bg",
    "--sidebar-foreground": "--rail-text",
    "--sidebar-muted": "--rail-text-2",
    "--sidebar-active": "--rail-active",
    "--sidebar-accent": "--rail-marker",
  };

  test.each(Object.entries(expected))("%s points to %s", (alias, target) => {
    expect(aliases[alias]).toBe(`var(${target})`);
  });

  test("aliases are theme independent", () => {
    expect(
      aliasRules.filter(
        (candidate) =>
          candidate.media !== null ||
          candidate.selectors.some((selector) =>
            selector.includes("data-theme"),
          ),
      ),
    ).toEqual([]);
  });

  // Pairs the existing components render with the old names.
  const aliasPairs: [string, string, number][] = [
    ["--foreground", "--background", TEXT],
    ["--primary-foreground", "--primary", TEXT],
    ["--danger-foreground", "--danger", TEXT],
    ["--warning-foreground", "--warning", TEXT],
    ["--muted", "--surface", TEXT],
    ["--muted", "--surface-muted", TEXT],
    ["--danger-text", "--surface", TEXT],
    ["--success-text", "--surface", TEXT],
    ["--warning-text", "--surface", TEXT],
    ["--accent-foreground", "--accent-soft", TEXT],
    ["--sidebar-foreground", "--sidebar", TEXT],
    ["--sidebar-muted", "--sidebar", TEXT],
    ["--input", "--surface", UI],
  ];

  describe.each(Object.entries(themes))("%s theme", (_, theme) => {
    test.each(aliasPairs)("%s on %s", (foreground, background, target) => {
      const scope = { ...theme, ...aliases };
      expect(
        contrast(oklch(foreground, scope), oklch(background, scope)),
      ).toBeGreaterThanOrEqual(target);
    });
  });
});
