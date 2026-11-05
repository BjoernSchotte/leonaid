# Third-party notices for `@leonaid/ui`

As of: November 4, 2026

LeonAid wraps the following UI dependencies in one place. The packages pinned
in `bun.lock` and the license texts shipped with each package remain
authoritative.

| Package/project                                                                   |                                Version used | License | Use                                              |
| --------------------------------------------------------------------------------- | ------------------------------------------: | ------- | ------------------------------------------------ |
| [shadcn/ui](https://github.com/shadcn-ui/ui)                                      | open-code configuration, no runtime package | MIT     | component structure and `components.json`        |
| [`@fontsource/barlow`](https://github.com/fontsource/font-files)                  |                                       5.3.0 | OFL-1.1 | self-hosted Barlow text font (latin, 400–700)    |
| [`@fontsource-variable/jetbrains-mono`](https://github.com/fontsource/font-files) |                                       5.3.0 | OFL-1.1 | self-hosted JetBrains Mono for numbers and codes |
| [`lucide-react`](https://github.com/lucide-icons/lucide)                          |                                      1.60.0 | ISC     | icon set for new UI (`Icon` adapter)             |
| [React](https://github.com/facebook/react)                                        |                                      19.2.8 | MIT     | component runtime                                |
| [Tailwind CSS](https://github.com/tailwindlabs/tailwindcss)                       |                                       4.3.3 | MIT     | build-time CSS and shadcn/ui compatibility       |

The two font packages ship the font files under the SIL Open Font License 1.1
(OFL-1.1); Björn Schotte approved OFL-1.1 for exactly these two packages on
November 3, 2026. The fonts are bundled as app assets and never loaded from a
third-party host.

The official Lions International brand colors are brand primitives, not a
software library. Their use is also governed by the
[Lions Clubs International Brand Guidelines](https://www.lionsclubs.org/en/resources-for-members/brand-guidelines).
LeonAid uses only the documented color values in the UI; logos and other brand
assets are not part of `@leonaid/ui`.
