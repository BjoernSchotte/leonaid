import { describe, expect, it } from "vitest";
import {
  RUNTIME_DOMAIN_PLACEHOLDER,
  patchRuntimeDomain,
  runtimeHostnames,
} from "../../runtime-allowed-domains.mjs";

// A serialized manifest fragment as Astro writes it into the server build.
const manifest = `const m = { allowedDomains: [{"hostname":"localhost"},${JSON.stringify(
  { hostname: RUNTIME_DOMAIN_PLACEHOLDER },
)}] };\nexport default m;`;

function allowedDomains(
  variables: string[],
  environment: Record<string, string | undefined>,
): unknown {
  const patched = patchRuntimeDomain(manifest, variables).replace(
    "export default m;",
    "return m.allowedDomains;",
  );
  const run = new Function("process", patched) as (process: {
    env: Record<string, string | undefined>;
  }) => unknown;
  return run({ env: environment });
}

describe("runtime allowed domains (specs/multi-domain §6.4)", () => {
  it("adds the admin host, the public host and its aliases", () => {
    expect(
      allowedDomains(
        [
          "LEONAID_ADMIN_DOMAIN",
          "LEONAID_PUBLIC_DOMAIN",
          "LEONAID_PUBLIC_DOMAIN_ALIASES",
        ],
        {
          LEONAID_ADMIN_DOMAIN: "App.Example.org",
          LEONAID_PUBLIC_DOMAIN: "example.org",
          LEONAID_PUBLIC_DOMAIN_ALIASES: "www.example.org, alt.example.org",
        },
      ),
    ).toEqual([
      { hostname: "localhost" },
      { hostname: "app.example.org" },
      { hostname: "example.org" },
      { hostname: "www.example.org" },
      { hostname: "alt.example.org" },
    ]);
  });

  it("keeps a single host and ignores unset or empty variables", () => {
    expect(
      allowedDomains(["LEONAID_ADMIN_DOMAIN", "LEONAID_PUBLIC_DOMAIN"], {
        LEONAID_ADMIN_DOMAIN: "",
        LEONAID_PUBLIC_DOMAIN: "portal.example.org",
      }),
    ).toEqual([{ hostname: "localhost" }, { hostname: "portal.example.org" }]);
    expect(allowedDomains(["LEONAID_PUBLIC_DOMAIN"], {})).toEqual([
      { hostname: "localhost" },
    ]);
  });

  it("drops ports and anything that is not a host name", () => {
    expect(
      runtimeHostnames([
        "app.localhost:28443",
        "evil.example/path",
        "*.example.org",
        " ",
        undefined,
      ]),
    ).toEqual(["app.localhost"]);
  });

  it("refuses a manifest without exactly one placeholder", () => {
    expect(() => patchRuntimeDomain("export default {};", ["A"])).toThrow();
    expect(() => patchRuntimeDomain(manifest, ["lower_case"])).toThrow();
  });
});
