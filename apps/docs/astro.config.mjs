import starlight from "@astrojs/starlight";
import { defineConfig } from "astro/config";

const sourceRevision = process.env.LEONAID_DOCS_REVISION ?? "development";

const generatedSection = (label, translation, directory) => ({
  label,
  translations: { en: translation },
  items: [{ autogenerate: { directory } }],
});

export default defineConfig({
  site: process.env.LEONAID_DOCS_SITE_URL ?? "https://docs.leonaid.invalid",
  redirects: { "/": "/de/" },
  integrations: [
    starlight({
      title: {
        de: "LeonAid Dokumentation",
        en: "LeonAid Documentation",
      },
      description:
        "Bilingual user, operations, and development documentation for LeonAid.",
      defaultLocale: "de",
      locales: {
        de: { label: "Deutsch", lang: "de" },
        en: { label: "English", lang: "en" },
      },
      logo: {
        src: "./src/assets/leonaid-mark.svg",
        alt: "LeonAid",
        replacesTitle: false,
      },
      favicon: "/favicon.svg",
      customCss: ["./src/styles/custom.css"],
      editLink: {
        baseUrl:
          "https://github.com/BjoernSchotte/leonaid/edit/main/apps/docs/",
      },
      lastUpdated: true,
      social: [
        {
          icon: "github",
          label: "GitHub",
          href: "https://github.com/BjoernSchotte/leonaid",
        },
      ],
      head: [
        {
          tag: "meta",
          attrs: { name: "leonaid-docs-revision", content: sourceRevision },
        },
      ],
      sidebar: [
        {
          label: "Anwendung",
          translations: { en: "Using LeonAid" },
          items: [
            { slug: "user" },
            generatedSection("Lernen", "Tutorials", "user/tutorials"),
            generatedSection("Anleitungen", "How-to guides", "user/how-to"),
            generatedSection("Referenz", "Reference", "user/reference"),
            generatedSection("Hintergründe", "Explanation", "user/explanation"),
          ],
        },
        {
          label: "Betrieb",
          translations: { en: "Operating LeonAid" },
          items: [
            { slug: "ops" },
            generatedSection("Lernen", "Tutorials", "ops/tutorials"),
            generatedSection("Anleitungen", "How-to guides", "ops/how-to"),
            generatedSection("Referenz", "Reference", "ops/reference"),
            generatedSection("Hintergründe", "Explanation", "ops/explanation"),
          ],
        },
        {
          label: "Entwicklung",
          translations: { en: "Developing LeonAid" },
          items: [
            { slug: "dev" },
            generatedSection("Lernen", "Tutorials", "dev/tutorials"),
            generatedSection("Anleitungen", "How-to guides", "dev/how-to"),
            generatedSection("Referenz", "Reference", "dev/reference"),
            generatedSection("Hintergründe", "Explanation", "dev/explanation"),
          ],
        },
      ],
    }),
  ],
});
