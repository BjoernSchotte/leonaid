import {
  Add01Icon,
  ArrowRight02Icon,
  Mail01Icon,
  PackageAdd01Icon,
  Search01Icon,
  TelephoneIcon,
  UserMultiple02Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";

import {
  ApiError,
  type AcquisitionActivityWorkItemResponse,
  type CurrentIdentityResponse,
  type LeonAidApiClient,
  type SponsorDraftRequest,
  type SponsorMatchCandidateResponse,
  type SponsorMatchResponse,
  type SponsorResolutionResponse,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

interface SponsorWorkspaceProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

type SponsorView = "list" | "new";
type SponsorMode = "company" | "person";

const statusLabels = {
  committed: "Zusage",
  contacted: "Kontaktiert",
  declined: "Absage",
  handed_over: "Übergeben",
  open: "Offen",
} as const;

function sponsorError(error: unknown) {
  if (
    error instanceof ApiError &&
    error.detail.code === "sponsor_match_changed"
  ) {
    return "Der CRM-Bestand hat sich seit der Prüfung geändert. Prüfe den Sponsor erneut, bevor du ihn zuordnest.";
  }
  if (
    error instanceof ApiError &&
    (error.detail.code === "idempotency_conflict" ||
      error.detail.code === "sponsor_idempotency_crm_conflict")
  ) {
    return "Diese Verarbeitung passt nicht mehr zur ursprünglichen Eingabe. Brich die Prüfung ab und starte sie neu.";
  }
  if (
    error instanceof ApiError &&
    error.detail.code === "idempotency_incomplete"
  ) {
    return "Die vorherige Verarbeitung läuft noch. Versuche das Speichern gleich noch einmal.";
  }
  if (error instanceof ApiError && error.status === 403) {
    return "Du darfst in dieser Aktion keine Sponsoren übernehmen. Wähle eine eigene Aktion oder wende dich an den Charity-Admin.";
  }
  return "Der Sponsor konnte gerade nicht verarbeitet werden. Prüfe deine Verbindung und versuche es erneut.";
}

function dueLabel(item: AcquisitionActivityWorkItemResponse) {
  if (!item.dueAt) return null;
  if (item.urgency === "overdue") return "Überfällig";
  if (item.urgency === "today") return "Heute";
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "short",
    timeZone: "Europe/Berlin",
  }).format(new Date(item.dueAt));
}

function IconAction({
  children,
  href,
  icon,
  label,
}: {
  readonly children: ReactNode;
  readonly href: string;
  readonly icon: typeof Mail01Icon;
  readonly label: string;
}) {
  return (
    <a aria-label={label} className="acq-contact-action" href={href}>
      <HugeiconsIcon
        aria-hidden="true"
        icon={icon}
        size={18}
        strokeWidth={1.8}
      />
      <span>{children}</span>
    </a>
  );
}

function SponsorRow({
  actionId,
  identity,
  item,
}: {
  readonly actionId: string;
  readonly identity: CurrentIdentityResponse;
  readonly item: AcquisitionActivityWorkItemResponse;
}) {
  const others = item.assignedAcquirers.filter(
    (assignee) => assignee.userId !== identity.userId,
  );
  const due = dueLabel(item);

  return (
    <article
      className="acq-sponsor-row"
      data-party-id={item.partyId}
      data-party-kind={item.partyKind}
      data-testid="sponsor-row"
    >
      <div className="acq-sponsor-row__main">
        <div className="acq-sponsor-row__title">
          <strong>{item.partyDisplayName}</strong>
          <span data-status={item.status}>{statusLabels[item.status]}</span>
        </div>
        <p className="acq-sponsor-row__address">
          {[item.postalCode, item.city].filter(Boolean).join(" ") ||
            (item.partyKind === "person"
              ? "Privatperson"
              : "Keine Adresse hinterlegt")}
        </p>
        {item.contactName ? (
          <p className="acq-sponsor-row__contact">
            Kontakt: {item.contactName}
          </p>
        ) : null}
        {others.length > 0 ? (
          <p className="acq-sponsor-row__shared" data-testid="co-assignees">
            <HugeiconsIcon
              aria-hidden="true"
              icon={UserMultiple02Icon}
              size={17}
              strokeWidth={1.8}
            />
            Gemeinsam mit {others.map((item) => item.displayName).join(", ")}
          </p>
        ) : null}
      </div>

      <div className="acq-sponsor-row__next">
        <span>Nächster Schritt</span>
        <strong>{item.nextAction ?? "Noch nicht geplant"}</strong>
        {due ? <small data-urgency={item.urgency}>{due}</small> : null}
      </div>

      <div
        aria-label="Kontaktmöglichkeiten"
        className="acq-sponsor-row__actions"
      >
        {item.phone ? (
          <IconAction
            href={`tel:${item.phone}`}
            icon={TelephoneIcon}
            label={`${item.partyDisplayName} anrufen`}
          >
            Anrufen
          </IconAction>
        ) : null}
        {item.email ? (
          <IconAction
            href={`mailto:${item.email}`}
            icon={Mail01Icon}
            label={`E-Mail an ${item.partyDisplayName} schreiben`}
          >
            E-Mail
          </IconAction>
        ) : null}
        <a
          className="acq-contact-action"
          href={`/app/activities?view=contacts&assignment=${encodeURIComponent(item.assignmentId)}`}
        >
          <span>Aktivität</span>
          <HugeiconsIcon
            aria-hidden="true"
            icon={ArrowRight02Icon}
            size={18}
            strokeWidth={1.8}
          />
        </a>
        <a
          className="acq-contact-action acq-contact-action--next"
          href={`/app/commitments/new?action=${encodeURIComponent(actionId)}&assignment=${encodeURIComponent(item.assignmentId)}`}
        >
          <HugeiconsIcon
            aria-hidden="true"
            icon={PackageAdd01Icon}
            size={18}
            strokeWidth={1.8}
          />
          <span>Bestellung</span>
        </a>
      </div>
    </article>
  );
}

function SponsorList({
  actionId,
  identity,
  items,
  onCreate,
}: {
  readonly actionId: string;
  readonly identity: CurrentIdentityResponse;
  readonly items: ReadonlyArray<AcquisitionActivityWorkItemResponse>;
  readonly onCreate: () => void;
}) {
  const [filter, setFilter] = useState("");
  const normalized = filter.trim().toLocaleLowerCase("de-DE");
  const visible = normalized
    ? items.filter((item) =>
        [item.partyDisplayName, item.city, item.postalCode, item.contactName]
          .filter(Boolean)
          .some((value) =>
            value?.toLocaleLowerCase("de-DE").includes(normalized),
          ),
      )
    : items;

  if (items.length === 0) {
    return (
      <div className="acq-empty acq-empty--roomy" data-testid="sponsor-empty">
        <HugeiconsIcon
          aria-hidden="true"
          icon={UserMultiple02Icon}
          size={22}
          strokeWidth={1.8}
        />
        <strong>Noch kein Sponsor zugeordnet</strong>
        <span>
          Prüfe einen vorhandenen CRM-Kontakt oder lege den ersten Sponsor an.
        </span>
        <Button onClick={onCreate}>Ersten Sponsor erfassen</Button>
      </div>
    );
  }

  return (
    <>
      <div className="acq-list-toolbar">
        <label className="acq-search" htmlFor="sponsor-filter">
          <HugeiconsIcon
            aria-hidden="true"
            icon={Search01Icon}
            size={19}
            strokeWidth={1.8}
          />
          <span className="sr-only">Sponsoren filtern</span>
          <input
            id="sponsor-filter"
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Name, Ort oder PLZ suchen"
            type="search"
            value={filter}
          />
        </label>
        <span aria-live="polite" className="acq-result-count">
          {visible.length} {visible.length === 1 ? "Sponsor" : "Sponsoren"}
        </span>
      </div>
      {visible.length > 0 ? (
        <div className="acq-sponsor-list" data-testid="sponsor-list">
          {visible.map((item) => (
            <SponsorRow
              actionId={actionId}
              identity={identity}
              item={item}
              key={item.assignmentId}
            />
          ))}
        </div>
      ) : (
        <div className="acq-empty" data-testid="sponsor-filter-empty">
          <HugeiconsIcon
            aria-hidden="true"
            icon={Search01Icon}
            size={22}
            strokeWidth={1.8}
          />
          <strong>Kein passender Sponsor</strong>
          <span>Ändere den Suchbegriff oder lösche den Filter.</span>
        </div>
      )}
    </>
  );
}

function candidateAddress(candidate: SponsorMatchCandidateResponse) {
  return [candidate.postalCode, candidate.city].filter(Boolean).join(" ");
}

function MatchResult({
  currentUser,
  match,
  onCancel,
  onResolve,
  resolving,
  resolution,
  selectedId,
  setSelectedId,
}: {
  readonly currentUser: CurrentIdentityResponse;
  readonly match: SponsorMatchResponse | null;
  readonly onCancel: () => void;
  readonly onResolve: () => void;
  readonly resolving: boolean;
  readonly resolution: SponsorResolutionResponse | null;
  readonly selectedId: string;
  readonly setSelectedId: (id: string) => void;
}) {
  if (resolution) {
    const shared = [
      ...resolution.priorAssignees,
      { displayName: currentUser.displayName, userId: currentUser.userId },
    ].filter(
      (item, index, all) =>
        all.findIndex((candidate) => candidate.userId === item.userId) ===
        index,
    );
    return (
      <div className="acq-match-success" data-testid="sponsor-success">
        <strong>Zuordnung gespeichert</strong>
        <p>
          {resolution.displayName}
          {resolution.outcome === "created"
            ? " wurde neu im CRM angelegt."
            : " wurde aus dem CRM übernommen."}
        </p>
        {shared.length > 1 ? (
          <span data-testid="shared-assignees">
            Gemeinsam betreut von{" "}
            {shared.map((item) => item.displayName).join(", ")}
          </span>
        ) : null}
        <Button onClick={onCancel} variant="secondary">
          Weiteren Sponsor erfassen
        </Button>
      </div>
    );
  }

  if (!match) {
    return (
      <div className="acq-empty acq-empty--roomy">
        <HugeiconsIcon
          aria-hidden="true"
          icon={Search01Icon}
          size={22}
          strokeWidth={1.8}
        />
        <strong>Noch keine CRM-Prüfung</strong>
        <span>
          Nach der Prüfung siehst du Treffer, Zusatzdaten und vorhandene
          Akquisiteure.
        </span>
      </div>
    );
  }

  const selected = match.candidates.find(
    (candidate) => candidate.twentyId === selectedId,
  );
  const hasOtherAssignments =
    selected?.assignedAcquirers.some(
      (assignee) => assignee.userId !== currentUser.userId,
    ) ?? false;
  const title =
    match.status === "no_match"
      ? "Kein gleichnamiger Sponsor gefunden"
      : match.status === "single_match"
        ? "Ein eindeutiger Treffer"
        : "Mehrere mögliche Treffer";

  return (
    <div className="acq-match-result">
      <div className="acq-match-result__heading">
        <h2>{title}</h2>
        <span>
          {match.status === "no_match"
            ? "LeonAid kann den neuen Datensatz jetzt kontrolliert anlegen."
            : "Prüfe die Zusatzdaten, bevor du die Zuordnung bestätigst."}
        </span>
      </div>
      {match.candidates.length > 0 ? (
        <div className="acq-candidates">
          {match.candidates.map((candidate) => (
            <label className="candidate" key={candidate.twentyId}>
              <input
                checked={selectedId === candidate.twentyId}
                name="candidate"
                onChange={() => setSelectedId(candidate.twentyId)}
                type="radio"
                value={candidate.twentyId}
              />
              <span>
                <strong>{candidate.displayName}</strong>
                <small>
                  {candidateAddress(candidate) ||
                    candidate.email ||
                    "Keine Zusatzdaten"}
                </small>
                {candidate.assignedAcquirers.length > 0 ? (
                  <span className="assignment-warning">
                    Bereits betreut von{" "}
                    {candidate.assignedAcquirers
                      .map((item) => item.displayName)
                      .join(", ")}
                  </span>
                ) : (
                  <span className="acq-unassigned">Noch nicht zugeordnet</span>
                )}
              </span>
            </label>
          ))}
        </div>
      ) : null}
      <div className="acq-match-actions">
        <Button
          data-testid="sponsor-resolve"
          disabled={
            resolving ||
            (match.status !== "no_match" && selectedId.length === 0)
          }
          onClick={onResolve}
        >
          {resolving
            ? "Zuordnung wird gespeichert …"
            : match.status === "no_match"
              ? "Sponsor anlegen und mir zuordnen"
              : hasOtherAssignments
                ? "Trotzdem ebenfalls zuordnen"
                : "Diesen Sponsor mir zuordnen"}
        </Button>
        <Button
          data-testid="sponsor-cancel"
          disabled={resolving}
          onClick={onCancel}
          variant="secondary"
        >
          Prüfung abbrechen
        </Button>
      </div>
    </div>
  );
}

function SponsorCapture({
  actionId,
  client,
  identity,
  onAssigned,
}: {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
  readonly onAssigned: () => Promise<unknown>;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const [mode, setMode] = useState<SponsorMode>("company");
  const [match, setMatch] = useState<SponsorMatchResponse | null>(null);
  const [draft, setDraft] = useState<SponsorDraftRequest | null>(null);
  const [commandId, setCommandId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [resolution, setResolution] =
    useState<SponsorResolutionResponse | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const preview = useMutation({
    mutationFn: (nextDraft: SponsorDraftRequest) =>
      client.previewSponsorMatch(actionId, nextDraft),
    onSuccess: (result, nextDraft) => {
      setDraft(nextDraft);
      setMatch(result);
      setCommandId(crypto.randomUUID());
      setResolution(null);
      setSelectedId(
        result.status === "single_match"
          ? (result.candidates[0]?.twentyId ?? "")
          : "",
      );
    },
  });
  const resolve = useMutation({
    mutationFn: async () => {
      if (!draft || !match || !commandId) throw new Error("missing-match");
      const selected = match.candidates.find(
        (candidate) => candidate.twentyId === selectedId,
      );
      return client.resolveSponsorMatch(actionId, {
        commandId,
        confirmExistingAssignments:
          (selected?.assignedAcquirers.length ?? 0) > 0,
        expectedStatus: match.status,
        selectedTwentyId: selected?.twentyId ?? null,
        sponsor: draft,
      });
    },
    onSuccess: async (result) => {
      setResolution(result);
      await onAssigned();
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const optional = (name: string) => {
      const value = String(values.get(name) ?? "").trim();
      return value || null;
    };
    const givenName = optional("givenName");
    const familyName = optional("familyName");
    const email = optional("email");
    if (
      mode === "company" &&
      (givenName || familyName || email) &&
      (!givenName || !familyName)
    ) {
      setFormError(
        "Gib für den Ansprechpartner Vorname und Nachname gemeinsam an.",
      );
      return;
    }
    const nextDraft: SponsorDraftRequest =
      mode === "company"
        ? {
            city: optional("city"),
            companyName: optional("companyName"),
            email,
            familyName,
            givenName,
            postalCode: optional("postalCode"),
            streetLine1: optional("streetLine1"),
          }
        : {
            companyName: null,
            email,
            familyName,
            givenName,
          };
    setFormError(null);
    setMatch(null);
    setCommandId(null);
    setResolution(null);
    preview.mutate(nextDraft);
  }

  function resetCapture() {
    preview.reset();
    resolve.reset();
    formRef.current?.reset();
    setDraft(null);
    setMatch(null);
    setCommandId(null);
    setSelectedId("");
    setResolution(null);
    setFormError(null);
  }

  const formLocked =
    preview.isPending ||
    resolve.isPending ||
    match !== null ||
    resolution !== null;

  return (
    <div className="acq-capture-layout">
      <section aria-labelledby="sponsor-form-heading" className="acq-workflow">
        <div className="acq-section-heading">
          <span aria-hidden="true" className="acq-section-heading__icon">
            <HugeiconsIcon icon={Add01Icon} size={20} strokeWidth={1.8} />
          </span>
          <div>
            <h2 id="sponsor-form-heading">Wen möchtest du ansprechen?</h2>
            <p>
              Firma ist der führende Matchschlüssel. Ohne Firma werden Vor- und
              Nachname verwendet.
            </p>
          </div>
        </div>
        <form
          className="acq-form"
          id="sponsor-form"
          onSubmit={submit}
          ref={formRef}
        >
          <fieldset className="acq-capture-fields" disabled={formLocked}>
            <legend className="sr-only">Sponsor-Daten</legend>
            <div
              aria-label="Sponsorart"
              className="acq-segment acq-field--wide"
              role="group"
            >
              <button
                aria-pressed={mode === "company"}
                onClick={() => setMode("company")}
                type="button"
              >
                Firma
              </button>
              <button
                aria-pressed={mode === "person"}
                onClick={() => setMode("person")}
                type="button"
              >
                Privatperson
              </button>
            </div>
            {mode === "company" ? (
              <div className="acq-field acq-field--wide">
                <label htmlFor="sponsor-company">Firmenname</label>
                <p id="sponsor-company-help">
                  Der offizielle oder im Alltag verwendete Firmenname. LeonAid
                  nutzt ihn für die CRM-Prüfung.
                </p>
                <input
                  aria-describedby="sponsor-company-help"
                  data-testid="sponsor-company"
                  id="sponsor-company"
                  maxLength={300}
                  name="companyName"
                  placeholder="Musterbetrieb GmbH"
                  required
                />
              </div>
            ) : null}
            <div className="acq-field">
              <label htmlFor="sponsor-given-name">
                Vorname{mode === "company" ? " (optional)" : ""}
              </label>
              <p id="sponsor-given-name-help">
                {mode === "company"
                  ? "Ansprechpartner in der Firma; Name immer vollständig angeben."
                  : "Gemeinsam mit dem Nachnamen der CRM-Matchschlüssel."}
              </p>
              <input
                aria-describedby="sponsor-given-name-help"
                id="sponsor-given-name"
                maxLength={200}
                name="givenName"
                required={mode === "person"}
              />
            </div>
            <div className="acq-field">
              <label htmlFor="sponsor-family-name">
                Nachname{mode === "company" ? " (optional)" : ""}
              </label>
              <p id="sponsor-family-name-help">
                {mode === "company"
                  ? "Wird zusammen mit dem Vornamen als Firmenkontakt angelegt."
                  : "Erforderlich, damit die Person eindeutig geprüft werden kann."}
              </p>
              <input
                aria-describedby="sponsor-family-name-help"
                id="sponsor-family-name"
                maxLength={200}
                name="familyName"
                required={mode === "person"}
              />
            </div>
            <div className="acq-field acq-field--wide">
              <label htmlFor="sponsor-email">E-Mail (optional)</label>
              <p id="sponsor-email-help">
                Hilft beim Kontakt und bei gleichnamigen Personen; sie ist kein
                führender Matchschlüssel.
              </p>
              <input
                aria-describedby="sponsor-email-help"
                autoComplete="email"
                id="sponsor-email"
                maxLength={320}
                name="email"
                placeholder="kontakt@beispiel.de"
                type="email"
              />
            </div>
            {mode === "company" ? (
              <>
                <div className="acq-field acq-field--wide">
                  <label htmlFor="sponsor-street">Straße (optional)</label>
                  <p id="sponsor-street-help">
                    Dient zur Unterscheidung und späteren Routenplanung.
                  </p>
                  <input
                    aria-describedby="sponsor-street-help"
                    id="sponsor-street"
                    maxLength={300}
                    name="streetLine1"
                    placeholder="Musterstraße 12"
                  />
                </div>
                <div className="acq-field">
                  <label htmlFor="sponsor-postal-code">PLZ (optional)</label>
                  <p id="sponsor-postal-code-help">
                    Hilft bei Trefferprüfung und Auslieferung.
                  </p>
                  <input
                    aria-describedby="sponsor-postal-code-help"
                    id="sponsor-postal-code"
                    maxLength={40}
                    name="postalCode"
                    placeholder="80331"
                  />
                </div>
                <div className="acq-field">
                  <label htmlFor="sponsor-city">Ort (optional)</label>
                  <p id="sponsor-city-help">
                    Wird zusammen mit der PLZ im Treffer angezeigt.
                  </p>
                  <input
                    aria-describedby="sponsor-city-help"
                    id="sponsor-city"
                    maxLength={200}
                    name="city"
                    placeholder="München"
                  />
                </div>
              </>
            ) : null}
          </fieldset>
          <div className="acq-form__actions acq-field--wide">
            <Button
              data-testid="sponsor-preview"
              disabled={formLocked}
              type="submit"
            >
              {preview.isPending ? "CRM wird geprüft …" : "Im CRM prüfen"}
            </Button>
          </div>
          <div
            aria-live="polite"
            className="acq-field--wide"
            id="sponsor-status"
            role="status"
          >
            {resolution ? (
              <StatusMessage tone="success">
                {resolution.displayName} ist jetzt dir zugeordnet.
              </StatusMessage>
            ) : null}
            {formError ? (
              <StatusMessage tone="error">{formError}</StatusMessage>
            ) : null}
            {preview.isError || resolve.isError ? (
              <StatusMessage tone="error">
                {sponsorError(preview.error ?? resolve.error)}
              </StatusMessage>
            ) : null}
          </div>
        </form>
      </section>

      <section
        aria-label="Ergebnis der CRM-Prüfung"
        className="acq-match-panel"
      >
        <MatchResult
          currentUser={identity}
          match={match}
          onCancel={resetCapture}
          onResolve={() => resolve.mutate()}
          resolving={resolve.isPending}
          resolution={resolution}
          selectedId={selectedId}
          setSelectedId={setSelectedId}
        />
      </section>
    </div>
  );
}

export function SponsorWorkspace({ client, identity }: SponsorWorkspaceProps) {
  const memberships = useMemo(
    () =>
      identity.actionMemberships.filter(
        (membership) => membership.role === "acquirer",
      ),
    [identity.actionMemberships],
  );
  const [actionId, setActionId] = useState(memberships[0]?.actionId ?? "");
  const [view, setView] = useState<SponsorView>("list");
  const board = useQuery({
    enabled: Boolean(actionId),
    queryFn: () => client.getAcquisitionActivityBoard(actionId, { limit: 50 }),
    queryKey: ["acquisition-activity-board", actionId],
  });

  return (
    <div className="acq-page">
      <header className="acq-page__header acq-page__header--with-action">
        <div>
          <p className="acq-eyebrow">Sponsor-Akquise</p>
          <h1>{view === "list" ? "Meine Sponsoren" : "Sponsor erfassen"}</h1>
          <p>
            {view === "list"
              ? "Deine Zuständigkeiten, nächsten Schritte und Kontaktwege – ohne CRM-Suche."
              : "Prüfe zuerst den CRM-Bestand. LeonAid zeigt vorhandene Zuständigkeiten vor der Übernahme."}
          </p>
        </div>
        {view === "list" ? (
          <Button
            icon={
              <HugeiconsIcon
                aria-hidden="true"
                icon={Add01Icon}
                size={18}
                strokeWidth={1.9}
              />
            }
            onClick={() => setView("new")}
          >
            Sponsor erfassen
          </Button>
        ) : null}
      </header>

      <div className="acq-workspace-bar">
        <div className="acq-field acq-action-picker">
          <label htmlFor="sponsor-action">Charity-Aktion</label>
          <select
            data-testid="sponsor-action"
            id="sponsor-action"
            onChange={(event) => setActionId(event.target.value)}
            value={actionId}
          >
            {memberships.map((membership) => (
              <option key={membership.actionId} value={membership.actionId}>
                {membership.actionName}
              </option>
            ))}
          </select>
        </div>
        <div aria-label="Sponsorenansicht" className="acq-tabs" role="tablist">
          <button
            aria-selected={view === "list"}
            onClick={() => setView("list")}
            role="tab"
            type="button"
          >
            Übersicht
          </button>
          <button
            aria-selected={view === "new"}
            onClick={() => setView("new")}
            role="tab"
            type="button"
          >
            Sponsor erfassen
          </button>
        </div>
      </div>

      {view === "new" ? (
        <SponsorCapture
          actionId={actionId}
          client={client}
          identity={identity}
          key={actionId}
          onAssigned={async () => {
            await board.refetch();
          }}
        />
      ) : board.isPending ? (
        <div aria-live="polite" className="acq-skeleton" role="status">
          <span />
          <span />
          <span />
          <p className="sr-only">Sponsoren werden geladen</p>
        </div>
      ) : board.isError ? (
        <StatusMessage tone="error">
          <div>
            <strong>Sponsorenliste nicht erreichbar</strong>
            <p>
              Prüfe deine Verbindung. Bereits geöffnete Daten werden nicht
              offline verändert.
            </p>
            <Button onClick={() => void board.refetch()} variant="secondary">
              Sponsoren neu laden
            </Button>
          </div>
        </StatusMessage>
      ) : (
        <SponsorList
          actionId={actionId}
          identity={identity}
          items={board.data?.workItems ?? []}
          onCreate={() => setView("new")}
        />
      )}
    </div>
  );
}
