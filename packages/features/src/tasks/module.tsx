import { lazy, Suspense } from "react";
import type { UiModule } from "../modules";

const TasksPage = lazy(() =>
  import("./tasks").then(({ TasksPage }) => ({ default: TasksPage })),
);

export const tasksModule: UiModule = {
  id: "tasks",
  area: "work",
  surfaces: ["web", "pwa"],
  routes: [
    {
      pattern: /^\/(admin|app)\/tasks(?:\/([0-9a-f-]{36}))?\/?$/,
      render: (context, match) => (
        <Suspense fallback={<p role="status">Aufgaben werden geladen …</p>}>
          <TasksPage
            {...context}
            basePath={`/${match[1]}/tasks`}
            listId={match[2]}
          />
        </Suspense>
      ),
    },
  ],
};
