import { describe, expect, it, vi } from "vitest";

import type { PublicLegalProviderResponse } from "@leonaid/api-client";

import {
  createLegalNoticeReader,
  providerAddress,
  providerRegister,
  telephoneHref,
} from "./legal-notice";

const provider: PublicLegalProviderResponse = {
  legalName: "Lions Hilfswerk LeonAid Golden e.V.",
  streetLine1: "Clubweg 1",
  postalCode: "86150",
  city: "Augsburg",
  countryCode: "DE",
  email: "finanzen@leonaid.invalid",
};

function setup(load: () => Promise<PublicLegalProviderResponse | null>) {
  let now = 1_000_000;
  const loader = vi.fn(load);
  const read = createLegalNoticeReader(loader, () => now);
  return {
    loader,
    read,
    advance: (ms: number) => {
      now += ms;
    },
  };
}

describe("readLegalNotice cache", () => {
  it("caches a provider for 60 s", async () => {
    const { advance, loader, read } = setup(async () => provider);
    expect(await read()).toEqual({ state: "ready", provider });
    advance(59_000);
    await read();
    expect(loader).toHaveBeenCalledTimes(1);
    advance(2_000);
    await read();
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it("caches 'none active yet' for 10 s, then reads again", async () => {
    let active: PublicLegalProviderResponse | null = null;
    const { advance, loader, read } = setup(async () => active);
    expect(await read()).toEqual({ state: "ready", provider: null });
    await read();
    expect(loader).toHaveBeenCalledTimes(1);
    active = provider;
    advance(10_001);
    expect(await read()).toEqual({ state: "ready", provider });
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it("caches a failure for 10 s instead of waiting on every render", async () => {
    let fail = true;
    const { advance, loader, read } = setup(async () => {
      if (fail) throw new Error("Core down");
      return provider;
    });
    expect(await read()).toEqual({ state: "unavailable" });
    expect(await read()).toEqual({ state: "unavailable" });
    expect(loader).toHaveBeenCalledTimes(1);
    fail = false;
    advance(10_001);
    expect(await read()).toEqual({ state: "ready", provider });
  });

  it("keeps the last provider when a later read fails", async () => {
    let fail = false;
    const { advance, loader, read } = setup(async () => {
      if (fail) throw new Error("Core down");
      return provider;
    });
    await read();
    fail = true;
    advance(60_001);
    expect(await read()).toEqual({ state: "ready", provider });
    advance(5_000);
    await read();
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it("shares one request between concurrent renders", async () => {
    let resolve: (value: PublicLegalProviderResponse) => void = () => {};
    const { loader, read } = setup(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    const first = read();
    const second = read();
    resolve(provider);
    expect(await first).toEqual(await second);
    expect(loader).toHaveBeenCalledTimes(1);
  });
});

describe("providerAddress", () => {
  it("omits Germany and names other countries", () => {
    expect(providerAddress(provider)).toBe("Clubweg 1 · 86150 Augsburg");
    expect(providerAddress({ ...provider, countryCode: "AT" })).toBe(
      "Clubweg 1 · 86150 Augsburg · Österreich",
    );
  });
});

describe("providerRegister", () => {
  it("joins court and number, and is null without an entry", () => {
    expect(providerRegister(provider)).toBeNull();
    expect(
      providerRegister({
        ...provider,
        registerCourt: "Amtsgericht Augsburg",
        registerNumber: "VR 1234",
      }),
    ).toBe("Amtsgericht Augsburg, VR 1234");
    expect(
      providerRegister({ ...provider, registerCourt: "Amtsgericht Augsburg" }),
    ).toBeNull();
  });
});

describe("telephoneHref", () => {
  it("keeps digits and a leading plus", () => {
    expect(telephoneHref("+49 (821) 123-456")).toBe("tel:+49821123456");
    expect(telephoneHref("0821 / 12 34 56")).toBe("tel:0821123456");
  });
});
