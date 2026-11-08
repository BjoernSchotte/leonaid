/*
 * Sponsors in the acquisition app (prototype pwa/Acquire.tsx SponsorList,
 * SponsorDetail and NewSponsor): /app/sponsors lists them, ?assignment=
 * opens one, ?view=new captures a new one with the CRM check.
 */
import {
  ArrowLeft,
  CalendarClock,
  CircleAlert,
  Mail,
  Phone,
  Search,
  ShoppingBasket,
  UserPlus,
  Users,
} from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  ApiError,
  type AcquisitionActivityBoardResponse,
  type AcquisitionActivityWorkItemResponse,
  type CurrentIdentityResponse,
  type LeonAidApiClient,
  type SponsorDraftRequest,
  type SponsorMatchResponse,
  type SponsorResolutionResponse,
} from "@leonaid/api-client";
import {
  Button,
  buttonClassName,
  EmptyState,
  Field,
  Icon,
  Input,
  StatusIcon,
  StatusMessage,
  isTypingTarget,
  useHotkeys,
} from "@leonaid/ui";

import { PendingCaptures } from "../offline/pending-captures";
import type { SponsorDraftEntry } from "../offline/queue";
import {
  useOfflineRuntime,
  useOnline,
  useQueueSnapshot,
} from "../offline/runtime";
import { OfflineSponsorDraft } from "../offline/sponsor-draft";
import { formatDateTime, relativeDay, shortDate } from "../shared/dates";
import { navigateInPage, useLocationHref } from "../shared/location";
import { ContactSheet, channelLabels, outcomeLabels } from "./contact-sheet";
import {
  ASSIGNMENT_STATUSES,
  ActionChoice,
  BoardFailed,
  BoardLoading,
  SponsorRow,
  assignmentStatusLabel,
  assignmentStatusShape,
  followInPage,
  isAssignmentStatus,
  navigateToScreen,
  otherAcquirers,
  sponsorHref,
  telHref,
  useAcquirerAction,
  useScreenHeading,
  useSponsorBoard,
  type AssignmentStatus,
} from "./pwa-common";
import { PWA_BASE } from "@leonaid/ui/base-paths";

interface SponsorWorkspaceProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

type SponsorMode = "company" | "person";

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

function listHref(actionId: string, status?: AssignmentStatus | null) {
  const query = new URLSearchParams({ action: actionId });
  if (status) query.set("status", status);
  return `${PWA_BASE}sponsors?${query.toString()}`;
}

/* ---------- Sponsor list ---------- */

function SponsorList({
  actionId,
  identity,
  items,
  status,
}: {
  readonly actionId: string;
  readonly identity: CurrentIdentityResponse;
  readonly items: ReadonlyArray<AcquisitionActivityWorkItemResponse>;
  readonly status: AssignmentStatus | null;
}) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<"mine" | "shared">("mine");
  const shared = items.filter(
    (item) => otherAcquirers(item, identity.userId).length > 0,
  );
  const normalized = query.trim().toLocaleLowerCase("de-DE");
  const rows = (scope === "shared" ? shared : items)
    .filter((item) => !status || item.status === status)
    .filter(
      (item) =>
        !normalized ||
        [item.partyDisplayName, item.contactName, item.city, item.postalCode]
          .filter(Boolean)
          .join(" ")
          .toLocaleLowerCase("de-DE")
          .includes(normalized),
    );
  const setStatus = (next: AssignmentStatus | null) =>
    navigateInPage(listHref(actionId, next), { replace: true });

  return (
    <>
      <label className="pwa-search" role="search">
        <Icon icon={Search} size={18} />
        <span className="sr-only">Sponsoren suchen</span>
        <input
          id="sponsor-filter"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Name, Kontakt oder Ort"
          type="search"
          value={query}
        />
      </label>
      <div aria-label="Nach Stand filtern" className="pwa-chips" role="group">
        <button
          aria-pressed={!status}
          className="pwa-chip"
          data-testid="sponsor-status-all"
          onClick={() => setStatus(null)}
          type="button"
        >
          Alle
        </button>
        {ASSIGNMENT_STATUSES.map((value) => (
          <button
            aria-pressed={status === value}
            className="pwa-chip"
            data-testid={`sponsor-status-${value}`}
            key={value}
            onClick={() => setStatus(status === value ? null : value)}
            type="button"
          >
            <StatusIcon
              label=""
              size={13}
              status={assignmentStatusShape[value]}
            />
            {assignmentStatusLabel[value]}
          </button>
        ))}
      </div>
      <div aria-label="Zuständigkeit" className="pwa-segment" role="group">
        <button
          aria-pressed={scope === "mine"}
          onClick={() => setScope("mine")}
          type="button"
        >
          Meine ({items.length})
        </button>
        <button
          aria-pressed={scope === "shared"}
          onClick={() => setScope("shared")}
          type="button"
        >
          Gemeinsam betreut ({shared.length})
        </button>
      </div>
      <p aria-live="polite" className="sr-only">
        {rows.length} {rows.length === 1 ? "Sponsor" : "Sponsoren"}
      </p>
      {items.length === 0 ? (
        <EmptyState
          action={
            <a
              className={buttonClassName({ variant: "primary" })}
              href={`${PWA_BASE}sponsors?action=${encodeURIComponent(actionId)}&view=new`}
              onClick={followInPage}
            >
              Ersten Sponsor erfassen
            </a>
          }
          description="Prüfe einen vorhandenen CRM-Kontakt oder lege den ersten Sponsor an."
          icon={Users}
          title="Noch kein Sponsor zugeordnet"
        />
      ) : rows.length ? (
        <ul className="pwa-list" data-testid="sponsor-list">
          {rows.map((item) => (
            <SponsorRow
              actionId={actionId}
              item={item}
              key={item.assignmentId}
              userId={identity.userId}
            />
          ))}
        </ul>
      ) : (
        <EmptyState
          action={
            <Button
              variant="secondary"
              onClick={() => {
                setQuery("");
                setScope("mine");
                setStatus(null);
              }}
            >
              Filter zurücksetzen
            </Button>
          }
          description="Passe Suche oder Filter an – oder lege den Sponsor neu an."
          icon={Search}
          title="Keine Sponsoren gefunden"
        />
      )}
    </>
  );
}

/* ---------- Sponsor detail ---------- */

function SponsorDetail({
  actionId,
  board,
  client,
  identity,
  item,
}: {
  readonly actionId: string;
  readonly board: AcquisitionActivityBoardResponse;
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
  readonly item: AcquisitionActivityWorkItemResponse | undefined;
}) {
  const [sheet, setSheet] = useState(
    () => new URLSearchParams(window.location.search).get("contact") === "1",
  );
  const heading = useScreenHeading();
  const contactButton = useRef<HTMLButtonElement>(null);
  const back = listHref(actionId);
  const orderHref = item
    ? `${PWA_BASE}commitments/new?action=${encodeURIComponent(actionId)}&assignment=${encodeURIComponent(item.assignmentId)}`
    : back;
  useHotkeys(
    [
      {
        keys: "escape",
        label: "Zurück zur Liste",
        group: "Akquise-App",
        run: () => navigateToScreen(back),
        // Esc in a field leaves the field (shell rule), not the page.
        when: () => !isTypingTarget(document.activeElement),
      },
      {
        keys: "k",
        label: "Kontaktversuch erfassen",
        group: "Akquise-App",
        run: () => setSheet(true),
        when: () => Boolean(item),
      },
      {
        keys: "b",
        label: "Bestellung erfassen",
        group: "Akquise-App",
        run: () => navigateToScreen(orderHref),
        when: () => Boolean(item),
      },
    ],
    [back, orderHref, item?.assignmentId],
  );

  if (!item) {
    return (
      <>
        <h1 className="pwa-h1" ref={heading} tabIndex={-1}>
          Sponsor nicht gefunden
        </h1>
        <EmptyState
          action={
            <a
              className={buttonClassName({ variant: "primary" })}
              href={back}
              onClick={followInPage}
            >
              Zur Liste
            </a>
          }
          description="Vielleicht wurde der Sponsor zusammengeführt oder du bist nicht mehr zuständig."
          icon={Users}
          title="Nicht mehr in deiner Liste"
        />
      </>
    );
  }

  const label = assignmentStatusLabel[item.status];
  const others = otherAcquirers(item, identity.userId);
  const phoneAllowed = item.phone && !item.suppressedChannels.includes("phone");
  const emailAllowed = item.email && !item.suppressedChannels.includes("email");
  const history = board.activities
    .filter((activity) => activity.assignmentId === item.assignmentId)
    .sort((a, b) => b.occurredAt.localeCompare(a.occurredAt));

  return (
    <>
      <a className="pwa-back" href={back} onClick={followInPage}>
        <Icon icon={ArrowLeft} size={18} /> Sponsoren
      </a>
      <header className="pwa-detail-head">
        <h1 className="pwa-h1" ref={heading} tabIndex={-1}>
          {item.partyDisplayName}
        </h1>
        <p className="pwa-detail-sub" data-status={item.status}>
          <StatusIcon
            label=""
            size={14}
            status={assignmentStatusShape[item.status]}
          />
          {label} · {item.partyKind === "company" ? "Firma" : "Privatperson"}
        </p>
        {others.length ? (
          <p className="small muted" data-testid="co-assignees">
            Gemeinsam mit {others.join(", ")}
          </p>
        ) : null}
      </header>
      <div aria-label="Kontaktmöglichkeiten" className="pwa-actions">
        {phoneAllowed ? (
          <a className="pwa-action" href={telHref(item.phone!)}>
            <Icon icon={Phone} size={20} />
            Anrufen
          </a>
        ) : null}
        {emailAllowed ? (
          <a className="pwa-action" href={`mailto:${item.email}`}>
            <Icon icon={Mail} size={20} />
            E-Mail
          </a>
        ) : null}
        <button
          className="pwa-action"
          data-testid="contact-open"
          onClick={() => setSheet(true)}
          ref={contactButton}
          type="button"
        >
          <Icon icon={CalendarClock} size={20} />
          Kontakt erfassen
        </button>
      </div>
      <a
        className={`${buttonClassName({ size: "lg", variant: "primary" })} pwa-wide`}
        data-testid="order-open"
        href={orderHref}
        onClick={followInPage}
      >
        <Icon icon={ShoppingBasket} size={18} />
        <span className="btn-label">Bestellung erfassen</span>
      </a>

      <section aria-labelledby="contact-title" className="pwa-card">
        <h2 className="pwa-h2" id="contact-title">
          Kontakt
        </h2>
        <dl className="pwa-dl">
          <div>
            <dt>Ansprechperson</dt>
            <dd>{item.contactName ?? "Nicht hinterlegt"}</dd>
          </div>
          <div>
            <dt>Telefon</dt>
            <dd className="num">{item.phone ?? "Nicht hinterlegt"}</dd>
          </div>
          <div>
            <dt>E-Mail</dt>
            <dd>{item.email ?? "Nicht hinterlegt"}</dd>
          </div>
          <div>
            <dt>Ort</dt>
            <dd>
              {[item.postalCode, item.city].filter(Boolean).join(" ") ||
                "Nicht hinterlegt"}
            </dd>
          </div>
          <div>
            <dt>Wiedervorlage</dt>
            <dd data-testid="detail-follow-up">
              {item.dueAt
                ? `${shortDate(item.dueAt)} (${relativeDay(item.dueAt)})${
                    item.nextAction ? ` · ${item.nextAction}` : ""
                  }`
                : "Keine geplant"}
            </dd>
          </div>
        </dl>
        {item.suppressedChannels.length ? (
          <p className="small muted">
            Gesperrt:{" "}
            {item.suppressedChannels
              .map((channel) =>
                channel === "email"
                  ? "E-Mail"
                  : channel === "phone"
                    ? "Telefon"
                    : "Post",
              )
              .join(", ")}
          </p>
        ) : null}
      </section>

      <PendingCaptures partyId={item.partyId} partyKind={item.partyKind} />

      <section aria-labelledby="history-title">
        <h2 className="pwa-h2" id="history-title">
          Verlauf
        </h2>
        {history.length ? (
          <ol className="timeline pwa-timeline" data-testid="activity-timeline">
            {history.map((entry) => (
              <li
                data-activity-id={entry.id}
                data-testid="activity-entry"
                key={entry.id}
              >
                <span>
                  <strong>{outcomeLabels[entry.outcome]}</strong>
                  {` · ${channelLabels[entry.channel]}`}
                  {entry.note ? ` – ${entry.note}` : ""}
                  <time dateTime={entry.occurredAt}>
                    {formatDateTime(entry.occurredAt)}
                    {entry.actorUserId === identity.userId
                      ? ""
                      : ` · ${entry.actorDisplayName}`}
                  </time>
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="small muted">Noch kein Kontakt erfasst.</p>
        )}
      </section>

      <ContactSheet
        actionId={actionId}
        client={client}
        item={item}
        onClose={() => setSheet(false)}
        returnFocus={contactButton}
        open={sheet}
      />
    </>
  );
}

/* ---------- New sponsor with CRM check ---------- */

function MatchResult({
  actionId,
  confirmed,
  currentUser,
  match,
  onCancel,
  onResolve,
  resolving,
  resolution,
  selectedId,
  setConfirmed,
  setSelectedId,
}: {
  readonly actionId: string;
  readonly currentUser: CurrentIdentityResponse;
  readonly match: SponsorMatchResponse | null;
  readonly onCancel: () => void;
  readonly onResolve: () => void;
  readonly resolving: boolean;
  readonly resolution: SponsorResolutionResponse | null;
  readonly selectedId: string;
  readonly setSelectedId: (id: string) => void;
  /** The acquirer's own "Ja, ich spreche mich … ab" (prototype). */
  readonly confirmed: boolean;
  readonly setConfirmed: (value: boolean) => void;
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
      <div className="pwa-card" data-testid="sponsor-success">
        <h2 className="pwa-h2">Zuordnung gespeichert</h2>
        <p>
          {resolution.displayName}
          {resolution.outcome === "created"
            ? " wurde neu im CRM angelegt."
            : " wurde aus dem CRM übernommen."}
        </p>
        {shared.length > 1 ? (
          <p className="small muted" data-testid="shared-assignees">
            Gemeinsam betreut von{" "}
            {shared.map((item) => item.displayName).join(", ")}
          </p>
        ) : null}
        <a
          className={`${buttonClassName({ size: "lg", variant: "primary" })} pwa-wide`}
          href={sponsorHref(actionId, resolution.assignmentId)}
          onClick={followInPage}
        >
          Zum Sponsor
        </a>
        <Button
          className="pwa-wide"
          onClick={onCancel}
          size="lg"
          variant="secondary"
        >
          Weiteren Sponsor erfassen
        </Button>
      </div>
    );
  }

  if (!match) {
    return (
      <p className="small muted">
        Noch keine CRM-Prüfung. Danach siehst du Treffer und wer den Sponsor
        schon betreut.
      </p>
    );
  }

  const selected = match.candidates.find(
    (candidate) => candidate.twentyId === selectedId,
  );
  const others =
    selected?.assignedAcquirers
      .filter((assignee) => assignee.userId !== currentUser.userId)
      .map((assignee) => assignee.displayName) ?? [];
  const hasOtherAssignments = others.length > 0;
  const title =
    match.status === "no_match"
      ? "Kein gleichnamiger Sponsor gefunden"
      : match.status === "single_match"
        ? "Ein eindeutiger Treffer"
        : "Mehrere mögliche Treffer";

  return (
    <div
      className={
        match.status === "no_match" ? "pwa-card" : "callout tone-warn pwa-match"
      }
    >
      {match.status === "no_match" ? null : (
        <Icon icon={CircleAlert} size={18} />
      )}
      <div className="stack">
        <h2 className="pwa-h2">{title}</h2>
        <p>
          {match.status === "no_match"
            ? "LeonAid kann den neuen Datensatz jetzt anlegen."
            : "Prüfe die Angaben, bevor du die Zuordnung bestätigst."}
        </p>
        {match.candidates.length > 0 ? (
          <fieldset className="pwa-fieldset">
            <legend className="sr-only">Treffer</legend>
            <div className="pwa-options">
              {match.candidates.map((candidate) => (
                <label
                  className={`pwa-option candidate${selectedId === candidate.twentyId ? " is-checked" : ""}`}
                  key={candidate.twentyId}
                >
                  <input
                    checked={selectedId === candidate.twentyId}
                    name="candidate"
                    onChange={() => setSelectedId(candidate.twentyId)}
                    type="radio"
                    value={candidate.twentyId}
                  />
                  <span className="pwa-option-text">
                    <strong>{candidate.displayName}</strong>
                    <span className="small muted">
                      {[candidate.postalCode, candidate.city]
                        .filter(Boolean)
                        .join(" ") ||
                        candidate.email ||
                        "Keine Zusatzdaten"}
                    </span>
                    {candidate.assignedAcquirers.length > 0 ? (
                      <span className="small assignment-warning">
                        Bereits betreut von{" "}
                        {candidate.assignedAcquirers
                          .map((item) => item.displayName)
                          .join(", ")}
                      </span>
                    ) : (
                      <span className="small muted">Noch nicht zugeordnet</span>
                    )}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
        ) : null}
        {hasOtherAssignments ? (
          <label className="checkbox pwa-confirm">
            <input
              checked={confirmed}
              data-testid="sponsor-confirm-shared"
              onChange={(event) => setConfirmed(event.target.checked)}
              type="checkbox"
            />
            Ja, ich spreche mich mit {others.join(", ")} ab und trage mich
            zusätzlich ein.
          </label>
        ) : null}
        <Button
          className="pwa-wide"
          data-testid="sponsor-resolve"
          disabled={
            resolving ||
            (match.status !== "no_match" && selectedId.length === 0) ||
            (hasOtherAssignments && !confirmed)
          }
          icon={UserPlus}
          loading={resolving}
          onClick={onResolve}
          size="lg"
          variant="primary"
        >
          {resolving
            ? "Zuordnung wird gespeichert …"
            : match.status === "no_match"
              ? "Sponsor anlegen"
              : hasOtherAssignments
                ? "Als weitere Akquise eintragen"
                : "Diesen Sponsor mir zuordnen"}
        </Button>
        <Button
          className="pwa-wide"
          data-testid="sponsor-cancel"
          disabled={resolving}
          onClick={onCancel}
          size="lg"
          variant="secondary"
        >
          Prüfung abbrechen
        </Button>
      </div>
    </div>
  );
}

function NewSponsor({
  actionId,
  client,
  draftEntry,
  identity,
  onAssigned,
}: {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  /** A sponsor saved offline, checked now (offline queue §10.4). */
  readonly draftEntry?: SponsorDraftEntry;
  readonly identity: CurrentIdentityResponse;
  readonly onAssigned: () => Promise<unknown>;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const { queue } = useOfflineRuntime();
  const [mode, setMode] = useState<SponsorMode>(draftEntry?.mode ?? "company");
  const [match, setMatch] = useState<SponsorMatchResponse | null>(null);
  const [draft, setDraft] = useState<SponsorDraftRequest | null>(null);
  const [commandId, setCommandId] = useState<string | null>(null);
  const [selectedId, setSelectedIdState] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  // Another candidate needs its own confirmation.
  const setSelectedId = (id: string) => {
    setSelectedIdState(id);
    setConfirmed(false);
  };
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
        // Only the acquirer's own tick confirms a shared assignment.
        confirmExistingAssignments: confirmed,
        expectedStatus: match.status,
        selectedTwentyId: selected?.twentyId ?? null,
        sponsor: draft,
      });
    },
    onSuccess: async (result) => {
      setResolution(result);
      if (draftEntry && queue) {
        // The captures of the draft take the resolved sponsor and the
        // assignment's current revision, then go out (§9.2).
        const board = await client
          .getAcquisitionActivityBoard(actionId, { limit: 100 })
          .catch(() => null);
        const assignment = board?.workItems.find(
          (item) => item.assignmentId === result.assignmentId,
        );
        await queue.resolveDraft(draftEntry.entryId, {
          assignmentId: result.assignmentId,
          displayName: result.displayName,
          partyId: result.twentyId,
          partyKind: result.partyKind,
          revision: assignment?.revision ?? 1,
        });
      }
      await onAssigned();
    },
  });
  // A draft starts its check at once, with the values saved offline.
  const started = useRef(false);
  useEffect(() => {
    if (!draftEntry || started.current) return;
    started.current = true;
    setMode(draftEntry.mode);
    preview.mutate({ ...draftEntry.request, streetLine1: null });
  }, [draftEntry]);
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
    if (mode === "company" && !optional("companyName")) {
      setFormError("Bitte den Firmennamen angeben.");
      return;
    }
    if (mode === "person" && (!givenName || !familyName)) {
      setFormError("Bitte Vor- und Nachnamen angeben.");
      return;
    }
    if (
      mode === "company" &&
      (givenName || familyName || email) &&
      (!givenName || !familyName)
    ) {
      setFormError(
        "Gib für die Ansprechperson Vorname und Nachname gemeinsam an.",
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
        : { companyName: null, email, familyName, givenName };
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
    <>
      <form
        className="stack"
        // Saved: the locked values are no unsaved input any more. During
        // match review nothing is saved yet, so leaving still asks.
        data-leave-guard={resolution ? "off" : undefined}
        id="sponsor-form"
        noValidate
        onSubmit={submit}
        ref={formRef}
      >
        <fieldset className="pwa-fieldset stack" disabled={formLocked}>
          <legend className="sr-only">Sponsor-Daten</legend>
          <div
            aria-label="Art des Sponsors"
            className="pwa-segment"
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
            <Field
              hint="So, wie die Firma im Alltag heißt. LeonAid prüft damit das CRM auf Dubletten."
              label="Firmenname"
            >
              <Input
                autoComplete="organization"
                data-testid="sponsor-company"
                id="sponsor-company"
                maxLength={300}
                defaultValue={draftEntry?.request.companyName ?? undefined}
                name="companyName"
                required
              />
            </Field>
          ) : null}
          <Field
            label={
              mode === "company" ? "Vorname der Ansprechperson" : "Vorname"
            }
            optional={mode === "company"}
          >
            <Input
              autoComplete="given-name"
              id="sponsor-given-name"
              maxLength={200}
              defaultValue={draftEntry?.request.givenName ?? undefined}
              name="givenName"
              required={mode === "person"}
            />
          </Field>
          <Field
            label={
              mode === "company" ? "Nachname der Ansprechperson" : "Nachname"
            }
            optional={mode === "company"}
          >
            <Input
              autoComplete="family-name"
              id="sponsor-family-name"
              maxLength={200}
              defaultValue={draftEntry?.request.familyName ?? undefined}
              name="familyName"
              required={mode === "person"}
            />
          </Field>
          <Field label="E-Mail" optional>
            <Input
              autoComplete="email"
              id="sponsor-email"
              maxLength={320}
              defaultValue={draftEntry?.request.email ?? undefined}
              name="email"
              type="email"
            />
          </Field>
          {mode === "company" ? (
            <>
              <Field label="Straße" optional>
                <Input
                  autoComplete="address-line1"
                  id="sponsor-street"
                  maxLength={300}
                  name="streetLine1"
                />
              </Field>
              <div className="pwa-two">
                <Field label="PLZ" optional>
                  <Input
                    autoComplete="postal-code"
                    id="sponsor-postal-code"
                    maxLength={40}
                    defaultValue={draftEntry?.request.postalCode ?? undefined}
                    name="postalCode"
                  />
                </Field>
                <Field label="Ort" optional>
                  <Input
                    autoComplete="address-level2"
                    id="sponsor-city"
                    maxLength={200}
                    defaultValue={draftEntry?.request.city ?? undefined}
                    name="city"
                  />
                </Field>
              </div>
            </>
          ) : null}
        </fieldset>
        {match || resolution ? null : (
          <Button
            className="pwa-wide"
            data-testid="sponsor-preview"
            disabled={formLocked}
            icon={Search}
            loading={preview.isPending}
            size="lg"
            type="submit"
            variant="primary"
          >
            {preview.isPending ? "CRM wird geprüft …" : "Im CRM prüfen"}
          </Button>
        )}
        <div aria-live="polite" id="sponsor-status" role="status">
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
      <section aria-label="Ergebnis der CRM-Prüfung">
        <MatchResult
          actionId={actionId}
          currentUser={identity}
          match={match}
          onCancel={resetCapture}
          onResolve={() => resolve.mutate()}
          resolving={resolve.isPending}
          resolution={resolution}
          confirmed={confirmed}
          selectedId={selectedId}
          setConfirmed={setConfirmed}
          setSelectedId={setSelectedId}
        />
      </section>
    </>
  );
}

/* ---------- Route ---------- */

export function SponsorWorkspace({ client, identity }: SponsorWorkspaceProps) {
  const { actionId, memberships, choose } = useAcquirerAction(identity);
  const heading = useScreenHeading();
  const href = useLocationHref();
  const query = new URLSearchParams(href.split("?")[1] ?? "");
  const view = query.get("view") === "new" ? "new" : "list";
  // Offline queue (§10.4): offline, "Neu" saves a draft; ?draft= checks one.
  const runtime = useOfflineRuntime();
  const online = useOnline();
  const offlineCapture = runtime.enabled && runtime.queue !== null;
  const draftId = query.get("draft");
  const draftEntry = useQueueSnapshot().entries.find(
    (entry): entry is SponsorDraftEntry =>
      entry.kind === "sponsor-draft" && entry.entryId === draftId,
  );
  const assignmentId = query.get("assignment");
  const requestedStatus = query.get("status");
  const status = isAssignmentStatus(requestedStatus) ? requestedStatus : null;
  const board = useSponsorBoard(client, actionId);
  const choice = (
    <ActionChoice
      actionId={actionId}
      memberships={memberships}
      onChange={choose}
    />
  );

  if (memberships.length === 0) {
    return (
      <EmptyState
        description="Sobald du einer Charity-Aktion als Akquisiteur zugeordnet bist, erscheinen hier deine Sponsoren."
        headingLevel={2}
        icon={Users}
        title="Noch keine Akquise-Aktion"
      />
    );
  }

  if (view === "new") {
    return (
      <>
        <h1 className="pwa-h1" ref={heading} tabIndex={-1}>
          Neuer Sponsor
        </h1>
        {choice}
        {offlineCapture && !online ? (
          <OfflineSponsorDraft actionId={actionId} client={client} />
        ) : (
          <NewSponsor
            actionId={actionId}
            client={client}
            draftEntry={draftEntry}
            identity={identity}
            // The URL's draft keeps the form mounted when the resolved
            // draft leaves the queue.
            key={`${actionId}:${draftId ?? ""}`}
            onAssigned={() => board.refetch()}
          />
        )}
      </>
    );
  }

  const content = board.isPending ? (
    <BoardLoading label="Sponsoren werden geladen" />
  ) : board.isError ? (
    <BoardFailed
      error={board.error}
      onRetry={() => void board.refetch()}
      retryLabel="Sponsoren neu laden"
      title="Sponsorenliste nicht erreichbar"
    />
  ) : null;

  if (assignmentId) {
    return (
      content ?? (
        <SponsorDetail
          actionId={actionId}
          board={board.data!}
          client={client}
          identity={identity}
          item={board.data!.workItems.find(
            (item) => item.assignmentId === assignmentId,
          )}
          key={assignmentId}
        />
      )
    );
  }

  return (
    <>
      <h1 className="pwa-h1" ref={heading} tabIndex={-1}>
        Sponsoren
      </h1>
      {choice}
      {content ?? (
        <SponsorList
          actionId={actionId}
          identity={identity}
          items={board.data!.workItems}
          status={status}
        />
      )}
    </>
  );
}
