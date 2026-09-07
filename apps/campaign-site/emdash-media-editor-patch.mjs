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
    '\treturn /* @__PURE__ */ jsx("form", {\n\t\tonSubmit: handleSubmit,\n\t\tclassName: cn("transition-all duration-300",',
    '\tconst mediaCampaign = collection === "campaign_pages" ? (isNew ? formData.action_id : item?.data?.action_id) : null;\n\treturn jsx(LeonAidMediaCampaign.Provider, { value: mediaCampaign, children: jsx("form", {\n\t\tonSubmit: handleSubmit,\n\t\tclassName: cn("transition-all duration-300",',
  );
  replace(
    "\t});\n}\nfunction ContentEditorSettingsResizeHandle({ panelId })",
    '\t}) }, mediaCampaign ?? "unbound");\n}\nfunction ContentEditorSettingsResizeHandle({ panelId })',
  );
  const pickerStart = source.indexOf("function MediaPickerModal(");
  assert.ok(pickerStart > 0);
  const pickerHeaderEnd = source.indexOf("\n", pickerStart);
  const pickerHeader = source.slice(pickerStart, pickerHeaderEnd);
  replace(
    pickerHeader,
    `${pickerHeader}\n\tconst campaign = React$1.useContext(LeonAidMediaCampaign);\n\tlocalOnly = true;\n\thideUrlInput = true;`,
  );
  replace(
    '\tconst mediaQueryKey = [\n\t\t"media",',
    '\tconst mediaQueryKey = [\n\t\t"media",\n\t\tcampaign,',
  );
  replace(
    "\t\tqueryFn: ({ pageParam }) => fetchMediaList({\n\t\t\tmimeType: filters,",
    "\t\tqueryFn: ({ pageParam }) => fetchMediaList({\n\t\t\tcampaign,\n\t\t\tmimeType: filters,",
  );
  replace(
    "mutationFn: (file) => uploadMedia(file, { fieldId }),",
    "mutationFn: (file) => uploadMedia(file, { fieldId, campaign }),",
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
    "function getMediaThumbnailUrl(originalUrl, mimeType, width = MEDIA_THUMBNAIL_WIDTH) {",
    "function getMediaThumbnailUrl(originalUrl, mimeType, width = MEDIA_THUMBNAIL_WIDTH) {\n\tif (originalUrl.startsWith(INTERNAL_MEDIA_PREFIX)) return originalUrl;",
  );
  return source;
}
