import { server as publicActions } from "../../../public/src/actions/index";

// Native form submissions on /campaigns/<slug>/ run the existing Core action.
// Browser RPC /_actions/* remains owned by apps/public at the reverse proxy.
// Do not add CMS persistence or a second order schema here.
export const server = {
  createPublicOrder: publicActions.createPublicOrder,
};
