import { render, screen } from "@testing-library/react";
import type { CurrentIdentityResponse } from "@leonaid/api-client";

import {
  CampaignEditorLink,
  campaignEditorHref,
} from "../../../packages/features/src/action-admin/campaign-editor-link";

const first = "20000000-0000-4000-8000-000000000001";
const second = "20000000-0000-4000-8000-000000000002";
const identity: Pick<
  CurrentIdentityResponse,
  "globalRoles" | "actionMemberships"
> = {
  globalRoles: [],
  actionMemberships: [
    {
      actionId: first,
      actionName: "First",
      role: "charity_admin",
      roleLabel: "Charity-Admin",
    },
    {
      actionId: second,
      actionName: "Second",
      role: "finance_reader",
      roleLabel: "Finanzen",
    },
  ],
};

test("shell and contextual links share action-specific authorization", () => {
  expect(campaignEditorHref(identity, first)).toBe(
    `/_emdash/admin/campaigns/${first}`,
  );
  expect(campaignEditorHref(identity, second)).toBeUndefined();
  expect(
    campaignEditorHref(
      { ...identity, globalRoles: ["system_admin"] },
      "../new",
    ),
  ).toBeUndefined();
});

test("the selected campaign and its role determine the same-tab editor link", () => {
  const view = render(
    <CampaignEditorLink actionId={first} identity={identity} />,
  );
  const link = screen.getByRole("link", { name: "Microsite bearbeiten" });
  expect(link.getAttribute("href")).toBe(`/_emdash/admin/campaigns/${first}`);
  expect(link.hasAttribute("target")).toBe(false);

  view.rerender(<CampaignEditorLink actionId={second} identity={identity} />);
  expect(screen.queryByRole("link")).toBeNull();
  view.rerender(
    <CampaignEditorLink
      actionId={second}
      identity={{ ...identity, globalRoles: ["system_admin"] }}
    />,
  );
  expect(screen.getByRole("link").getAttribute("href")).toBe(
    `/_emdash/admin/campaigns/${second}`,
  );
  view.rerender(
    <CampaignEditorLink
      actionId=""
      identity={{ ...identity, globalRoles: ["system_admin"] }}
    />,
  );
  expect(screen.queryByRole("link")).toBeNull();
});
