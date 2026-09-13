import { inboxModule } from "./inbox/module";
import { materialsModule } from "./materials/module";
import { knowledgeModule } from "./knowledge/module";
import { validateUiModules } from "./modules";
import { tasksModule } from "./tasks/module";

// Only contributions shipped in the mobile shell.
export const registeredPwaModules = [
  tasksModule,
  knowledgeModule,
  materialsModule,
  inboxModule,
  // The PWA links to the shared Web editor; it does not ship a second editor.
  { id: "surveys", area: "work", surfaces: ["pwa"], routes: [] },
] as const;
validateUiModules(registeredPwaModules);
