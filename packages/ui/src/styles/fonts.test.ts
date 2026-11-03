// fonts.css copies the latin JetBrains Mono face from the package so that
// only one subset ships. A package bump that renames the file or changes the
// face must fail here instead of silently dropping the font.
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { describe, expect, test } from "vitest";

const require = createRequire(import.meta.url);
const fontsCss = readFileSync(new URL("./fonts.css", import.meta.url), "utf8");

function packageFile(specifier: string): string {
  const [scope, name, ...rest] = specifier.split("/");
  const root = dirname(require.resolve(`${scope}/${name}/package.json`));
  return join(root, ...rest);
}

function normalise(value: string): string {
  return value.replace(/\s+/g, "").replace(/['"]/g, "");
}

function declaration(block: string, name: string): string {
  const match = new RegExp(`${name}:([^;]+);`).exec(block);
  if (!match) throw new Error(`${name} missing in ${block}`);
  return normalise(match[1]);
}

describe("self-hosted fonts", () => {
  test.each([...fontsCss.matchAll(/@import "([^"]+)";/g)].map((m) => m[1]))(
    "imported stylesheet %s exists",
    (specifier) => {
      expect(existsSync(packageFile(specifier))).toBe(true);
    },
  );

  const face = /@font-face\s*\{([^}]+)\}/.exec(fontsCss)?.[1] ?? "";
  const url = /url\("([^"]+)"\)/.exec(face)?.[1] ?? "";

  test("the JetBrains Mono file referenced in fonts.css is installed", () => {
    expect(url).toMatch(
      /^@fontsource-variable\/jetbrains-mono\/files\/.+\.woff2$/,
    );
    expect(existsSync(packageFile(url))).toBe(true);
  });

  test("the copied face matches the package's latin face", () => {
    const upstream = readFileSync(
      packageFile("@fontsource-variable/jetbrains-mono/wght.css"),
      "utf8",
    );
    const fileName = url.split("/").pop() ?? "";
    const upstreamFace = [...upstream.matchAll(/@font-face\s*\{([^}]+)\}/g)]
      .map((m) => m[1])
      .find((block) => block.includes(`./files/${fileName}`));
    expect(upstreamFace, `${fileName} not declared upstream`).toBeDefined();
    for (const name of [
      "font-family",
      "font-style",
      "font-weight",
      "unicode-range",
    ]) {
      expect(declaration(face, name), name).toBe(
        declaration(upstreamFace ?? "", name),
      );
    }
  });
});
