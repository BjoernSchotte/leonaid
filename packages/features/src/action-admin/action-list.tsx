import {
  Add01Icon,
  ArrowRight01Icon,
  CharityIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";

import type { CurrentIdentityResponse } from "@leonaid/api-client";
import { Button } from "@leonaid/ui";

export interface ActionListPageProps {
  readonly identity: CurrentIdentityResponse;
}

export function ActionListPage({ identity }: ActionListPageProps) {
  const actions = [
    ...new Map(
      identity.actionMemberships
        .filter((item) => item.role === "charity_admin")
        .map((item) => [item.actionId, item]),
    ).values(),
  ];

  return (
    <div className="action-page">
      <header className="action-page__header">
        <div>
          <p className="action-page__eyebrow">Charity-Aktionen</p>
          <h1>Aktionen verwalten</h1>
          <p>
            Pflege Laufzeit, Ziel, Begünstigte, Verantwortliche und
            Veröffentlichung an einem Ort.
          </p>
        </div>
        <a className="ui-button ui-button--primary" href="/admin/actions/new">
          <HugeiconsIcon
            aria-hidden="true"
            icon={Add01Icon}
            size={18}
            strokeWidth={1.8}
          />
          <span>Neue Aktion</span>
        </a>
      </header>

      {actions.length === 0 ? (
        <section className="action-empty" data-testid="action-list">
          <HugeiconsIcon
            aria-hidden="true"
            icon={CharityIcon}
            size={30}
            strokeWidth={1.5}
          />
          <h2>Noch keine verwaltete Aktion</h2>
          <p>
            Sobald du einer Charity-Aktion als Admin zugeordnet bist, erscheint
            sie hier.
          </p>
        </section>
      ) : (
        <section
          aria-label="Verwaltete Charity-Aktionen"
          className="action-card-grid"
          data-testid="action-list"
        >
          {actions.map((action) => (
            <article className="action-card" key={action.actionId}>
              <div className="action-card__icon" aria-hidden="true">
                <HugeiconsIcon icon={CharityIcon} size={22} strokeWidth={1.7} />
              </div>
              <div>
                <p>Charity-Aktion</p>
                <h2>{action.actionName}</h2>
                <span>{action.roleLabel}</span>
              </div>
              <a
                aria-label={`${action.actionName} verwalten`}
                className="action-card__link"
                href={`/admin/actions/${action.actionId}`}
              >
                Verwalten
                <HugeiconsIcon
                  aria-hidden="true"
                  icon={ArrowRight01Icon}
                  size={18}
                  strokeWidth={1.8}
                />
              </a>
            </article>
          ))}
        </section>
      )}
    </div>
  );
}
