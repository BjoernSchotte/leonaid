import { Menu } from "@base-ui/react/menu";
import {
  ComputerIcon,
  Moon02Icon,
  Sun01Icon,
  Tick02Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useEffect, useState } from "react";

const themeOptions = [
  { icon: ComputerIcon, label: "System", value: "system" },
  { icon: Sun01Icon, label: "Hell", value: "light" },
  { icon: Moon02Icon, label: "Dunkel", value: "dark" },
] as const;

type ThemeMode = (typeof themeOptions)[number]["value"];

const storageKey = "leonaid.theme";

function storedTheme(): ThemeMode {
  try {
    const value = window.localStorage.getItem(storageKey);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function isDarkSystemTheme(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

function applyTheme(mode: ThemeMode) {
  const resolved =
    mode === "system" ? (isDarkSystemTheme() ? "dark" : "light") : mode;
  document.documentElement.dataset.theme = resolved;
  document.documentElement.dataset.themePreference = mode;
  document.documentElement.style.colorScheme = resolved;
}

export function ThemeSwitcher() {
  const [theme, setTheme] = useState<ThemeMode>(storedTheme);
  const [open, setOpen] = useState(false);
  const activeOption =
    themeOptions.find((option) => option.value === theme) ?? themeOptions[0];

  useEffect(() => {
    applyTheme(theme);
    try {
      window.localStorage.setItem(storageKey, theme);
    } catch {
      // Theme selection still applies for this session when storage is blocked.
    }

    if (theme !== "system" || typeof window.matchMedia !== "function") {
      return;
    }

    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const updateSystemTheme = () => applyTheme("system");
    media.addEventListener("change", updateSystemTheme);
    return () => media.removeEventListener("change", updateSystemTheme);
  }, [theme]);

  return (
    <Menu.Root onOpenChange={setOpen} open={open}>
      <Menu.Trigger
        aria-label={`Farbschema: ${activeOption.label}`}
        className="ui-icon-button ui-theme-trigger"
        data-testid="theme-trigger"
        title={`Farbschema: ${activeOption.label}`}
      >
        <HugeiconsIcon
          aria-hidden="true"
          icon={activeOption.icon}
          size={19}
          strokeWidth={1.8}
        />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner
          align="end"
          className="ui-menu-positioner"
          sideOffset={8}
        >
          <Menu.Popup aria-label="Farbschema wählen" className="ui-theme-menu">
            <Menu.RadioGroup
              onValueChange={(value) => {
                setTheme(value as ThemeMode);
                setOpen(false);
              }}
              value={theme}
            >
              <Menu.GroupLabel className="ui-theme-menu__label">
                Darstellung
              </Menu.GroupLabel>
              {themeOptions.map((option) => (
                <Menu.RadioItem
                  className="ui-theme-menu__item"
                  data-testid={`theme-${option.value}`}
                  key={option.value}
                  value={option.value}
                >
                  <HugeiconsIcon
                    aria-hidden="true"
                    icon={option.icon}
                    size={18}
                    strokeWidth={1.8}
                  />
                  <span>{option.label}</span>
                  <Menu.RadioItemIndicator className="ui-theme-menu__indicator">
                    <HugeiconsIcon
                      aria-hidden="true"
                      icon={Tick02Icon}
                      size={16}
                      strokeWidth={2}
                    />
                  </Menu.RadioItemIndicator>
                </Menu.RadioItem>
              ))}
            </Menu.RadioGroup>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}
