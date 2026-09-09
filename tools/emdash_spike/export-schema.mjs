import { exportCampaignSchema } from "../../apps/campaign-site/src/campaign-schema.mjs";
// Deliberately no environment, database, filesystem or HTTP reads.
process.stdout.write(exportCampaignSchema());
