import { constants } from "node:fs";
import { lstat, open, rename, mkdir, rmdir, unlink } from "node:fs/promises";
import { join } from "node:path";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export class BootstrapDenied extends Error {
  constructor() {
    super("CMS bootstrap is not authorized");
  }
}

// The operator creates this state explicitly; HTTP never infers authorization
// from an empty DB or a missing file. State belongs to a separate durable volume.
async function readState(directory) {
  try {
    const file = await open(
      join(directory, "state.json"),
      constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK,
    );
    try {
      const stat = await file.stat();
      if (!stat.isFile() || stat.size > 1024) throw new BootstrapDenied();
      const state = JSON.parse(await file.readFile("utf8"));
      if (
        state.version !== 1 ||
        !uuid.test(state.actor ?? "") ||
        !["armed", "consumed", "complete"].includes(state.status) ||
        !Number.isSafeInteger(state.expiresAt)
      )
        throw new BootstrapDenied();
      return state;
    } finally {
      await file.close();
    }
  } catch {
    throw new BootstrapDenied();
  }
}

async function writeState(directory, state) {
  const temporary = join(directory, "state.next");
  const file = await open(temporary, "wx", 0o600);
  try {
    await file.writeFile(JSON.stringify(state));
    await file.sync();
  } finally {
    await file.close();
  }
  await rename(temporary, join(directory, "state.json"));
  const dir = await open(directory, "r");
  try {
    await dir.sync();
  } finally {
    await dir.close();
  }
}

async function locked(directory, work) {
  const lock = join(directory, "operation.lock");
  try {
    await mkdir(lock);
  } catch {
    throw new BootstrapDenied();
  }
  try {
    return await work();
  } finally {
    await rmdir(lock);
  }
}

// Operator-only. A consumed/complete state cannot be rearmed implicitly.
// Recovery requires a separate reviewed operator action, not another HTTP call.
export async function armBootstrap(directory, actor) {
  if (!uuid.test(actor)) throw new BootstrapDenied();
  await locked(directory, async () => {
    const file = await open(join(directory, "state.json"), "wx", 0o600);
    try {
      await file.writeFile(
        JSON.stringify({
          version: 1,
          status: "armed",
          actor,
          expiresAt: Date.now() + 15 * 60_000,
        }),
      );
      await file.sync();
    } finally {
      await file.close();
    }
    const dir = await open(directory, "r");
    try {
      await dir.sync();
    } finally {
      await dir.close();
    }
  });
}

// Operator-only, read-only view for pilot-cms-provision. "none" means no state
// was ever written; an unreadable or malformed state throws BootstrapDenied.
export async function inspectBootstrap(directory) {
  try {
    await lstat(join(directory, "state.json"));
  } catch (error) {
    if (error.code === "ENOENT") return { status: "none" };
    throw new BootstrapDenied();
  }
  const state = await readState(directory);
  return {
    status:
      state.status === "armed" && state.expiresAt <= Date.now()
        ? "expired"
        : state.status,
    actor: state.actor,
    expiresAt: state.expiresAt,
  };
}

// HTTP only, after a failed setup request: the upstream setup did not
// complete, so the grant returns to "armed" with its original expiry. The
// single use stays guarded by the lock and the consume-before-mutation step;
// a crash between consume and release leaves "consumed" for resetConsumed.
export async function releaseBootstrap(directory, actor) {
  await locked(directory, async () => {
    const state = await readState(directory);
    if (state.status !== "consumed" || state.actor !== actor)
      throw new BootstrapDenied();
    await writeState(directory, { ...state, status: "armed" });
  });
}

// Operator-only (cms-provision-operator.mjs complete-setup): EmDash completed
// the setup, but the grant was not marked (crash between the upstream success
// and completeBootstrap, or a reset that raced the request). The operator
// verified the completed setup and the mapped System Admin before.
export async function completeBootstrapByOperator(directory, actor) {
  if (!uuid.test(actor)) throw new BootstrapDenied();
  await locked(directory, async () => {
    let state = null;
    try {
      await lstat(join(directory, "state.json"));
      state = await readState(directory);
    } catch (error) {
      if (!(error instanceof BootstrapDenied) && error.code !== "ENOENT")
        throw new BootstrapDenied();
    }
    if (state && state.status !== "consumed") throw new BootstrapDenied();
    if (state && state.actor !== actor) throw new BootstrapDenied();
    await writeState(directory, {
      version: 1,
      status: "complete",
      actor,
      expiresAt: state?.expiresAt ?? Date.now(),
    });
  });
}

// Operator-only (cms-provision-operator.mjs reset-setup, after its checks that
// the CMS was never used): withdraw a consumed grant, back to "no grant".
export async function resetConsumedBootstrap(directory) {
  return locked(directory, async () => {
    const state = await readState(directory);
    if (state.status !== "consumed") throw new BootstrapDenied();
    await unlink(join(directory, "state.json"));
    const dir = await open(directory, "r");
    try {
      await dir.sync();
    } finally {
      await dir.close();
    }
    return state.actor;
  });
}

// Operator-only. Only an armed grant that expired unused may be replaced: no
// setup request consumed it, so nothing upstream can have changed. Consumed
// and complete states stay final.
export async function rearmExpiredBootstrap(directory, actor) {
  if (!uuid.test(actor)) throw new BootstrapDenied();
  await locked(directory, async () => {
    const state = await readState(directory);
    if (state.status !== "armed" || state.expiresAt > Date.now())
      throw new BootstrapDenied();
    await writeState(directory, {
      version: 1,
      status: "armed",
      actor,
      expiresAt: Date.now() + 15 * 60_000,
    });
  });
}

export async function requireArmedBootstrap(directory, actor) {
  const state = await readState(directory);
  if (
    state.status !== "armed" ||
    state.actor !== actor ||
    state.expiresAt <= Date.now()
  )
    throw new BootstrapDenied();
}

export async function bootstrapIsArmed(directory) {
  try {
    const state = await readState(directory);
    return state.status === "armed" && state.expiresAt > Date.now();
  } catch {
    return false;
  }
}

export async function consumeBootstrap(directory, actor) {
  await locked(directory, async () => {
    await requireArmedBootstrap(directory, actor);
    const state = await readState(directory);
    await writeState(directory, { ...state, status: "consumed" });
  });
}

export async function completeBootstrap(directory, actor) {
  await locked(directory, async () => {
    const state = await readState(directory);
    if (state.status !== "consumed" || state.actor !== actor)
      throw new BootstrapDenied();
    await writeState(directory, { ...state, status: "complete" });
  });
}

export async function requireCompletedBootstrap(directory) {
  if ((await readState(directory)).status !== "complete")
    throw new BootstrapDenied();
}
