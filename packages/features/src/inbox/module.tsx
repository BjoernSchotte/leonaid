import { lazy, Suspense } from "react";
import type { UiModule } from "../modules";

const InboxPage = lazy(() =>
  import("./inbox").then(({ InboxPage }) => ({ default: InboxPage })),
);

export const inboxModule: UiModule = {
  id: "inbox",
  area: "work",
  surfaces: ["web", "pwa"],
  routes: [
    {
      pattern: /^\/(admin|app)\/inbox(?:\/([0-9a-f-]{36}))?\/?$/,
      render: (context, match) => (
        <Suspense fallback={<p role="status">Eingänge werden geladen …</p>}>
          <InboxPage
            {...context}
            basePath={`/${match[1]}/inbox`}
            caseId={match[2]}
          />
        </Suspense>
      ),
    },
  ],
};
