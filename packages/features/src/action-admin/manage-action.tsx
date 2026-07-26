import {
  ArrowLeft01Icon,
  Calendar03Icon,
  CharityIcon,
  Settings02Icon,
  Target01Icon,
  UserGroupIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiError,
  type ActionManagementResponse,
  type CharityActionResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

import { actionErrorMessage } from "./errors";
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

const steps = [
  { href: "#details", icon: CharityIcon, label: "Grunddaten" },
  { href: "#goal", icon: Target01Icon, label: "Ziel" },
  { href: "#beneficiaries", icon: CharityIcon, label: "Begünstigte" },
  { href: "#capabilities", icon: Settings02Icon, label: "Funktionen" },
  { href: "#administrators", icon: UserGroupIcon, label: "Verantwortliche" },
  { href: "#publication", icon: Calendar03Icon, label: "Publikation" },
  { href: "#lifecycle", icon: Settings02Icon, label: "Status" },
] as const;

export interface ManageActionPageProps {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
}

export function ManageActionPage({ actionId, client }: ManageActionPageProps) {
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
            {action.carrierName} · {action.startsOn} bis {action.endsOn}
          </p>
        </div>
        <span
          className="action-status-badge"
          data-status={action.status}
          data-testid="management-status"
        >
          {statusLabels[action.status]}
        </span>
      </header>

      {archived ? (
        <StatusMessage>
          Die archivierte Aktion bleibt vollständig nachvollziehbar. Alle
          Bearbeitungsfelder sind schreibgeschützt.
        </StatusMessage>
      ) : null}

      <nav aria-label="Bearbeitungsschritte" className="action-step-nav">
        {steps.map((step, index) => (
          <a href={step.href} key={step.href}>
            <span>{index + 1}</span>
            <HugeiconsIcon
              aria-hidden="true"
              icon={step.icon}
              size={18}
              strokeWidth={1.7}
            />
            {step.label}
          </a>
        ))}
      </nav>

      <div className="action-edit-stack">
        <DetailsSection {...shared} />
        <GoalSection {...shared} />
        <BeneficiariesSection {...shared} />
        <CapabilitiesSection {...shared} />
        <AdministratorsSection {...shared} />
        <PublicationSection {...shared} />
        <LifecycleSection {...shared} />
      </div>
    </div>
  );
}
