import { lazy, Suspense } from "react";
import type { UiModule } from "../modules";

const KnowledgePage = lazy(() =>
  import("./knowledge").then(({ KnowledgePage }) => ({
    default: KnowledgePage,
  })),
);

const KnowledgeEditorPage = lazy(() =>
  import("./editor").then(({ KnowledgeEditorPage }) => ({
    default: KnowledgeEditorPage,
  })),
);

export const knowledgeModule: UiModule = {
  id: "knowledge",
  area: "work",
  surfaces: ["web", "pwa"],
  search: {
    label: "Wissen",
    find: async ({ client, identity }, search, surface, signal) => {
      const result = await client.listKnowledgePages(
        { search, limit: 10 },
        { signal },
      );
      return result.items.map((page) => ({
        id: page.id,
        type: "knowledge-page" as const,
        title: page.title,
        context: page.actionId
          ? (identity.actionMemberships.find(
              (item) => item.actionId === page.actionId,
            )?.actionName ?? "Aktionsseite")
          : "Eigenständige Seite",
        href: `/${surface === "web" ? "admin" : "app"}/knowledge/${page.id}`,
      }));
    },
  },
  routes: [
    {
      pattern: /^\/(admin|app)\/knowledge\/([0-9a-f-]{36})\/?$/,
      render: (context, match) => (
        <Suspense fallback={<p role="status">Seite wird geladen …</p>}>
          <KnowledgeEditorPage
            {...context}
            basePath={`/${match[1]}/knowledge`}
            pageId={match[2]}
          />
        </Suspense>
      ),
    },
    {
      pattern: /^\/(admin|app)\/knowledge\/?$/,
      render: (context, match) => (
        <Suspense fallback={<p role="status">Wissen wird geladen …</p>}>
          <KnowledgePage {...context} basePath={`/${match[1]}/knowledge`} />
        </Suspense>
      ),
    },
  ],
};
