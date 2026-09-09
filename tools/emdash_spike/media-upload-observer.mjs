// Test-only, fixed-category diagnostics. No URLs, IDs, payloads or errors leave
// the browser; in particular never log signed upload URLs or session headers.
export function mediaUploadStage(url, method) {
  const target = new URL(url);
  if (target.origin !== "https://proxy:8443") return null;
  if (target.pathname === "/_emdash/api/media/upload-url" && method === "POST")
    return "reserve";
  if (
    /^\/_emdash\/api\/media\/[0-9A-Z]+\/upload$/.test(target.pathname) &&
    method === "PUT"
  )
    return "upload";
  if (
    /^\/_emdash\/api\/media\/[0-9A-Z]+\/confirm$/.test(target.pathname) &&
    method === "POST"
  )
    return "confirm";
  return null;
}

export function observeMediaUpload(page) {
  const started = Date.now();
  const request = (value) => {
    const stage = mediaUploadStage(value.url(), value.method());
    if (stage)
      console.log(
        `media-upload: ${stage} requested; elapsedMs=${Date.now() - started}`,
      );
  };
  const response = (value) => {
    const stage = mediaUploadStage(value.url(), value.request().method());
    if (stage)
      console.log(
        `media-upload: ${stage} status=${value.status()}; elapsedMs=${Date.now() - started}`,
      );
  };
  const failed = (value) => {
    const stage = mediaUploadStage(value.url(), value.method());
    if (stage)
      console.log(
        `media-upload: ${stage} transport-failed; elapsedMs=${Date.now() - started}`,
      );
  };
  page.on("request", request);
  page.on("response", response);
  page.on("requestfailed", failed);
  return () => {
    page.off("request", request);
    page.off("response", response);
    page.off("requestfailed", failed);
  };
}
