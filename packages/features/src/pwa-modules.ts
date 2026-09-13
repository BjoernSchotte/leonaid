import { validateUiModules } from "./modules";
import { tasksModule } from "./tasks/module";

// Only contributions shipped in the mobile shell.
export const registeredPwaModules = [tasksModule] as const;
validateUiModules(registeredPwaModules);
