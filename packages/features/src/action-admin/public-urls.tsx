import { useQuery } from "@tanstack/react-query";
import { Globe } from "lucide-react";

import type { LeonAidApiClient } from "@leonaid/api-client";
import { Badge, Icon } from "@leonaid/ui";

/**
 * The action's public addresses (specs/multi-domain §7.1, §6.6), read only:
 * domains are managed by the system administration (D5).
 */
export function ActionPublicUrls({
  actionId,
  client,
}: {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
}) {
  const urls = useQuery({
    queryFn: () => client.getActionPublicUrls(actionId),
    queryKey: ["action-public-urls", actionId],
    retry: false,
  });
  if (!urls.isSuccess) return null;
  const { canonicalUrl, editions } = urls.data;
  return (
    <section
      aria-labelledby={`public-urls-${actionId}`}
      className="stack"
      data-testid="action-public-urls"
    >
      <h3 className="small" id={`public-urls-${actionId}`}>
        <Icon icon={Globe} size={14} /> Öffentliche Adresse
      </h3>
      {canonicalUrl ? (
        <p className="small">
          <a href={canonicalUrl} rel="noreferrer" target="_blank">
            {canonicalUrl}
          </a>
        </p>
      ) : (
        <p className="small muted">
          Nicht öffentlich erreichbar: Die Aktion ist an keine aktive Domain
          gebunden.
        </p>
      )}
      {editions.length ? (
        <ul className="alias-list">
          {editions.map((edition) => (
            <li
              className="alias-row"
              key={`${edition.hostname}/${edition.segment}`}
            >
              <a className="mono alias-path" href={edition.editionUrl}>
                {edition.hostname}/{edition.segment}/
              </a>
              {edition.atRoot ? <Badge tone="ok">aktuell auf /</Badge> : null}
              {edition.isPrimary ? null : <Badge>zweite Adresse</Badge>}
              {edition.hostStatus === "active" ? null : (
                <Badge tone="warn">Domain nicht aktiv</Badge>
              )}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="small subtle">
        Domains verwaltet die System-Administration unter System › Domains.
      </p>
    </section>
  );
}
