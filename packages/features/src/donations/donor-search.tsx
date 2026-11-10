import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import type {
  AcquisitionPartyResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, Field, Input } from "@leonaid/ui";

/** The CRM party a donor was taken from. */
export interface DonorParty {
  readonly partyKind: "company" | "person";
  readonly twentyId: string;
  readonly displayName: string;
}

const MIN_QUERY = 2;

/**
 * Looks the donor up among the sponsors of the action (the parties with an
 * assignment in it). Choosing one fills name, postal code, city and e-mail
 * and links the donation to the CRM party. The CRM read carries no street:
 * it stays to be typed.
 */
export function DonorSearch({
  actionId,
  client,
  onPick,
  onUnlink,
  party,
}: {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly onPick: (party: AcquisitionPartyResponse) => void;
  readonly onUnlink: () => void;
  readonly party: DonorParty | null;
}) {
  const [term, setTerm] = useState("");
  const [query, setQuery] = useState("");
  // Ask the server once the typing pauses.
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(term.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [term]);
  const search = useQuery({
    enabled: query.length >= MIN_QUERY,
    queryFn: () =>
      client.listAcquisitionParties(actionId, { q: query, limit: 8 }),
    queryKey: ["donor-search", actionId, query],
  });

  if (party) {
    return (
      <p className="small inv-note" data-testid="donation-donor-party">
        Mit dem CRM-Kontakt „{party.displayName}“ verknüpft.{" "}
        <Button
          data-testid="donation-donor-unlink"
          onClick={onUnlink}
          size="sm"
          variant="ghost"
        >
          Verknüpfung lösen
        </Button>
      </p>
    );
  }

  const items = query.length >= MIN_QUERY ? (search.data?.items ?? []) : [];
  return (
    <div className="stack" data-testid="donation-donor-search">
      <Field
        hint="Sponsoren dieser Aktion nach Name oder Ort. Die Auswahl füllt Name, Postleitzahl, Ort und E-Mail; die Straße tragen Sie selbst ein."
        id="donation-donor-search"
        label="Spender im CRM suchen"
        optional
      >
        <Input
          autoComplete="off"
          data-testid="donation-donor-search-input"
          onChange={(event) => setTerm(event.target.value)}
          type="search"
          value={term}
        />
      </Field>
      {search.isError ? (
        <p className="small field-error" role="alert">
          Die Suche im CRM ist gerade nicht möglich. Tragen Sie den Spender von
          Hand ein.
        </p>
      ) : null}
      {query.length >= MIN_QUERY && search.isSuccess && items.length === 0 ? (
        <p className="small muted" data-testid="donation-donor-search-empty">
          Kein Sponsor dieser Aktion passt. Tragen Sie den Spender von Hand ein.
        </p>
      ) : null}
      {items.length > 0 ? (
        <ul
          aria-label="Gefundene Sponsoren"
          className="doc-list"
          data-testid="donation-donor-search-results"
        >
          {items.map((item) => (
            <li key={`${item.partyKind}:${item.twentyId}`}>
              <span className="grow">
                {item.displayName}
                <span className="subtle small">
                  {" "}
                  ·{" "}
                  {[item.postalCode, item.city].filter(Boolean).join(" ") ||
                    "ohne Ort"}
                </span>
              </span>
              <Button
                aria-label={`${item.displayName} als Spender übernehmen`}
                data-testid="donation-donor-pick"
                onClick={() => {
                  onPick(item);
                  setTerm("");
                }}
                size="sm"
                variant="ghost"
              >
                Übernehmen
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
