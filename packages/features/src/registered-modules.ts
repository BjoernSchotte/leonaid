import { inboxModule } from "./inbox/module";
import { materialsModule } from "./materials/module";
import { knowledgeModule } from "./knowledge/module";
import { validateUiModules } from "./modules";
import { tasksModule } from "./tasks/module";
import { surveysModule } from "./surveys/module";

// Shells compose the same module contributions; navigation is authorized by Core.
export const registeredModules = [
  surveysModule,
  tasksModule,
  knowledgeModule,
  materialsModule,
  inboxModule,
] as const;
validateUiModules(registeredModules);
