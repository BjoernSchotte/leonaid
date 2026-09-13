import { validateUiModules } from "./modules";
import { surveysModule } from "./surveys/module";

// Shells compose the same module contributions; navigation is authorized by Core.
export const registeredModules = [surveysModule] as const;
validateUiModules(registeredModules);
