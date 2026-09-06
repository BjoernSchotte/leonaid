import { Model } from "survey-core";

/** Add profile checks that native input limits alone cannot guarantee. */
export function createSurveyModel(definition: Record<string, unknown>): Model {
  const model = new Model(structuredClone(definition));
  model.onValidateQuestion.add((_, options) => {
    const question = options.question;
    const value = options.value;
    if (
      typeof value === "string" &&
      ["text", "comment"].includes(question.getType())
    ) {
      const maximum = question.getPropertyValue("maxLength", 0);
      if (maximum > 0 && value.length > maximum)
        options.error = `Bitte geben Sie höchstens ${maximum} Zeichen ein.`;
    }
    if (question.getType() === "checkbox" && Array.isArray(value)) {
      const maximum = question.getPropertyValue("maxSelectedChoices", 0);
      if (maximum > 0 && value.length > maximum)
        options.error = `Bitte wählen Sie höchstens ${maximum} Antworten aus.`;
    }
  });
  return model;
}
