import {
  cloneElement,
  useId,
  type ComponentPropsWithRef,
  type ReactElement,
  type ReactNode,
} from "react";

import { cn } from "../lib/utils";

type FieldControlProps = {
  readonly "aria-describedby"?: string;
  readonly "aria-invalid"?: boolean | "false" | "true";
  readonly "aria-required"?: boolean | "false" | "true";
  readonly className?: string;
  readonly id?: string;
  readonly required?: boolean;
  readonly type?: string;
};

export interface FieldProps {
  /** One control. Native input, select and textarea get the `.input` look. */
  readonly children: ReactElement<FieldControlProps>;
  readonly className?: string;
  /** Replaced by the error while one is shown. */
  readonly error?: ReactNode;
  readonly hint?: ReactNode;
  /** Used for the control; generated when absent. */
  readonly id?: string;
  readonly label: ReactNode;
  readonly optional?: boolean;
  readonly required?: boolean;
}

const unstyledInputTypes = new Set([
  "checkbox",
  "radio",
  "hidden",
  "range",
  "color",
]);

function controlClass(control: ReactElement<FieldControlProps>) {
  if (control.type === "textarea") return "input textarea";
  if (control.type === "select") return "input select";
  if (
    control.type === "input" &&
    !unstyledInputTypes.has(control.props.type ?? "text")
  ) {
    return "input";
  }
  return undefined;
}

/** Label, control and hint or error, linked for assistive technology. */
export function Field({
  children,
  className,
  error,
  hint,
  id,
  label,
  optional = false,
  required = false,
}: FieldProps) {
  const generatedId = useId();
  const controlId = children.props.id ?? id ?? `field-${generatedId}`;
  const hasError = error != null && error !== false && error !== "";
  const hasHint = !hasError && hint != null && hint !== false && hint !== "";
  const hintId = hasHint ? `${controlId}-hint` : undefined;
  const errorId = hasError ? `${controlId}-error` : undefined;
  const describedBy = [children.props["aria-describedby"], hintId, errorId]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={cn("field", hasError && "has-error", className)}>
      <label className="field-label" htmlFor={controlId}>
        {label}
        {required ? (
          <>
            <span aria-hidden="true" className="field-required">
              {" *"}
            </span>
            <span className="sr-only"> (Pflichtfeld)</span>
          </>
        ) : optional ? (
          <span className="field-optional"> (optional)</span>
        ) : null}
      </label>
      {cloneElement(children, {
        "aria-describedby": describedBy || undefined,
        "aria-invalid": hasError ? true : children.props["aria-invalid"],
        "aria-required": required || children.props["aria-required"],
        className:
          cn(controlClass(children), children.props.className) || undefined,
        id: controlId,
        required: required || children.props.required,
      })}
      {hasHint ? (
        <p className="field-hint" id={hintId}>
          {hint}
        </p>
      ) : null}
      {hasError ? (
        <p className="field-error" id={errorId}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

export interface FormFieldProps extends Omit<FieldProps, "hint"> {
  /** Shown as the field hint. */
  readonly description?: ReactNode;
}

/** The product's earlier name for {@link Field}; `description` is the hint. */
export function FormField({ description, ...props }: FormFieldProps) {
  return <Field hint={description} {...props} />;
}

export function Input({ className, ...props }: ComponentPropsWithRef<"input">) {
  return <input className={cn("input", className)} {...props} />;
}

export function Textarea({
  className,
  ...props
}: ComponentPropsWithRef<"textarea">) {
  return <textarea className={cn("input", "textarea", className)} {...props} />;
}

export function Select({
  className,
  ...props
}: ComponentPropsWithRef<"select">) {
  return <select className={cn("input", "select", className)} {...props} />;
}
