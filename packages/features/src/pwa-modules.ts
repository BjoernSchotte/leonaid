import { materialsModule } from "./materials/module";
import { knowledgeModule } from "./knowledge/module";
import { validateUiModules } from "./modules";
import { tasksModule } from "./tasks/module";

// Only contributions shipped in the mobile shell.
export const registeredPwaModules = [
  tasksModule,
  knowledgeModule,
  materialsModule,
] as const;
validateUiModules(registeredPwaModules);
