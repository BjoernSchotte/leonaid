import type { LeonAidApiClient } from "@leonaid/api-client";

export async function downloadMaterial(
  client: LeonAidApiClient,
  version: Awaited<ReturnType<LeonAidApiClient["getMaterialVersion"]>>,
) {
  const blob = await client.downloadMaterialVersion(
    version.materialId,
    version.version,
  );
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = version.filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
