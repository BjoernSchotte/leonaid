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

function shellBase(surface: "web" | "pwa") {
  return surface === "web" ? "/admin" : "/app";
}

export const knowledgeModule: UiModule = {
  id: "knowledge",
  label: "Wissen",
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
        href: `${shellBase(surface)}/knowledge/${page.id}`,
      }));
    },
  },
  routes: [
    {
      pattern: /^\/knowledge\/([0-9a-f-]{36})$/,
      render: (context, match, surface) => (
        <Suspense fallback={<p role="status">Seite wird geladen …</p>}>
          <KnowledgeEditorPage
            {...context}
            basePath={`${shellBase(surface)}/knowledge`}
            pageId={match[1]}
          />
        </Suspense>
      ),
    },
    {
      pattern: /^\/knowledge$/,
      render: (context, _match, surface) => (
        <Suspense fallback={<p role="status">Wissen wird geladen …</p>}>
          <KnowledgePage
            {...context}
            basePath={`${shellBase(surface)}/knowledge`}
          />
        </Suspense>
      ),
    },
  ],
};
