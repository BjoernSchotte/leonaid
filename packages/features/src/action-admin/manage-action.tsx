import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Pencil, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  type ActionManagementResponse,
  type CharityActionResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Button,
  buttonClassName,
  DetailProps,
  ErrorState,
  Icon,
  ReadOnlyNotice,
  SkeletonRows,
  StatusIcon,
  StatusLabel,
  TabPanel,
  Tabs,
  isTypingTarget,
  useDiscardDialog,
  useHotkeys,
} from "@leonaid/ui";

import { goalText } from "./action-list";
import { shortDate } from "../shared/dates";
import {
  OffersTab,
  TemplatesTab,
  useActionConfiguration,
} from "./action-templates";
import { BuyerMailSection } from "./buyer-mail-section";
import { CampaignAliasesSection } from "./campaign-aliases";
import { ActionPublicUrls } from "./public-urls";
import { DeliverySection } from "./delivery-section";
import {
  AdministratorsSection,
  BeneficiariesSection,
  CapabilitiesSection,
  DetailsSection,
  GoalSection,
  LifecycleNextStep,
  PublicationSection,
  capabilityOptions,
  statusLabels,
  type SharedSectionProps,
} from "./manage-sections";
import { useActionErrorMessage } from "./use-action-error";
import { adminHref } from "@leonaid/ui/base-paths";

const TABS = [
  { id: "overview", label: "Überblick" },
  { id: "delivery", label: "Lieferfenster" },
  { id: "aliases", label: "Aliase" },
  { id: "templates", label: "Vorlagen" },
  { id: "offers", label: "Angebote" },
] as const;

export type ActionTab = (typeof TABS)[number]["id"];

interface Location {
  readonly tab: ActionTab;
  readonly editing: boolean;
}

/**
 * The tab lives in the hash (`#delivery`, `#overview/edit`). Old panel
 * hashes keep working: the edit forms of the former panels open the
 * overview in edit mode, "public" opens the aliases.
 */
export function actionLocation(hash: string): Location {
  const [head = "", mode] = hash.replace(/^#/, "").split("/");
  if (TABS.some((tab) => tab.id === head)) {
    return {
      tab: head as ActionTab,
      editing: head === "overview" && mode === "edit",
    };
  }
  if (
    [
      "basics",
      "details",
      "goal",
      "beneficiaries",
      "team",
      "capabilities",
      "administrators",
    ].includes(head)
  ) {
    return { tab: "overview", editing: true };
  }
  if (head === "public" || head === "publication") {
    return { tab: "aliases", editing: false };
  }
  return { tab: "overview", editing: false };
}

function locationHash({ editing, tab }: Location) {
  return editing ? "#overview/edit" : `#${tab}`;
}

function period(action: CharityActionResponse) {
  return `${shortDate(action.startsOn)} – ${shortDate(action.endsOn)}`;
}

/** Überblick, read view (prototype Campaigns.tsx Overview). */
function Overview({ state }: { readonly state: ActionManagementResponse }) {
  const action = state.action;
  const leads = state.administratorOptions
    .filter((option) => option.isResponsible)
    .map((option) => option.displayName);
  const goal = goalText(action.goal, action.goal.goalValue);
  return (
    <div className="overview" data-testid="action-overview">
      <section aria-labelledby="overview-purpose">
        <h2 className="tab-h2" id="overview-purpose">
          Zweck
        </h2>
        <p className="overview-purpose">{action.purpose}</p>
        <DetailProps
          items={[
            { label: "Zeitraum", value: period(action) },
            { label: "Träger", value: action.carrierName },
            {
              label: "Ziel",
              value: goal ? (
                <span className="num">{goal}</span>
              ) : (
                <span className="subtle">Kein Ziel</span>
              ),
            },
            {
              label: "Bisher erreicht",
              value: (
                <span className="num">
                  {goalText(action.goal, action.goal.actualValue) ?? "–"}
                </span>
              ),
            },
            {
              label: "Begünstigte",
              value: action.beneficiaries.length ? (
                action.beneficiaries
                  .map((item) => item.organizationName)
                  .join(", ")
              ) : (
                <span className="subtle">Keine</span>
              ),
            },
            {
              label: "Leitung",
              value: leads.length ? (
                leads.join(", ")
              ) : (
                <span className="subtle">Niemand</span>
              ),
            },
            {
              label: "Öffentliche Adresse",
              value: state.publicAlias ? (
                <span className="mono">/{state.publicAlias}</span>
              ) : (
                <span className="subtle">Noch keine</span>
              ),
            },
            {
              label: "Archiv-Adresse",
              value: (
                <span className="mono">/archive/{action.archiveSlug}</span>
              ),
            },
          ]}
        />
      </section>
      <section aria-labelledby="overview-capabilities">
        <h2 className="tab-h2" id="overview-capabilities">
          Funktionen dieser Aktion
        </h2>
        {action.capabilities.length ? (
          <ul className="capabilities">
            {capabilityOptions
              .filter((option) => action.capabilities.includes(option.value))
              .map((option) => (
                <li key={option.value}>
                  <StatusIcon label="Aktiv" status="done" />
                  {option.label}
                </li>
              ))}
          </ul>
        ) : (
          <p className="small subtle">Keine Funktionen gewählt.</p>
        )}
        <p className="small muted">
          Funktionen kommen aus der Vorlage. Rollen wie „Ausfahrer“ gibt es nur,
          wenn die Auslieferung aktiv ist.
        </p>
      </section>
    </div>
  );
}

export interface ManageActionPageProps {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  /** CMS editor of this action (campaignEditorHref); absent without the CMS. */
  readonly editorHref?: string | undefined;
}

/**
 * Aktion im Detail (prototype Campaigns.tsx CampaignDetail): header with
 * status, tabs Überblick, Lieferfenster, Aliase, Vorlagen and Angebote.
 * "Bearbeiten" shows the edit forms on the overview; every change goes to
 * the server with the action's revision.
 */
export function ManageActionPage({
  actionId,
  client,
  editorHref,
}: ManageActionPageProps) {
  const [location, setLocation] = useState<Location>(() =>
    actionLocation(window.location.hash),
  );
  const queryClient = useQueryClient();
  const queryKey = useMemo(
    () => ["action-management", actionId] as const,
    [actionId],
  );
  const query = useQuery({
    queryFn: () => client.getCharityActionManagement(actionId),
    queryKey,
    retry: (failureCount, error) =>
      !(error instanceof ApiError) && failureCount < 2,
    retryDelay: (attempt) => 150 * (attempt + 1),
    staleTime: 0,
  });
  const configuration = useActionConfiguration(client, actionId);
  // Same keys as the tabs' own queries: the counts cost no extra request.
  const deliveryCount = useQuery({
    enabled: query.data?.action.capabilities.includes("delivery") ?? false,
    queryKey: ["delivery-configuration", actionId],
    queryFn: () => client.getDeliveryConfiguration(actionId),
    refetchOnWindowFocus: false,
    retry: false,
  });
  const aliasCount = useQuery({
    queryKey: ["campaign-aliases", actionId],
    queryFn: () => client.listCampaignAliases(actionId),
    retry: false,
    staleTime: 0,
  });
  const errorMessage = useActionErrorMessage(query.error);

  const hasDelivery =
    query.data?.action.capabilities.includes("delivery") ?? false;
  const tabs = TABS.filter((tab) => tab.id !== "delivery" || hasDelivery);
  const current: ActionTab =
    location.tab === "delivery" && query.isSuccess && !hasDelivery
      ? "overview"
      : location.tab;
  const archived = query.data?.action.status === "archived";
  const editing = location.editing && !archived;

  // Revisions this page saved itself; a draft begun before them is current.
  const ownRevisions = useRef(new Set<number>());
  const revisionFor = useCallback((base: number) => {
    let revision = base;
    while (ownRevisions.current.has(revision + 1)) revision += 1;
    return revision;
  }, []);
  // Forms with unsaved input; leaving them asks first.
  const [dirtyForms, setDirtyForms] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const onDirty = useCallback((form: string, dirty: boolean) => {
    setDirtyForms((current) => {
      if (current.has(form) === dirty) return current;
      const next = new Set(current);
      if (dirty) next.add(form);
      else next.delete(form);
      return next;
    });
  }, []);
  const discard = useDiscardDialog("Sie");
  const locationRef = useRef(location);
  locationRef.current = location;
  const dirtyRef = useRef(dirtyForms);
  dirtyRef.current = dirtyForms;

  /** Whether leaving `from` for `to` unmounts a form with unsaved input. */
  const losesInput = (from: Location, to: Location) => {
    if (dirtyRef.current.size === 0) return false;
    if (from.tab === to.tab && from.editing === to.editing) return false;
    return true;
  };

  const go = useCallback(
    async (next: Location) => {
      const from = locationRef.current;
      if (losesInput(from, next) && !(await discard.confirmDiscard())) return;
      setLocation(next);
      // One history entry per tab, so Back steps through the tabs.
      if (locationHash(next) !== window.location.hash) {
        window.history.pushState(window.history.state, "", locationHash(next));
      }
    },
    // losesInput reads refs only.
    [discard],
  );

  const leaveToList = useCallback(async () => {
    if (dirtyRef.current.size > 0 && !(await discard.confirmDiscard())) return;
    window.location.assign(adminHref("actions"));
  }, [discard]);

  useEffect(() => {
    // Back/Forward and hash links: ask before a draft goes away; on
    // "Weiter bearbeiten" the previous hash comes back.
    const onHash = () => {
      const from = locationRef.current;
      const next = actionLocation(window.location.hash);
      if (!losesInput(from, next)) {
        setLocation(next);
        return;
      }
      void discard.confirmDiscard().then((ok) => {
        if (ok) setLocation(next);
        else
          window.history.replaceState(
            window.history.state,
            "",
            locationHash(from),
          );
      });
    };
    window.addEventListener("hashchange", onHash);
    window.addEventListener("popstate", onHash);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("popstate", onHash);
    };
  }, [discard]);

  // #delivery without the delivery capability: show and name the overview.
  useEffect(() => {
    if (location.tab === "delivery" && query.isSuccess && !hasDelivery) {
      const next = { tab: "overview", editing: false } as const;
      setLocation(next);
      window.history.replaceState(window.history.state, "", locationHash(next));
    }
  }, [location.tab, query.isSuccess, hasDelivery]);

  useHotkeys(
    [
      {
        keys: "escape",
        label: "Zurück zur Aktionsliste",
        group: "Aktion",
        // Esc in a field stays with the field (prototype: cancel typing).
        when: () => !editing && !isTypingTarget(document.activeElement),
        run: () => void leaveToList(),
      },
      ...tabs.map((tab, index) => ({
        keys: String(index + 1),
        label: `Reiter ${tab.label}`,
        group: "Aktion",
        run: () => void go({ tab: tab.id, editing: false }),
      })),
    ],
    [editing, tabs.length, go, leaveToList],
  );

  if (query.isPending) {
    return (
      <div className="campaign" aria-busy="true">
        <h1 className="sr-only">Aktion wird geladen</h1>
        <SkeletonRows rows={6} />
      </div>
    );
  }

  if (query.isError) {
    return (
      <div className="campaign">
        <nav aria-label="Brotkrumen" className="crumbs">
          <a href={adminHref("actions")}>Aktionen</a>
        </nav>
        <h1 className="sr-only">Aktion konnte nicht geladen werden</h1>
        <ErrorState
          onRetry={() => void query.refetch()}
          title="Aktion konnte nicht geladen werden"
        >
          {errorMessage?.message}
        </ErrorState>
      </div>
    );
  }

  const state = query.data;
  const action = state.action;

  function updateAction(next: CharityActionResponse) {
    queryClient.setQueryData<ActionManagementResponse>(
      queryKey,
      (existing) => existing && { ...existing, action: next },
    );
    void queryClient.invalidateQueries({ queryKey });
    ownRevisions.current.add(next.revision);
    void queryClient.invalidateQueries({
      queryKey: ["action-configuration", actionId],
    });
    // Completing or archiving removes the action's aliases on the server.
    void queryClient.invalidateQueries({
      queryKey: ["campaign-aliases", actionId],
    });
  }

  function updateState(next: ActionManagementResponse) {
    ownRevisions.current.add(next.action.revision);
    queryClient.setQueryData<ActionManagementResponse>(queryKey, next);
    // The publication sets the active alias.
    void queryClient.invalidateQueries({
      queryKey: ["campaign-aliases", actionId],
    });
  }

  const shared: SharedSectionProps = {
    client,
    disabled: archived,
    state,
    updateAction,
    updateState,
    revisionFor,
    onDirty,
  };
  const leads = state.administratorOptions
    .filter((option) => option.isResponsible)
    .map((option) => option.displayName);
  const counts: Partial<Record<ActionTab, number>> = {
    delivery: deliveryCount.data?.windows.filter((window) => !window.retired)
      .length,
    aliases: aliasCount.data?.items.length,
    offers: configuration.data?.offerings.length,
  };

  return (
    <div className="campaign" data-testid="action-detail">
      <nav aria-label="Brotkrumen" className="crumbs">
        <a href={adminHref("actions")}>Aktionen</a>
        <span aria-hidden="true">/</span>
        <span aria-current="page">{action.name}</span>
      </nav>
      <header className="page-header">
        <div>
          <div className="page-heading">
            <h1 data-testid="management-title">{action.name}</h1>
            <span data-testid="management-status">
              <StatusLabel status={statusLabels[action.status]} />
            </span>
          </div>
          <p className="page-sub">
            {action.carrierName} · {period(action)}
            {leads.length ? ` · Leitung ${leads.join(", ")}` : ""}
          </p>
        </div>
        <div className="page-actions">
          {editorHref ? (
            <a
              className={buttonClassName({ variant: "ghost" })}
              href={editorHref}
            >
              <Icon icon={ExternalLink} size={16} />
              <span className="btn-label">Microsite bearbeiten</span>
            </a>
          ) : null}
          {!archived ? (
            editing ? (
              <Button
                data-testid="action-edit-done"
                icon={X}
                onClick={() => void go({ tab: "overview", editing: false })}
                variant="secondary"
              >
                Bearbeiten beenden
              </Button>
            ) : (
              <Button
                data-testid="action-edit"
                icon={Pencil}
                onClick={() => void go({ tab: "overview", editing: true })}
                variant="secondary"
              >
                Bearbeiten
              </Button>
            )
          ) : null}
        </div>
      </header>

      <Tabs
        idPrefix="action"
        items={tabs.map((tab) => ({ ...tab, count: counts[tab.id] }))}
        label="Bereiche der Aktion"
        onChange={(tab) => void go({ tab, editing: false })}
        value={current}
      />
      <TabPanel className="tab-panel" idPrefix="action" tabId={current}>
        {current === "overview" ? (
          <div className="stack">
            {archived ? (
              <ReadOnlyNotice data-testid="action-read-only">
                Die archivierte Aktion bleibt vollständig nachvollziehbar. Alle
                Felder sind schreibgeschützt.
              </ReadOnlyNotice>
            ) : (
              <LifecycleNextStep {...shared} />
            )}
            {editing ? (
              <div className="edit-stack" data-testid="action-edit-forms">
                <DetailsSection {...shared} />
                <GoalSection {...shared} />
                <BeneficiariesSection {...shared} />
                <CapabilitiesSection {...shared} />
                {action.capabilities.includes("ordering") ? (
                  <BuyerMailSection
                    actionId={actionId}
                    client={client}
                    disabled={archived}
                    hasDelivery={hasDelivery}
                  />
                ) : null}
                <AdministratorsSection {...shared} />
              </div>
            ) : (
              <Overview state={state} />
            )}
          </div>
        ) : current === "delivery" ? (
          <DeliverySection
            actionId={actionId}
            actionName={action.name}
            client={client}
            disabled={archived || !action.capabilities.includes("ordering")}
            disabledReason={archived ? "archived" : "no-ordering"}
            endsOn={action.endsOn}
            ordering={action.capabilities.includes("ordering")}
            startsOn={action.startsOn}
          />
        ) : current === "aliases" ? (
          <div className="stack">
            {archived || action.status === "completed" ? (
              <ReadOnlyNotice data-testid="aliases-read-only">
                {archived
                  ? "Die archivierte Aktion hat keine Aliase mehr; ihre dauerhafte Adresse bleibt erreichbar."
                  : "Nach dem Abschluss lassen sich die Aliase nicht mehr ändern; die dauerhafte Adresse bleibt erreichbar."}
              </ReadOnlyNotice>
            ) : null}
            <ActionPublicUrls actionId={actionId} client={client} />
            <CampaignAliasesSection
              actionId={actionId}
              client={client}
              disabled={archived || action.status === "completed"}
            />
            {!archived ? (
              // Completing an action releases its aliases (server): the
              // public alias and window stay read-only from then on.
              <PublicationSection
                {...shared}
                disabled={action.status === "completed"}
              />
            ) : null}
          </div>
        ) : current === "templates" ? (
          <TemplatesTab
            action={action}
            client={client}
            configuration={configuration}
            disabled={false}
          />
        ) : (
          <OffersTab configuration={configuration} />
        )}
      </TabPanel>
      {discard.dialog}
    </div>
  );
}
