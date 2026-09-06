import { armBootstrap } from "../../apps/campaign-site/src/bootstrap-control.mjs";

if (process.argv.length !== 3)
  throw new Error("Expected designated Core System Admin UUID");
try {
  await armBootstrap("/app/bootstrap-state", process.argv[2]);
  console.log(
    "emdash-bootstrap: armed for the designated Core subject for 15 minutes",
  );
} catch {
  throw new Error(
    "Bootstrap activation denied; review durable state before retrying",
  );
}
