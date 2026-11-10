import { describe, expect, it } from "vitest";

import { DONATION_INPUT_PATTERN, parseDonationAmount } from "./order-donation";

describe("parseDonationAmount", () => {
  it("treats an empty field as no donation", () => {
    expect(parseDonationAmount("")).toEqual({ kind: "empty" });
    expect(parseDonationAmount("   ")).toEqual({ kind: "empty" });
    expect(parseDonationAmount(undefined)).toEqual({ kind: "empty" });
    expect(parseDonationAmount(null)).toEqual({ kind: "empty" });
  });

  it.each([
    ["1", 100],
    ["25", 2_500],
    ["25,5", 2_550],
    ["25,50", 2_550],
    ["25.50", 2_550],
    [" 25,50 € ", 2_550],
    ["1.000", 100_000],
    ["1.000,50", 100_050],
    ["10.000,00", 1_000_000],
    ["10000", 1_000_000],
    ["0,29", null],
    ["1,00", 100],
  ])("reads %j", (raw, minor) => {
    expect(parseDonationAmount(raw)).toEqual(
      minor === null ? { kind: "invalid" } : { kind: "amount", minor },
    );
  });

  it.each([
    "0",
    "0,99",
    "10000,01",
    "10.000,01",
    "-5",
    "5,555",
    "fünf",
    "1e3",
    "1,000.50",
    "5 EUR",
    "99999999999",
  ])("refuses %j", (raw) => {
    expect(parseDonationAmount(raw)).toEqual({ kind: "invalid" });
  });

  it("keeps cents exact", () => {
    expect(parseDonationAmount("19,99")).toEqual({
      kind: "amount",
      minor: 1_999,
    });
    expect(parseDonationAmount("0,57")).toEqual({ kind: "invalid" });
    expect(parseDonationAmount("1,15")).toEqual({ kind: "amount", minor: 115 });
  });
});

describe("DONATION_INPUT_PATTERN", () => {
  const pattern = new RegExp(`^(?:${DONATION_INPUT_PATTERN})$`, "u");

  it("accepts every format the parser reads", () => {
    for (const raw of ["5", "5,5", "5.50", "1.000,00", " 25,50 € "])
      expect(pattern.test(raw)).toBe(true);
  });

  it("refuses text the parser refuses for its format", () => {
    for (const raw of ["fünf", "-5", "5,555", "1e3"])
      expect(pattern.test(raw)).toBe(false);
  });
});
