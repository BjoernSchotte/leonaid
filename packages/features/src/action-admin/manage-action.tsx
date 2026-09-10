import {
  ArrowLeft01Icon,
  Calendar03Icon,
  CharityIcon,
  Megaphone02Icon,
  Target01Icon,
  UserGroupIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import {
  ApiError,
  type ActionManagementResponse,
  type CharityActionResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

import { actionErrorMessage } from "./errors";
import { CampaignAliasesSection } from "./campaign-aliases";
import { DeliverySection } from "./delivery-section";
import {
  AdministratorsSection,
  BeneficiariesSection,
  CapabilitiesSection,
  DetailsSection,
  GoalSection,
  LifecycleSection,
  PublicationSection,
} from "./manage-sections";

const statusLabels: Record<CharityActionResponse["status"], string> = {
  active: "Aktiv",
  archived: "Archiviert",
  completed: "Abgeschlossen",
  draft: "Entwurf",
  scheduled: "Geplant",
};

const panels = [
  {
    description: "Name, Zeitraum und Aktionsziel",
    icon: Target01Icon,
    id: "basics",
    label: "Grundlagen",
    legacyHashes: ["details", "goal"],
  },
  {
    description: "Organisationen, denen die Aktion hilft",
    icon: CharityIcon,
    id: "beneficiaries",
    label: "Begünstigte",
    legacyHashes: ["beneficiaries"],
  },
  {
    description: "Aktive Bereiche und verantwortliche Mitglieder",
    icon: UserGroupIcon,
    id: "team",
    label: "Funktionen & Team",
    legacyHashes: ["capabilities", "administrators"],
  },
  {
    description: "Zeitraum und Kurzadresse der öffentlichen Seite",
    icon: Megaphone02Icon,
    id: "public",
    label: "Öffentliche Seite",
    legacyHashes: ["publication"],
  },
  {
    description: "Tage und Zeitfenster für Krapfentaxi",
    icon: Calendar03Icon,
    id: "delivery",
    label: "Lieferung",
    legacyHashes: ["delivery"],
  },
  {
    description: "Aktion planen, starten und abschließen",
    icon: Calendar03Icon,
    id: "status",
    label: "Status",
    legacyHashes: ["lifecycle"],
  },
] as const;

type PanelId = (typeof panels)[number]["id"];

function initialPanel(): PanelId {
  const hash = window.location.hash.slice(1);
  return (
    panels.find(
      (panel) =>
        panel.id === hash ||
        (panel.legacyHashes as readonly string[]).includes(hash),
    )?.id ?? "basics"
  );
}

function displayDate(value: string): string {
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(`${value}T12:00:00Z`));
}

export interface ManageActionPageProps {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
}

export function ManageActionPage({ actionId, client }: ManageActionPageProps) {
  const [activePanel, setActivePanel] = useState<PanelId>(initialPanel);
  const configuration = useQuery({
    queryKey: ["charity-action-configuration", actionId],
    queryFn: () => client.getCharityActionConfiguration(actionId),
    retry: false,
  });
  const hasDelivery = configuration.data?.template.key === "krapfentaxi";
  const visiblePanels = panels.filter(
    (panel) => panel.id !== "delivery" || hasDelivery,
  );
  const selectedPanel =
    activePanel === "delivery" && !hasDelivery ? "basics" : activePanel;
  const tabRefs = useRef(new Map<PanelId, HTMLButtonElement>());
  const queryClient = useQueryClient();
  const queryKey = ["action-management", actionId] as const;
  const query = useQuery({
    queryFn: () => client.getCharityActionManagement(actionId),
    queryKey,
    retry: (failureCount, error) =>
      !(error instanceof ApiError) && failureCount < 2,
    retryDelay: (attempt) => 150 * (attempt + 1),
    staleTime: 0,
  });

  function updateAction(action: CharityActionResponse) {
    queryClient.setQueryData<ActionManagementResponse>(
      queryKey,
      (current) => current && { ...current, action },
    );
    void queryClient.invalidateQueries({ queryKey });
  }

  function updateState(state: ActionManagementResponse) {
    queryClient.setQueryData<ActionManagementResponse>(queryKey, state);
  }

  useEffect(() => {
    function useLocationHash() {
      setActivePanel(initialPanel());
    }

    window.addEventListener("hashchange", useLocationHash);
    return () => window.removeEventListener("hashchange", useLocationHash);
  }, []);

  useEffect(() => {
    function keepSelectedTabVisible() {
      const tab = tabRefs.current.get(selectedPanel);
      const strip = tab?.parentElement;
      if (tab && strip && strip.scrollWidth > strip.clientWidth) {
        strip.scrollTo({
          left: Math.max(
            0,
            tab.offsetLeft -
              strip.offsetLeft -
              (strip.clientWidth - tab.offsetWidth) / 2,
          ),
          behavior: "instant",
        });
      }
    }
    keepSelectedTabVisible();
    window.addEventListener("resize", keepSelectedTabVisible);
    return () => window.removeEventListener("resize", keepSelectedTabVisible);
  }, [selectedPanel, query.data?.action.id]);

  function selectPanel(panelId: PanelId, focus = false) {
    setActivePanel(panelId);
    window.history.replaceState(null, "", `#${panelId}`);
    if (focus) tabRefs.current.get(panelId)?.focus();
  }

  function movePanel(
    event: React.KeyboardEvent<HTMLButtonElement>,
    panelId: PanelId,
  ) {
    const current = visiblePanels.findIndex((panel) => panel.id === panelId);
    let next = current;
    if (event.key === "ArrowRight") next = (current + 1) % visiblePanels.length;
    if (event.key === "ArrowLeft") {
      next = (current - 1 + visiblePanels.length) % visiblePanels.length;
    }
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = visiblePanels.length - 1;
    if (next === current) return;
    event.preventDefault();
    selectPanel(visiblePanels[next].id, true);
  }

  if (query.isPending) {
    return (
      <div aria-live="polite" className="action-loading" role="status">
        <span aria-hidden="true" />
        <h1>Aktionsverwaltung wird geladen</h1>
        <p>Grunddaten, Rollen und Publikation werden sicher abgerufen.</p>
      </div>
    );
  }

  if (query.isError) {
    const details = actionErrorMessage(query.error);
    return (
      <div className="action-page action-page--state">
        <StatusMessage tone="error">
          <h1>Aktion konnte nicht geladen werden</h1>
          <p>{details.message}</p>
          <Button onClick={() => void query.refetch()} variant="secondary">
            Erneut versuchen
          </Button>
        </StatusMessage>
      </div>
    );
  }

  const state = query.data;
  const action = state.action;
  const archived = action.status === "archived";
  const shared = {
    client,
    disabled: archived,
    state,
    updateAction,
    updateState,
  };

  return (
    <div className="action-page action-page--manage">
      <a className="action-back" href="/admin/actions">
        <HugeiconsIcon
          aria-hidden="true"
          icon={ArrowLeft01Icon}
          size={18}
          strokeWidth={1.8}
        />
        Alle Aktionen
      </a>
      <header className="action-page__header action-page__header--management">
        <div>
          <p className="action-page__eyebrow">Charity-Aktion verwalten</p>
          <h1 data-testid="management-title">{action.name}</h1>
          <p>
            {action.carrierName} · {displayDate(action.startsOn)} bis{" "}
            {displayDate(action.endsOn)}
          </p>
        </div>
        <span
          className="action-status-badge"
          data-status={action.status}
          data-testid="management-status"
        >
          {statusLabels[action.status]}
        </span>
        <a
          className="ui-button ui-button--secondary"
          href={`/_emdash/admin/campaigns/${action.id}`}
        >
          Microsite bearbeiten
        </a>
      </header>

      {archived ? (
        <StatusMessage>
          Die archivierte Aktion bleibt vollständig nachvollziehbar. Alle
          Bearbeitungsfelder sind schreibgeschützt.
        </StatusMessage>
      ) : null}

      {configuration.isError && (
        <StatusMessage tone="error">
          Die Aktionsvorlage konnte nicht geladen werden.
          <Button
            variant="secondary"
            onClick={() => void configuration.refetch()}
          >
            Erneut versuchen
          </Button>
        </StatusMessage>
      )}

      <div className="action-workspace-nav">
        <div
          aria-label="Bereich der Aktion wählen"
          className="action-workspace-tabs"
          role="tablist"
        >
          {visiblePanels.map((panel) => (
            <button
              aria-controls={`panel-${panel.id}`}
              aria-selected={selectedPanel === panel.id}
              className="action-workspace-tab"
              data-testid={`management-tab-${panel.id}`}
              id={`tab-${panel.id}`}
              key={panel.id}
              onClick={() => selectPanel(panel.id)}
              onKeyDown={(event) => movePanel(event, panel.id)}
              ref={(element) => {
                if (element) tabRefs.current.set(panel.id, element);
                else tabRefs.current.delete(panel.id);
              }}
              role="tab"
              tabIndex={selectedPanel === panel.id ? 0 : -1}
              type="button"
            >
              <HugeiconsIcon
                aria-hidden="true"
                icon={panel.icon}
                size={18}
                strokeWidth={1.7}
              />
              <span>
                <strong>{panel.label}</strong>
                <small>{panel.description}</small>
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="action-edit-stack">
        <div
          aria-labelledby="tab-basics"
          className="action-edit-panel"
          hidden={selectedPanel !== "basics"}
          id="panel-basics"
          role="tabpanel"
        >
          <DetailsSection {...shared} />
          <GoalSection {...shared} />
        </div>
        <div
          aria-labelledby="tab-beneficiaries"
          className="action-edit-panel"
          hidden={selectedPanel !== "beneficiaries"}
          id="panel-beneficiaries"
          role="tabpanel"
        >
          <BeneficiariesSection {...shared} />
        </div>
        <div
          aria-labelledby="tab-team"
          className="action-edit-panel"
          hidden={selectedPanel !== "team"}
          id="panel-team"
          role="tabpanel"
        >
          <CapabilitiesSection {...shared} />
          <AdministratorsSection {...shared} />
        </div>
        <div
          aria-labelledby="tab-public"
          className="action-edit-panel"
          hidden={selectedPanel !== "public"}
          id="panel-public"
          role="tabpanel"
        >
          <PublicationSection {...shared} />
          <CampaignAliasesSection
            actionId={actionId}
            client={client}
            disabled={archived || action.status === "completed"}
          />
        </div>
        <div
          aria-labelledby="tab-status"
          className="action-edit-panel"
          hidden={selectedPanel !== "status"}
          id="panel-status"
          role="tabpanel"
        >
          <LifecycleSection {...shared} />
        </div>
        {hasDelivery && (
          <div
            aria-labelledby="tab-delivery"
            className="action-edit-panel"
            hidden={selectedPanel !== "delivery"}
            id="panel-delivery"
            role="tabpanel"
          >
            <DeliverySection
              client={client}
              actionId={actionId}
              startsOn={action.startsOn}
              endsOn={action.endsOn}
              disabled={archived || !action.capabilities.includes("ordering")}
            />
          </div>
        )}
      </div>
    </div>
  );
}
