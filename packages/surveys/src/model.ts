import { Model, TextValidator } from "survey-core";
import { profileAnswerError, type ProfileQuestion } from "./answer-validation";

/** Add profile checks that native input limits alone cannot guarantee. */
export function createSurveyModel(definition: Record<string, unknown>): Model {
  const model = new Model(structuredClone(definition));
  model.clearInvisibleValues = "onHiddenContainer";
  const pages = definition.pages as Array<{
    elements: Array<ProfileQuestion & { minLength?: number }>;
  }>;
  for (const page of pages) {
    for (const source of page.elements) {
      if (["radiogroup", "dropdown", "checkbox"].includes(source.type)) {
        // SurveyJS otherwise silently clears unknown choices before validating.
        // Hidden-choice cleanup is handled explicitly below, independently.
        model.getQuestionByName(source.name).clearIfInvisible = "none";
      }
      if (source.minLength !== undefined) {
        const validator = new TextValidator();
        validator.minLength = source.minLength;
        model.getQuestionByName(source.name).validators.push(validator);
      }
    }
  }
  let cleaning = false;
  model.onValueChanged.add(() => {
    if (cleaning) return;
    cleaning = true;
    try {
      clearHiddenAnswers(model);
    } finally {
      cleaning = false;
    }
  });
  const sources = new Map(
    pages
      .flatMap((page) => page.elements)
      .map((question) => [question.name, structuredClone(question)]),
  );
  model.onValidateQuestion.add((_, options) => {
    const source = sources.get(options.question.name);
    if (source)
      options.error =
        profileAnswerError(source, model.getValue(options.question.name)) ??
        options.error;
  });
  return model;
}

/** Restore in profile order so hidden ancestors cannot reactivate later branches. */
export function restoreSurveyAnswers(
  model: Model,
  answers: Record<string, unknown>,
): void {
  const restored = structuredClone(answers);
  for (const question of model.getAllQuestions()) {
    const value = restored[question.name];
    if (
      value === null ||
      value === "" ||
      (Array.isArray(value) && !value.length)
    )
      delete restored[question.name];
  }
  model.data = restored;
  // SurveyJS defers clearing initially hidden values until completion. Our profile
  // permits only preceding-answer references, so one ordered pass reaches a fixed
  // point and matches the server's authoritative relevance cleanup.
  clearHiddenAnswers(model);
}

function clearHiddenAnswers(model: Model): void {
  for (const question of model.getAllQuestions()) {
    if (!question.isVisible || !question.page.isVisible)
      model.clearValue(question.name);
  }
}
