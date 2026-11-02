import { validateUiModules, type UiModule } from "@leonaid/features";
import { surveysModule } from "@leonaid/features/surveys";

// The web shell composes these contributions; Core authorizes navigation.
export const webModules: readonly UiModule[] = [surveysModule];
validateUiModules(webModules);
