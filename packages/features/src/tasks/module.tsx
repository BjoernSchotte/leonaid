import { lazy, Suspense } from "react";

import { Plus } from "lucide-react";

import { createHref } from "../command-palette/create-request";
import type { UiModule } from "../modules";

const TasksPage = lazy(() =>
  import("./tasks").then(({ TasksPage }) => ({ default: TasksPage })),
);

function shellBase(surface: "web" | "pwa") {
  return surface === "web" ? "/admin" : "/app";
}

export const tasksModule: UiModule = {
  id: "tasks",
  label: "Aufgaben",
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
        // "Alle" also holds done tasks, so every hit opens in the pane.
        href: `${shellBase(surface)}/tasks/${task.listId}?view=all&open=${task.id}`,
      }));
    },
  },
  creates: [
    {
      id: "create:task",
      label: "Aufgabe anlegen",
      icon: Plus,
      href: (surface) => createHref(`${shellBase(surface)}/tasks`, "task"),
    },
  ],
  routes: [
    {
      pattern: /^\/tasks(?:\/([0-9a-f-]{36}))?$/,
      render: (context, match, surface) => (
        <Suspense fallback={<p role="status">Aufgaben werden geladen …</p>}>
          <TasksPage
            {...context}
            basePath={`${shellBase(surface)}/tasks`}
            listId={match[1]}
            surface={surface}
          />
        </Suspense>
      ),
    },
  ],
};
