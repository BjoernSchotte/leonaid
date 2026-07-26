# `@leonaid/ui`

Gemeinsame, host-neutrale Open-Code-Komponenten für Web und PWA. Die
shadcn/ui-Konfiguration ist auf Base UI und ausschließlich freie
Hugeicons-Pakete festgelegt.

`src/styles/tokens.css` trennt zwei Ebenen:

- unveränderte Lions-International-Markenprimitiven aus den offiziellen
  [Brand Guidelines](https://www.lionsclubs.org/en/resources-for-members/brand-guidelines),
  darunter Blue `#00338D`, Yellow `#EBB700`, Purple `#7A2582` und Navy
  `#0D2240`;
- semantische LeonAid-Tokens wie `--background`, `--surface`, `--primary`,
  `--focus`, `--success` und `--sidebar`.

Komponenten verwenden ausschließlich die semantische Ebene. Light und Dark
Mode können dadurch weiterentwickelt werden, ohne Fachkomponenten oder
Markenprimitiven umzuschreiben. Der Umschalter unterstützt `system`, `light`
und `dark`, speichert nur diese Präferenz lokal und folgt im Systemmodus
laufenden Änderungen des Betriebssystems.
