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
