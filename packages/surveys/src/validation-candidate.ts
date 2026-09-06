import { createSurveyModel, restoreSurveyAnswers } from "./model";
import { profileAnswerError, type ProfileQuestion } from "./answer-validation";

/** Feasibility candidate, not a public untrusted-definition API.
 * The host MUST validate the stored definition against initial-v1 first.
 * Authorization, definition selection and transaction decisions remain in the host.
 */
export function evaluateApprovedSurvey(
  definition: Record<string, unknown>,
  answers: Record<string, unknown>,
) {
  const sources = (
    definition.pages as Array<{ elements: ProfileQuestion[] }>
  ).flatMap((page) => page.elements);
  const known = new Set(sources.map((question) => question.name));
  if (Object.keys(answers).some((key) => !known.has(key)))
    throw new Error("unknown_answer");
  const model = createSurveyModel(definition);
  try {
    restoreSurveyAnswers(model, answers);
    const visible = model
      .getAllQuestions()
      .filter((question) => question.isVisible && question.page.isVisible)
      .map((question) => question.name);
    const relevant = new Set(visible);
    const partialValid = sources.every(
      (source) =>
        !relevant.has(source.name) ||
        profileAnswerError(source, model.getValue(source.name), false) ===
          undefined,
    );
    const completeValid = model.validate();
    return { partialValid, completeValid, answers: model.data, visible };
  } finally {
    model.dispose();
  }
}
