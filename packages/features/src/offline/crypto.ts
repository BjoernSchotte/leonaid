/*
 * Encryption at rest of the PWA device storage (specs/pwa-offline-queue
 * §8.4): AES-GCM-256 with a WebCrypto key created non-extractable. The key
 * lives as a CryptoKey in the user's IndexedDB `meta` store and never exists
 * as bytes in JavaScript, so a copy of the database files is useless without
 * the browser's key store. It does not protect against code running in the
 * page; CSP and the absence of third-party scripts do that.
 */

/** One encrypted value as IndexedDB keeps it. */
export interface SealedValue {
  readonly iv: Uint8Array<ArrayBuffer>;
  readonly data: ArrayBuffer;
}

const ALGORITHM = "AES-GCM";
const IV_BYTES = 12;

export function createDeviceKey(): Promise<CryptoKey> {
  return crypto.subtle.generateKey({ name: ALGORITHM, length: 256 }, false, [
    "encrypt",
    "decrypt",
  ]);
}

/**
 * `binding` names the record (store and id). It is authenticated with the
 * value, so a sealed value copied under another id fails to open.
 */
export async function seal(
  key: CryptoKey,
  binding: string,
  value: unknown,
): Promise<SealedValue> {
  const iv = crypto.getRandomValues(new Uint8Array(IV_BYTES));
  const data = await crypto.subtle.encrypt(
    {
      name: ALGORITHM,
      iv,
      additionalData: new TextEncoder().encode(binding),
    },
    key,
    new TextEncoder().encode(JSON.stringify(value)),
  );
  return { iv, data };
}

export async function unseal<T>(
  key: CryptoKey,
  binding: string,
  sealed: SealedValue,
): Promise<T> {
  const plain = await crypto.subtle.decrypt(
    {
      name: ALGORITHM,
      iv: sealed.iv,
      additionalData: new TextEncoder().encode(binding),
    },
    key,
    sealed.data,
  );
  return JSON.parse(new TextDecoder().decode(plain)) as T;
}

export function isSealedValue(value: unknown): value is SealedValue {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as SealedValue).iv instanceof Uint8Array &&
    (value as SealedValue).data instanceof ArrayBuffer
  );
}
