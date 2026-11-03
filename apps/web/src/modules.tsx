import { validateUiModules, type UiModule } from "@leonaid/features";
import { surveysModule } from "@leonaid/features/surveys";
import { inboxModule } from "@leonaid/features/inbox";
import { knowledgeModule } from "@leonaid/features/knowledge";
import { materialsModule } from "@leonaid/features/materials";
import { tasksModule } from "@leonaid/features/tasks";

// The web shell composes these contributions; Core authorizes navigation.
export const webModules: readonly UiModule[] = [
  surveysModule,
  tasksModule,
  materialsModule,
  knowledgeModule,
  inboxModule,
];
validateUiModules(webModules);
