import { validateUiModules } from "./modules";
import { tasksModule } from "./tasks/module";
import { surveysModule } from "./surveys/module";

// Shells compose the same module contributions; navigation is authorized by Core.
export const registeredModules = [surveysModule, tasksModule] as const;
validateUiModules(registeredModules);
