import { validateUiModules, type UiModule } from "@leonaid/features";
import { surveysModule } from "@leonaid/features/surveys";
import { tasksModule } from "@leonaid/features/tasks";

// The web shell composes these contributions; Core authorizes navigation.
export const webModules: readonly UiModule[] = [surveysModule, tasksModule];
validateUiModules(webModules);
