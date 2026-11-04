/**
 * jsdom has no `showModal()`. This polyfill copies the browser behaviour the
 * Modal relies on: `open`, focus of the first control, Esc firing a cancelable
 * `cancel` event, and a `close` event when the dialog closes.
 */
const focusable =
  "[autofocus], button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";

const stack: HTMLDialogElement[] = [];

function onKeyDown(event: KeyboardEvent) {
  if (event.key !== "Escape") return;
  const dialog = stack.at(-1);
  if (!dialog) return;
  const cancel = new Event("cancel", { cancelable: true });
  if (dialog.dispatchEvent(cancel)) dialog.close();
}

export function installDialogPolyfill() {
  const proto = HTMLDialogElement.prototype;
  proto.showModal = function showModal(this: HTMLDialogElement) {
    if (this.open) return;
    this.setAttribute("open", "");
    stack.push(this);
    const target =
      this.querySelector<HTMLElement>("[autofocus]") ??
      this.querySelector<HTMLElement>(focusable);
    target?.focus();
  };
  proto.close = function close(this: HTMLDialogElement) {
    if (!this.open) return;
    this.removeAttribute("open");
    const index = stack.indexOf(this);
    if (index >= 0) stack.splice(index, 1);
    this.dispatchEvent(new Event("close"));
  };
  document.removeEventListener("keydown", onKeyDown);
  document.addEventListener("keydown", onKeyDown);
}
