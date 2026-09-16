import { lazy, Suspense } from "react";
import type { UiModule } from "../modules";
const MaterialsPage = lazy(() =>
  import("./materials").then(({ MaterialsPage }) => ({
    default: MaterialsPage,
  })),
);
export const materialsModule: UiModule = {
  id: "materials",
  area: "work",
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
        href: `/${surface === "web" ? "admin" : "app"}/materials/${material.id}`,
      }));
    },
  },
  routes: [
    {
      pattern: /^\/(admin|app)\/materials(?:\/([0-9a-f-]{36}))?\/?$/,
      render: (context, match) => (
        <Suspense fallback={<p role="status">Materialien werden geladen …</p>}>
          <MaterialsPage
            {...context}
            basePath={`/${match[1]}/materials`}
            materialId={match[2]}
          />
        </Suspense>
      ),
    },
  ],
};
