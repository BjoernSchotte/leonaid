# Drittanbieterhinweise für `@leonaid/ui`

Stand: 27. Juli 2026

LeonAid kapselt die folgenden UI-Abhängigkeiten zentral. Maßgeblich bleiben
die mit `bun.lock` gepinnten Pakete und die jeweils mitgelieferten
Lizenztexte.

| Paket/Projekt                                                                            |                          Verwendete Version | Lizenz | Verwendung                                      |
| ---------------------------------------------------------------------------------------- | ------------------------------------------: | ------ | ----------------------------------------------- |
| [shadcn/ui](https://github.com/shadcn-ui/ui)                                             | Open-Code-Konfiguration, kein Runtime-Paket | MIT    | Komponentenstruktur und `components.json`       |
| [`@base-ui/react`](https://github.com/mui/base-ui)                                       |                                       1.6.0 | MIT    | zugängliche Dialog-, Menü- und Toast-Primitives |
| [`@hugeicons/core-free-icons`](https://www.npmjs.com/package/@hugeicons/core-free-icons) |                                       4.2.3 | MIT    | ausschließlich freie Icon-Daten                 |
| [`@hugeicons/react`](https://github.com/hugeicons/hugeicons)                             |                                       1.1.9 | MIT    | React-Renderer für freie Hugeicons              |
| [React](https://github.com/facebook/react)                                               |                                      19.2.8 | MIT    | Komponenten-Laufzeit                            |
| [Tailwind CSS](https://github.com/tailwindlabs/tailwindcss)                              |                                       4.3.3 | MIT    | Buildzeit-CSS und shadcn/ui-Kompatibilität      |

Die offiziellen Lions-International-Markenfarben sind Markenprimitiven, keine
Softwarebibliothek. Ihre Nutzung richtet sich zusätzlich nach den
[Lions Clubs International Brand Guidelines](https://www.lionsclubs.org/en/resources-for-members/brand-guidelines).
LeonAid verwendet daraus im UI nur die dokumentierten Farbwerte; Logos und
sonstige Markenassets sind nicht Bestandteil von `@leonaid/ui`.
