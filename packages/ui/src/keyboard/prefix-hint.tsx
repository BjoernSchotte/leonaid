import { Kbd } from "../components/kbd";
import { useRegisteredHotkeys, usePendingPrefix } from "./use-hotkeys";

export interface PrefixHintProps {
  /** Second key of the example target; falls back to the first one. */
  readonly exampleKey?: string;
}

/**
 * Dark pill at the bottom centre while a sequence prefix ("g") waits for its
 * second key. Hidden on small screens. Mount once inside HotkeyProvider.
 */
export function PrefixHint({ exampleKey = "b" }: PrefixHintProps) {
  const prefix = usePendingPrefix();
  const bindings = useRegisteredHotkeys();
  if (!prefix) return null;
  const targets = bindings.filter((binding) =>
    binding.keys.startsWith(`${prefix} `),
  );
  const example =
    targets.find((binding) => binding.keys === `${prefix} ${exampleKey}`) ??
    targets[0];
  return (
    <div className="prefix-hint" role="status">
      <Kbd keys={prefix} /> gedrückt – jetzt Ziel wählen
      {example ? (
        <>
          , z. B. <Kbd keys={example.keys.slice(prefix.length + 1)} />{" "}
          {example.label}
        </>
      ) : null}
    </div>
  );
}
