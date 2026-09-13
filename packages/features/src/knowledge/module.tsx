import { lazy, Suspense } from "react";
import type { UiModule } from "../modules";

const KnowledgePage = lazy(() =>
  import("./knowledge").then(({ KnowledgePage }) => ({
    default: KnowledgePage,
  })),
);

export const knowledgeModule: UiModule = {
  id: "knowledge",
  area: "work",
  surfaces: ["web", "pwa"],
  routes: [
    {
      pattern: /^\/(admin|app)\/knowledge\/?$/,
      render: (context) => (
        <Suspense fallback={<p role="status">Wissen wird geladen …</p>}>
          <KnowledgePage {...context} />
        </Suspense>
      ),
    },
  ],
};
