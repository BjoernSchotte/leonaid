import { lazy, Suspense } from "react";

import type { UiModule } from "../modules";

const InboxPage = lazy(() =>
  import("./inbox").then(({ InboxPage }) => ({ default: InboxPage })),
);

export const inboxModule: UiModule = {
  id: "inbox",
  label: "Eingänge",
  surfaces: ["web", "pwa"],
  routes: [
    {
      pattern: /^\/inbox(?:\/([0-9a-f-]{36}))?$/,
      render: (context, match, surface) => (
        <Suspense fallback={<p role="status">Anfragen werden geladen …</p>}>
          <InboxPage
            {...context}
            basePath={`${surface === "web" ? "/admin" : "/app"}/inbox`}
            caseId={match[1]}
            surface={surface}
          />
        </Suspense>
      ),
    },
  ],
};
