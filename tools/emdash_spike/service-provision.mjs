import pg from "pg";
import { Kysely } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { runMigrations } from "emdash/db";
import { provisionPostgres } from "./provision-postgres.mjs";

const admin = new pg.Pool({ connectionTimeoutMillis: 3000 });
try {
  await provisionPostgres({
    admin,
    coreDatabase: "leonaid",
    coreRole: "leonaid",
    password: process.env.CMS_POSTGRES_PASSWORD,
  });
} finally {
  await admin.end();
}
const database = new Kysely({
  dialect: createDialect({
    host: "core-postgres",
    database: "emdash",
    user: "emdash",
    password: process.env.CMS_POSTGRES_PASSWORD,
  }),
});
try {
  await runMigrations(database);
} finally {
  await database.destroy();
}
console.log(
  "emdash-service-provision: OK: dedicated credentials and migrations ready before HTTP startup",
);
