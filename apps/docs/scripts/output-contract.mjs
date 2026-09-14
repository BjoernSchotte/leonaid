export function isAllowedOutput(relative) {
  if (
    [
      "404.html",
      "build-manifest.json",
      "favicon.svg",
      "index.html",
      "sitemap-0.xml",
      "sitemap-index.xml",
    ].includes(relative)
  ) {
    return true;
  }
  if (/^(?:de|en)(?:\/[a-z0-9-]+)*\/index\.html$/.test(relative)) {
    return true;
  }
  if (/^_astro\/[A-Za-z0-9._-]+\.(?:css|js|svg|woff2)$/.test(relative)) {
    return true;
  }
  return /^pagefind\/(?:fragment\/[^/]+\.pf_fragment|index\/[^/]+\.pf_index|[^/]+\.(?:css|js|json|pagefind|pf_meta))$/.test(
    relative,
  );
}
