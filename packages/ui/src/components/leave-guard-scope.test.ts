import { describe, expect, it } from "vitest";

import { LeaveGuardRegistry } from "./leave-guard";

describe("LeaveGuardRegistry scopes", () => {
  it("answer for their own drafts and pass them on to the shell", () => {
    const shell = new LeaveGuardRegistry();
    const pane = new LeaveGuardRegistry(shell);
    const elsewhere = new LeaveGuardRegistry(shell);
    const token = {};
    pane.register(token);
    expect(pane.hasDirtyPages()).toBe(true);
    expect(elsewhere.hasDirtyPages()).toBe(false);
    expect(shell.hasDirtyPages()).toBe(true);
    pane.unregister(token);
    expect(shell.hasDirtyPages()).toBe(false);
  });

  it("see a confirmed leave of the shell", () => {
    const shell = new LeaveGuardRegistry();
    const pane = new LeaveGuardRegistry(shell);
    shell.leaving = true;
    expect(pane.leaving).toBe(true);
  });
});
