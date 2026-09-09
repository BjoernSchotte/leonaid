// Request-local redisplay only: never persist contact details or credentials.
const fieldLimits = {
  companyName: 300,
  givenName: 200,
  familyName: 200,
  email: 320,
  phone: 40,
  deliveryRecipientName: 300,
  deliveryStreetLine1: 300,
  deliveryPostalCode: 24,
  deliveryCity: 200,
  invoiceRecipientName: 300,
  invoiceStreetLine1: 300,
  invoicePostalCode: 24,
  invoiceCity: 200,
  invoiceEmail: 320,
  message: 1000,
} as const;
type Field = keyof typeof fieldLimits;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function readOrderRedisplay(
  request: Request,
  publicAlias: string,
) {
  if (request.method !== "POST" || request.bodyUsed) return null;
  if (Number(request.headers.get("content-length")) > 64 * 1024) return null;
  const type = request.headers
    .get("content-type")
    ?.split(";")[0]
    .trim()
    .toLowerCase();
  if (
    !type ||
    !["application/x-www-form-urlencoded", "multipart/form-data"].includes(type)
  )
    return null;
  const reader = request.clone().body?.getReader();
  if (!reader) return null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error("redisplay_timeout")), 2000);
  });
  try {
    const chunks: Uint8Array[] = [];
    let length = 0;
    while (true) {
      const { done, value } = await Promise.race([reader.read(), deadline]);
      if (done) break;
      length += value.byteLength;
      if (length > 64 * 1024) return null;
      chunks.push(value);
    }
    const body = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) {
      body.set(chunk, offset);
      offset += chunk.byteLength;
    }
    const form = await new Request(request.url, {
      method: "POST",
      headers: { "Content-Type": request.headers.get("content-type")! },
      body,
    }).formData();
    if (
      form.getAll("publicAlias").length !== 1 ||
      form.get("publicAlias") !== publicAlias
    )
      return null;
    const fields: Partial<Record<Field, string>> = {};
    for (const name of Object.keys(fieldLimits) as Field[]) {
      const values = form.getAll(name);
      if (
        values.length === 1 &&
        typeof values[0] === "string" &&
        values[0].length <= fieldLimits[name]
      )
        fields[name] = values[0];
    }
    const ids = form.getAll("offeringId");
    const values = form.getAll("quantity");
    const quantities: Record<string, number> = {};
    if (
      ids.length <= 20 &&
      ids.length === values.length &&
      new Set(ids).size === ids.length
    ) {
      ids.forEach((id, index) => {
        const value = values[index];
        if (
          typeof id === "string" &&
          uuid.test(id) &&
          typeof value === "string" &&
          /^\d{1,4}$/.test(value) &&
          Number(value) <= 5000
        )
          quantities[id] = Number(value);
      });
    }
    const command = form.get("commandId");
    return {
      fields,
      quantities,
      commandId:
        form.getAll("commandId").length === 1 &&
        typeof command === "string" &&
        uuid.test(command)
          ? command
          : undefined,
      billingSameAsDelivery:
        form.getAll("billingSameAsDelivery").length === 1 &&
        form.get("billingSameAsDelivery") === "true",
    };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
    // Cancellation of a cloned stream can wait for its other branch. Do not
    // hold the response open waiting for that unrelated consumer to finish.
    void reader.cancel().catch(() => {});
  }
}
