import assert from "node:assert/strict";

// Called only after patchEditorSource verified the exact published admin hash.
// Pass ordinary form context through React, never globals, Referer or a fetch
// interceptor. The server independently checks every campaign/media binding.
export function patchCampaignMediaEditor(source) {
  const replace = (before, after) => {
    assert.equal(
      source.split(before).length,
      2,
      "Campaign media patch seam changed",
    );
    source = source.replace(before, after);
  };
  replace(
    "function ContentEditor({ leonaidActionId,",
    "const LeonAidMediaCampaign = React$1.createContext(null);\nfunction ContentEditor({ leonaidActionId,",
  );
  replace(
    '\treturn /* @__PURE__ */ jsxs("form", {\n\t\tonSubmit: handleSubmit,\n\t\tclassName: cn("flex h-full flex-col bg-kumo-elevated",',
    '\tconst mediaCampaign = collection === "campaign_pages" ? (isNew ? formData.action_id : item?.data?.action_id) : null;\n\treturn jsx(LeonAidMediaCampaign.Provider, { value: mediaCampaign, children: jsxs("form", {\n\t\tonSubmit: handleSubmit,\n\t\tclassName: cn("flex h-full flex-col bg-kumo-elevated",',
  );
  replace(
    "\t\t]\n\t});\n}\nfunction ContentEditorSettingsResizeHandle({ panelId })",
    '\t\t]\n\t}) }, mediaCampaign ?? "unbound");\n}\nfunction ContentEditorSettingsResizeHandle({ panelId })',
  );
  const pickerStart = source.indexOf("function MediaPickerModal(");
  assert.ok(pickerStart > 0);
  const pickerHeaderEnd = source.indexOf("\n", pickerStart);
  const pickerHeader = source.slice(pickerStart, pickerHeaderEnd);
  // Campaign media is a flat, campaign-scoped library: no global folders, no
  // external providers and no URL source. The picker keeps native paging.
  replace(
    pickerHeader,
    `${pickerHeader}\n\tconst campaign = React$1.useContext(LeonAidMediaCampaign);\n\tlocalOnly = true;\n\thideUrlInput = true;\n\tif (campaign && mimeTypeFilters === void 0) mimeTypeFilters = ["image/png", "image/jpeg", "image/webp"];`,
  );
  replace(
    '\tconst localQueryKey = React$1.useMemo(() => [\n\t\t"media",\n\t\t"picker",',
    '\tconst localQueryKey = React$1.useMemo(() => [\n\t\t"media",\n\t\t"picker",\n\t\tcampaign,',
  );
  replace(
    "\t\tqueryFn: () => fetchMediaList({\n\t\t\tpage,\n\t\t\tlimit: PICKER_PAGE_SIZE,\n\t\t\tsearch: activeSearch || void 0,\n\t\t\tmimeType: effectiveMimeFilters,\n\t\t\tfolderId: activeSearch ? void 0 : folderId ?? null\n\t\t}),",
    "\t\tqueryFn: () => fetchMediaList({\n\t\t\tcampaign,\n\t\t\tpage,\n\t\t\tlimit: PICKER_PAGE_SIZE,\n\t\t\tsearch: activeSearch || void 0,\n\t\t\tmimeType: effectiveMimeFilters,\n\t\t\tfolderId: campaign || activeSearch ? void 0 : folderId ?? null\n\t\t}),",
  );
  replace(
    '\tconst showFolderResults = activeSource === "local" &&',
    '\tconst showFolderResults = !campaign && activeSource === "local" &&',
  );
  replace(
    "\t\t\titem: withLocalMediaUrl(await uploadMedia(file, {\n\t\t\t\tfieldId,\n\t\t\t\tfolderId: folderId ?? null,\n\t\t\t\tsignal\n\t\t\t}))",
    "\t\t\titem: withLocalMediaUrl(await uploadMedia(file, {\n\t\t\t\tfieldId,\n\t\t\t\tcampaign,\n\t\t\t\tfolderId: campaign ? void 0 : folderId ?? null,\n\t\t\t\tsignal\n\t\t\t}))",
  );
  replace(
    "\t\t\tonChange: (v) => onChange(v),\n\t\t\trequired: subField.required\n\t\t});\n\t\tdefault:",
    "\t\t\tonChange: (v) => onChange(v),\n\t\t\trequired: subField.required,\n\t\t\tallowedMimeTypes: subField.validation?.allowedMimeTypes\n\t\t});\n\t\tdefault:",
  );
  replace(
    "async function fetchMediaList(options) {\n\tconst params = new URLSearchParams();",
    'async function fetchMediaList(options) {\n\tconst params = new URLSearchParams();\n\tif (options?.campaign) params.set("campaign", options.campaign);',
  );
  replace(
    "const response = await apiFetch(`${API_BASE}/media/upload-url`, {",
    'const response = await apiFetch(`${API_BASE}/media/upload-url?${new URLSearchParams({ campaign: opts?.campaign ?? "" })}`, {',
  );
  // A public optimizer cannot forward the private Core session. Keep previews
  // on the authenticated endpoint; do not create a second anonymous media path.
  replace(
    "function getMediaThumbnailUrl(originalUrl, mimeType, width = MEDIA_THUMBNAIL_WIDTH, contentHash) {",
    "function getMediaThumbnailUrl(originalUrl, mimeType, width = MEDIA_THUMBNAIL_WIDTH, contentHash) {\n\tif (originalUrl.startsWith(INTERNAL_MEDIA_PREFIX)) return originalUrl;",
  );
  return source;
}
