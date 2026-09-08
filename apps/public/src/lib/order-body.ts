// Run before Astro parses an action, not in its handler (which is too late).
// Buffer only the bounded tee sibling; leave the original body for Astro.
const maximumBytes = 64 * 1024;
const bodyDeadlineMilliseconds = 4_000;

export function isOrderSubmission(request: Request) {
  if (request.method !== "POST") return false;
  const url = new URL(request.url);
  let pathname: string;
  try {
    pathname = decodeURIComponent(url.pathname);
  } catch {
    return false; // Astro owns malformed-route rejection.
  }
  return (
    url.searchParams.get("_action") === "createPublicOrder" ||
    pathname.replace(/\/$/, "") === "/_actions/createPublicOrder"
  );
}

function rejected(status: number) {
  return new Response(
    status === 408
      ? "Die Übertragung des Bestellformulars hat zu lange gedauert. Diese Anfrage wurde nicht an die Bestellverarbeitung weitergeleitet. Bitte gehe zum Formular zurück und sende es erneut."
      : "Das Bestellformular konnte nicht vollständig angenommen werden. Diese Anfrage wurde nicht an die Bestellverarbeitung weitergeleitet.",
    {
      status,
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-store",
        Connection: "close",
      },
    },
  );
}

export async function guardOrderBody(request: Request) {
  if (!isOrderSubmission(request)) return null;
  if (Number(request.headers.get("content-length")) > maximumBytes) {
    // The adapter still needs the incoming socket to write this response.
    // Connection: close releases it after the rejection has been delivered.
    return rejected(413);
  }
  const reader = request.clone().body?.getReader();
  if (!reader) return null; // Astro retains its own missing-input validation.
  let timer: ReturnType<typeof setTimeout> | undefined;
  let timedOut = false;
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      timedOut = true;
      reject(new Error("order_body_timeout"));
    }, bodyDeadlineMilliseconds);
  });
  let complete = false;
  try {
    let bytes = 0;
    while (true) {
      const { done, value } = await Promise.race([reader.read(), deadline]);
      if (done) {
        complete = true;
        return null;
      }
      bytes += value.byteLength;
      if (bytes > maximumBytes) return rejected(413);
    }
  } catch {
    return rejected(timedOut ? 408 : 400);
  } finally {
    clearTimeout(timer);
    if (complete) reader.releaseLock();
    else {
      // Do not cancel the adapter-owned original before writing the response:
      // its async iterator can destroy the same socket used for that response.
      // Do not await the tee sibling either; edge/adapter Connection: close
      // ends the incoming stream after the error has actually been delivered.
      void reader.cancel().catch(() => {});
    }
  }
}
