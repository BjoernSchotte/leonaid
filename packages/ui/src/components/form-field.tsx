import { cloneElement, useId, type ReactElement, type ReactNode } from "react";

import { cn } from "../lib/utils";

type FieldControlProps = {
  readonly "aria-describedby"?: string;
  readonly "aria-invalid"?: boolean | "false" | "true";
  readonly "aria-required"?: boolean | "false" | "true";
  readonly id?: string;
  readonly required?: boolean;
};

export interface FormFieldProps {
  readonly children: ReactElement<FieldControlProps>;
  readonly className?: string;
  readonly description?: ReactNode;
  readonly error?: ReactNode;
  readonly label: ReactNode;
  readonly required?: boolean;
}

export function FormField({
  children,
  className,
  description,
  error,
  label,
  required = false,
}: FormFieldProps) {
  const generatedId = useId();
  const controlId = children.props.id ?? `field-${generatedId}`;
  const descriptionId = description ? `${controlId}-description` : undefined;
  const errorId = error ? `${controlId}-error` : undefined;
  const describedBy = [
    children.props["aria-describedby"],
    descriptionId,
    errorId,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={cn("ui-field", error && "ui-field--error", className)}>
      <label className="ui-field__label" htmlFor={controlId}>
        {label}
        {required ? (
          <>
            <span aria-hidden="true" className="ui-field__required">
              *
            </span>
            <span className="sr-only"> (Pflichtfeld)</span>
          </>
        ) : null}
      </label>
      {description ? (
        <p className="ui-field__description" id={descriptionId}>
          {description}
        </p>
      ) : null}
      {cloneElement(children, {
        "aria-describedby": describedBy || undefined,
        "aria-invalid": error ? true : children.props["aria-invalid"],
        "aria-required": required || children.props["aria-required"],
        id: controlId,
        required: required || children.props.required,
      })}
      {error ? (
        <p className="ui-field__error" id={errorId}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
