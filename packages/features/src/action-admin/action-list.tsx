import { ChevronRight, HandHeart, Plus } from "lucide-react";

import type { CurrentIdentityResponse } from "@leonaid/api-client";
import { Button, buttonClassName } from "@leonaid/ui";

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
        <a
          className={buttonClassName({ variant: "primary" })}
          href="/admin/actions/new"
        >
          <Plus aria-hidden="true" size={18} />
          <span>Neue Aktion</span>
        </a>
      </header>

      {actions.length === 0 ? (
        <section className="action-empty" data-testid="action-list">
          <HandHeart aria-hidden="true" size={30} />
          <h2>Noch keine verwaltete Aktion</h2>
          <p>
            Sobald Sie einer Charity-Aktion als Admin zugeordnet sind, erscheint
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
                <HandHeart aria-hidden="true" size={22} />
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
                <ChevronRight aria-hidden="true" size={18} />
              </a>
            </article>
          ))}
        </section>
      )}
    </div>
  );
}
