---
title: Add a campaign type
description: Publish a new campaign template as data, choose its theme, and plug in a new mechanic as a module.
docId: DOC-P040
audience: [dev]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 3ffbc7ebf669d360fb6ec7352034e4067d7eb8a4
reviewer: Björn Schotte
---

Core never branches on a campaign name. Behaviour follows the **capabilities**
of an action (`acquisition`, `offerings`, `ordering`, `invoicing`, `delivery`),
and the public look follows its **presentation theme**. A template is the data
that sets both when a charity administrator creates an action.

## Add a goods-sale template

A goods sale such as a Christmas-tree sale reuses offerings, ordering and
invoicing. It needs no code change.

1. Add an Alembic data migration (see the migration guide) that inserts one
   row into each template table for a new slug key and version `1`:
   - `action_template_version`: `template_key`, `version`, `display_name`,
     `description` and an optional `presentation_theme`.
   - `action_template_capability`: one row per capability. Add `delivery` only
     when the goods are delivered to an address; it requires `ordering`.
   - `action_template_offering`: code, name, status, `unit` (`box`, `piece`,
     `package` or `sponsoring`), `pieces_per_unit` for boxes, price and
     currency.
   - `action_template_order_form`: texts and required fields. Set
     `require_delivery_address` only together with the `delivery` capability.
2. Published versions are immutable. Change a template by inserting the next
   version; existing actions keep their snapshot.
3. Run `./leonaid test-templates`. Its contract publishes a pickup-only goods
   sale the same way and creates an action from it through the API.

The back office lists the new template in **Aktionsvorlage** from
`GET /api/v1/action-templates`. Without `delivery`, the delivery panel stays
hidden and the public order form asks only for the billing address.
Dashboards, the activity feed and order totals report `quantities` per
offering unit; the box fields remain for older clients and are deprecated.

## Add a public theme

1. Create `apps/public/src/themes/<key>/index.ts` that exports a `PublicTheme`:
   body class, site name, share image, optional campaign header, footer mode
   and optional `Intro` component.
2. Put the styles in `themes/<key>/theme.css`, import them from the theme
   module, and scope every selector under the theme body class.
3. Register the theme in `apps/public/src/themes/index.ts`. Unknown keys fall
   back to the neutral LeonAid look.
4. Set the key as `presentation_theme` on the template version. Actions copy
   it on creation and on year-to-year copies.

The CMS microsite selects its theme with the `theme` field. Its options are
part of the versioned CMS schema in `apps/campaign-site/src/campaign-schema.mjs`;
offering a new option to editors therefore needs a CMS schema version. The
campaign-site registry in `apps/campaign-site/src/themes/index.ts` is
exhaustive over the generated option type, so type checking fails until a new
option is mapped.

## Add a new mechanic

A different mechanic, such as a charity run or a raffle, is its own module.
Follow the surveys module:

- domain types and rules in `src/leonaid/domain/<module>/`,
- application services with ports in `src/leonaid/application/<module>/`,
- PostgreSQL adapters in `src/leonaid/adapters/postgres/<module>*.py` and
  tables in their own migration,
- HTTP routes in `src/leonaid/entrypoints/fastapi/<module>.py`.

If the mechanic is enabled per action, add a capability value to
`ActionCapability` and to the API schema, and gate the module on that
capability. The database CHECK constraints already reserve `event_registration`,
`tournament`, `booths` and `volunteer_shifts`; other values need a migration.
Templates can then switch the mechanic on as data.
