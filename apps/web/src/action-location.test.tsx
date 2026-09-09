import { act, render, screen } from "@testing-library/react";

import {
  useActionInUrl,
  useCurrentActionId,
} from "../../../packages/features/src/action-admin/action-location";

function Shell() {
  return <output data-testid="shell-action">{useCurrentActionId()}</output>;
}

function Page({ actionId }: { actionId: string }) {
  useActionInUrl(actionId);
  return null;
}

test("initial and changed page selections notify the shell without adding history", () => {
  window.history.replaceState(
    { retained: true },
    "",
    "/admin/?status=open#main",
  );
  const historyLength = window.history.length;
  const shell = render(<Shell />);
  const page = render(<Page actionId="first" />);
  expect(screen.getByTestId("shell-action").textContent).toBe("first");
  page.rerender(<Page actionId="second" />);
  expect(screen.getByTestId("shell-action").textContent).toBe("second");
  expect(window.location.search).toBe("?status=open&action=second");
  expect(window.location.hash).toBe("#main");
  expect(window.history.state).toEqual({ retained: true });
  expect(window.history.length).toBe(historyLength);

  act(() => {
    window.history.replaceState(null, "", "/admin/?action=first");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  expect(screen.getByTestId("shell-action").textContent).toBe("first");
  page.unmount();
  shell.unmount();
  window.history.replaceState(null, "", "/");
});
