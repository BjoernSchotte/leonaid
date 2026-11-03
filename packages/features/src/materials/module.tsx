import { lazy, Suspense } from "react";

import { Upload } from "lucide-react";

import { createHref } from "../command-palette/create-request";
import type { UiModule } from "../modules";

const MaterialsPage = lazy(() =>
  import("./materials").then(({ MaterialsPage }) => ({
    default: MaterialsPage,
  })),
);

function shellBase(surface: "web" | "pwa") {
  return surface === "web" ? "/admin" : "/app";
}

export const materialsModule: UiModule = {
  id: "materials",
  label: "Materialien",
  surfaces: ["web", "pwa"],
  search: {
    label: "Materialien",
    find: async ({ client, identity }, search, surface, signal) => {
      const result = await client.listMaterials(
        { search, limit: 10 },
        { signal },
      );
      return result.items.map((material) => ({
        id: material.id,
        type: "material" as const,
        title: material.title,
        context: material.actionId
          ? (identity.actionMemberships.find(
              (item) => item.actionId === material.actionId,
            )?.actionName ?? "Aktionsmaterial")
          : "Eigenständiges Material",
        href: `${shellBase(surface)}/materials/${material.id}`,
      }));
    },
  },
  creates: [
    {
      id: "create:material",
      label: "Material hochladen",
      icon: Upload,
      href: (surface) =>
        createHref(`${shellBase(surface)}/materials`, "material"),
    },
  ],
  routes: [
    {
      pattern: /^\/materials(?:\/([0-9a-f-]{36}))?$/,
      render: (context, match, surface) => (
        <Suspense fallback={<p role="status">Materialien werden geladen …</p>}>
          <MaterialsPage
            {...context}
            basePath={`${shellBase(surface)}/materials`}
            materialId={match[1]}
          />
        </Suspense>
      ),
    },
  ],
};
