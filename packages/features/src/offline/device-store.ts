/*
 * Device storage of the acquisition PWA (specs/pwa-offline-queue §8.3): one
 * IndexedDB database per signed-in user, `leonaid-pwa-v1-<userId>`, with the
 * stores `queue`, `cache` and `meta`. Every value is sealed with the user's
 * non-extractable device key (crypto.ts); only ids, states, numbers and
 * times stay in clear text as index values. A small `localStorage` record
 * names the user whose database is current; it holds the user id only.
 */
import {
  createDeviceKey,
  isSealedValue,
  seal,
  unseal,
  type SealedValue,
} from "./crypto";

export const DATABASE_PREFIX = "leonaid-pwa-v1-";
export const ACTIVE_USER_KEY = "leonaid-pwa-active-user";
const DATABASE_VERSION = 1;
const KEY_RECORD = "device-key";
const USER_ID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type CacheKind = "board" | "capture";

export interface CacheEntryInfo {
  readonly kind: CacheKind;
  readonly actionId: string;
  readonly fetchedAt: string;
}

export interface CachedValue<T> {
  readonly value: T;
  readonly fetchedAt: string;
}

/** Clear-text part of a queue record: ids, state and numbers only. */
export interface QueueIndex {
  readonly entryId: string;
  readonly state: string;
  readonly actionId: string;
  readonly sequence: number;
  readonly dependsOn: string;
}

interface CacheRecord {
  readonly id: string;
  readonly fetchedAt: string;
  readonly sealed: SealedValue;
}

interface MetaRecord {
  readonly name: string;
  readonly sealed?: SealedValue;
  readonly key?: CryptoKey;
}

interface QueueRecord extends QueueIndex {
  readonly sealed: SealedValue;
}

export function databaseName(userId: string): string {
  if (!USER_ID.test(userId)) {
    throw new Error("LeonAid device storage needs a user id");
  }
  return `${DATABASE_PREFIX}${userId.toLowerCase()}`;
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () =>
      reject(transaction.error ?? new Error("IndexedDB transaction aborted"));
  });
}

function openDatabase(name: string): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(name, DATABASE_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains("queue")) {
        const queue = database.createObjectStore("queue", {
          keyPath: "entryId",
        });
        queue.createIndex("state", "state");
        queue.createIndex("actionId", "actionId");
        queue.createIndex("sequence", "sequence", { unique: true });
        queue.createIndex("dependsOn", "dependsOn");
      }
      if (!database.objectStoreNames.contains("cache")) {
        const cache = database.createObjectStore("cache", { keyPath: "id" });
        cache.createIndex("fetchedAt", "fetchedAt");
      }
      if (!database.objectStoreNames.contains("meta")) {
        database.createObjectStore("meta", { keyPath: "name" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () =>
      reject(new Error("LeonAid device storage is blocked by another tab"));
  });
}

function deleteDatabase(name: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.deleteDatabase(name);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
    // Another tab still holds it open; it closes on `versionchange`, and
    // the deletion completes then.
    request.onblocked = () => undefined;
  });
}

function cacheId(kind: CacheKind, actionId: string) {
  return `${kind}:${actionId}`;
}

/** Whether this browser has what the device storage needs. */
export function deviceStorageAvailable(): boolean {
  return (
    typeof indexedDB !== "undefined" &&
    typeof crypto !== "undefined" &&
    typeof crypto.subtle !== "undefined"
  );
}

export class DeviceStore {
  readonly userId: string;
  readonly #database: IDBDatabase;
  readonly #key: CryptoKey;

  private constructor(userId: string, database: IDBDatabase, key: CryptoKey) {
    this.userId = userId;
    this.#database = database;
    this.#key = key;
    // A deletion from another tab (sign-out, account switch) wins. A page
    // kept in the back-forward cache closes its connection when it is
    // hidden, so it never blocks such a deletion.
    database.onversionchange = () => database.close();
    window.addEventListener("pagehide", () => database.close(), {
      once: true,
    });
  }

  /** Opens the user's database and creates its device key once. */
  static async open(userId: string): Promise<DeviceStore> {
    const database = await openDatabase(databaseName(userId));
    try {
      const existing = (await requestResult(
        database.transaction("meta").objectStore("meta").get(KEY_RECORD),
      )) as MetaRecord | undefined;
      let key = existing?.key;
      if (!(key instanceof CryptoKey)) {
        // An await on WebCrypto inside a transaction lets it auto-commit;
        // the key is created first and written in its own transaction,
        // which re-checks for a key another tab wrote meanwhile.
        key = await createDeviceKey();
        const write = database.transaction("meta", "readwrite");
        const store = write.objectStore("meta");
        const raced = (await requestResult(store.get(KEY_RECORD))) as
          | MetaRecord
          | undefined;
        if (raced?.key instanceof CryptoKey) {
          key = raced.key;
        } else {
          store.put({ name: KEY_RECORD, key } satisfies MetaRecord);
        }
        await transactionDone(write);
      }
      return new DeviceStore(userId, database, key);
    } catch (error) {
      database.close();
      throw error;
    }
  }

  close() {
    this.#database.close();
  }

  async getMeta<T>(name: string): Promise<T | undefined> {
    const record = (await requestResult(
      this.#database.transaction("meta").objectStore("meta").get(name),
    )) as MetaRecord | undefined;
    if (!record?.sealed) return undefined;
    return unseal<T>(this.#key, `meta:${name}`, record.sealed);
  }

  async putMeta(name: string, value: unknown): Promise<void> {
    if (name === KEY_RECORD) throw new Error("Reserved meta record");
    const sealed = await seal(this.#key, `meta:${name}`, value);
    const transaction = this.#database.transaction("meta", "readwrite");
    transaction.objectStore("meta").put({ name, sealed } satisfies MetaRecord);
    await transactionDone(transaction);
  }

  async deleteMeta(name: string): Promise<void> {
    if (name === KEY_RECORD) throw new Error("Reserved meta record");
    const transaction = this.#database.transaction("meta", "readwrite");
    transaction.objectStore("meta").delete(name);
    await transactionDone(transaction);
  }

  async getCache<T>(
    kind: CacheKind,
    actionId: string,
  ): Promise<CachedValue<T> | undefined> {
    const id = cacheId(kind, actionId);
    const record = (await requestResult(
      this.#database.transaction("cache").objectStore("cache").get(id),
    )) as CacheRecord | undefined;
    if (!record || !isSealedValue(record.sealed)) return undefined;
    const value = await unseal<T>(this.#key, `cache:${id}`, record.sealed);
    return { value, fetchedAt: record.fetchedAt };
  }

  /** Replaces the document of one kind and action as a whole (§8.2). */
  async putCache(
    kind: CacheKind,
    actionId: string,
    value: unknown,
    fetchedAt: string,
  ): Promise<void> {
    const id = cacheId(kind, actionId);
    const sealed = await seal(this.#key, `cache:${id}`, value);
    const transaction = this.#database.transaction("cache", "readwrite");
    transaction
      .objectStore("cache")
      .put({ id, fetchedAt, sealed } satisfies CacheRecord);
    await transactionDone(transaction);
  }

  async deleteCache(kind: CacheKind, actionId: string): Promise<void> {
    const transaction = this.#database.transaction("cache", "readwrite");
    transaction.objectStore("cache").delete(cacheId(kind, actionId));
    await transactionDone(transaction);
  }

  async listCache(): Promise<CacheEntryInfo[]> {
    const records = (await requestResult(
      this.#database.transaction("cache").objectStore("cache").getAll(),
    )) as CacheRecord[];
    return records.flatMap((record) => {
      const separator = record.id.indexOf(":");
      const kind = record.id.slice(0, separator);
      if (kind !== "board" && kind !== "capture") return [];
      return [
        {
          kind,
          actionId: record.id.slice(separator + 1),
          fetchedAt: record.fetchedAt,
        },
      ];
    });
  }

  async clearCache(): Promise<void> {
    const transaction = this.#database.transaction("cache", "readwrite");
    transaction.objectStore("cache").clear();
    await transactionDone(transaction);
  }

  /* ---------- queue (stage 3) ---------- */

  async queueRecords<T>(): Promise<{ index: QueueIndex; value: T }[]> {
    const records = (await requestResult(
      this.#database
        .transaction("queue")
        .objectStore("queue")
        .index("sequence")
        .getAll(),
    )) as QueueRecord[];
    return Promise.all(
      records.map(async ({ sealed, ...index }) => ({
        index,
        value: await unseal<T>(this.#key, `queue:${index.entryId}`, sealed),
      })),
    );
  }

  async putQueueRecord(index: QueueIndex, value: unknown): Promise<void> {
    const sealed = await seal(this.#key, `queue:${index.entryId}`, value);
    const transaction = this.#database.transaction("queue", "readwrite");
    transaction
      .objectStore("queue")
      .put({ ...index, sealed } satisfies QueueRecord);
    await transactionDone(transaction);
  }

  async deleteQueueRecord(entryId: string): Promise<void> {
    const transaction = this.#database.transaction("queue", "readwrite");
    transaction.objectStore("queue").delete(entryId);
    await transactionDone(transaction);
  }

  async queueCount(): Promise<number> {
    return requestResult(
      this.#database.transaction("queue").objectStore("queue").count(),
    );
  }
}

/* ---------- active user and clearing (§8.5, D6) ---------- */

export function activeDeviceUser(): string | null {
  try {
    const value = window.localStorage.getItem(ACTIVE_USER_KEY);
    return value && USER_ID.test(value) ? value : null;
  } catch {
    return null;
  }
}

export function setActiveDeviceUser(userId: string) {
  try {
    window.localStorage.setItem(ACTIVE_USER_KEY, userId);
  } catch {
    // Without localStorage the app cannot start offline; online it works.
  }
}

export function clearActiveDeviceUser() {
  try {
    window.localStorage.removeItem(ACTIVE_USER_KEY);
  } catch {
    // Nothing to clear.
  }
}

export async function deleteDeviceStore(userId: string): Promise<void> {
  await deleteDatabase(databaseName(userId));
}

/** Names of every user database on this device. */
async function deviceDatabaseUsers(): Promise<string[]> {
  const users = new Set<string>();
  const active = activeDeviceUser();
  if (active) users.add(active.toLowerCase());
  if (typeof indexedDB.databases === "function") {
    for (const database of await indexedDB.databases()) {
      const name = database.name ?? "";
      if (name.startsWith(DATABASE_PREFIX)) {
        users.add(name.slice(DATABASE_PREFIX.length));
      }
    }
  }
  return [...users].filter((user) => USER_ID.test(user));
}

/**
 * D6: another person's data on this device is deleted without asking
 * before the signed-in user's shell renders; the sign-out warning (§12.5)
 * is the safeguard.
 */
export async function deleteOtherDeviceUsers(userId: string): Promise<void> {
  const current = userId.toLowerCase();
  const others = (await deviceDatabaseUsers()).filter(
    (user) => user !== current,
  );
  await Promise.all(others.map((user) => deleteDeviceStore(user)));
}
