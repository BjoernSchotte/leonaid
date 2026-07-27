import { Toast } from "@base-ui/react/toast";
import {
  Alert02Icon,
  Cancel01Icon,
  CheckmarkCircle02Icon,
  InformationCircleIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import type { ReactNode } from "react";

export type ToastTone = "error" | "info" | "success";

export interface LeonAidToast {
  readonly description?: ReactNode;
  readonly timeout?: number;
  readonly title: ReactNode;
  readonly tone?: ToastTone;
}

const icons = {
  error: Alert02Icon,
  info: InformationCircleIcon,
  success: CheckmarkCircle02Icon,
} as const;

function ToastList() {
  const { toasts } = Toast.useToastManager();

  return toasts.map((toast) => {
    const tone =
      toast.type === "error" || toast.type === "success" ? toast.type : "info";
    return (
      <Toast.Root
        className={`ui-toast ui-toast--${tone}`}
        data-testid="toast"
        key={toast.id}
        swipeDirection={["down", "right"]}
        toast={toast}
      >
        <Toast.Content className="ui-toast__content">
          <HugeiconsIcon
            aria-hidden="true"
            className="ui-toast__icon"
            icon={icons[tone]}
            size={21}
            strokeWidth={1.8}
          />
          <div className="ui-toast__copy">
            <Toast.Title className="ui-toast__title" />
            <Toast.Description className="ui-toast__description" />
          </div>
          <Toast.Close
            aria-label="Hinweis schließen"
            className="ui-toast__close"
          >
            <HugeiconsIcon
              aria-hidden="true"
              icon={Cancel01Icon}
              size={18}
              strokeWidth={1.8}
            />
          </Toast.Close>
        </Toast.Content>
      </Toast.Root>
    );
  });
}

export function ToastProvider({ children }: { readonly children: ReactNode }) {
  return (
    <Toast.Provider limit={3} timeout={5_000}>
      {children}
      <Toast.Portal>
        <Toast.Viewport className="ui-toast-viewport">
          <ToastList />
        </Toast.Viewport>
      </Toast.Portal>
    </Toast.Provider>
  );
}

export function useToast() {
  const manager = Toast.useToastManager();

  return {
    show({ description, timeout, title, tone = "info" }: LeonAidToast): string {
      return manager.add({
        description,
        priority: tone === "error" ? "high" : "low",
        timeout,
        title,
        type: tone,
      });
    },
  };
}
