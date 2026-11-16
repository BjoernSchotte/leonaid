import { describe, expect, it } from "vitest";
import {
  deadlineLabel,
  deliveryDays,
  orderDeadline,
  remainingLabel,
} from "./order-deadline";

const until = "2027-02-02T16:00:00Z";

describe("order deadline (E-068)", () => {
  it("is the latest end of all offerings, none while one is open-ended", () => {
    expect(
      orderDeadline([
        { availableUntil: until },
        { availableUntil: "2027-01-31T16:00:00Z" },
      ]),
    ).toBe("2027-02-02T16:00:00.000Z");
    expect(
      orderDeadline([{ availableUntil: until }, { availableUntil: null }]),
    ).toBeNull();
    expect(orderDeadline([])).toBeNull();
  });

  it("names the local time and counts down", () => {
    expect(deadlineLabel(until)).toBe("Dienstag, 2. Februar 2027 um 17:00 Uhr");
    const at = Date.parse(until);
    expect(remainingLabel(until, at - 78 * 86_400_000)).toBe("noch 78 Tage");
    expect(remainingLabel(until, at - 5 * 3_600_000)).toBe("noch 5 Stunden");
    expect(remainingLabel(until, at - 60_000)).toBe("noch 1 Minute");
    expect(remainingLabel(until, at)).toBeNull();
  });
});

describe("delivery days (E-068)", () => {
  it("joins the windows of a day and sorts the days", () => {
    expect(
      deliveryDays([
        { deliveryOn: "2027-02-04", startsAt: "09:00:00", endsAt: "11:00:00" },
        { deliveryOn: "2027-02-03", startsAt: "11:00:00", endsAt: "13:00:00" },
        { deliveryOn: "2027-02-03", startsAt: "07:00:00", endsAt: "09:00:00" },
        { deliveryOn: "2027-02-04", startsAt: "07:30:00", endsAt: "09:00:00" },
      ]),
    ).toEqual([
      "Mittwoch, 3. Februar 2027, 7–13 Uhr",
      "Donnerstag, 4. Februar 2027, 7:30–11 Uhr",
    ]);
    expect(deliveryDays([])).toEqual([]);
  });
});
