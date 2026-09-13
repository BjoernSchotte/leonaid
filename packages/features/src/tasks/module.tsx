import { lazy, Suspense } from "react";
import type { UiModule } from "../modules";

const TasksPage = lazy(() =>
  import("./tasks").then(({ TasksPage }) => ({ default: TasksPage })),
);

export const tasksModule: UiModule = {
  id: "tasks",
  area: "work",
  surfaces: ["web", "pwa"],
  search: {
    label: "Aufgaben",
    find: async ({ client }, search, surface, signal) => {
      const result = await client.listTasks(
        { search, limit: 10, includeDeferred: true },
        { signal },
      );
      return result.items.map((task) => ({
        id: task.id,
        type: "task" as const,
        title: task.title,
        context: task.status === "done" ? "Erledigt" : "Offen",
        href: `/${surface === "web" ? "admin" : "app"}/tasks/${task.listId}?task=${task.id}`,
      }));
    },
  },
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
