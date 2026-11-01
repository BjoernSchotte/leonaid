import "./theme.css";

// The intro and images stay at their established paths: the CMS microsite
// import (tools/emdash_spike/krapfentaxi-source.mjs) pins them by hash.
import Intro from "../../components/KrapfentaxiIntro.astro";
import hero from "../../assets/krapfentaxi/hero.webp";
import logo from "../../assets/krapfentaxi/logo.png";
import type { PublicTheme } from "../types";

export const krapfentaxiTheme: PublicTheme = {
  key: "krapfentaxi",
  bodyClass: "taxi-site",
  siteName: "Lions Krapfentaxi",
  shareImage: {
    src: hero.src,
    width: 1568,
    height: 1024,
    alt: "Ein Löwe im Krapfentaxi vor der Würzburger Residenz.",
  },
  header: {
    logo,
    homeHref: "#start",
    homeLabel: "Krapfentaxi – zum Seitenanfang",
    navigationClass: "taxi-nav",
    navigation: (canOrder) => [
      { href: "#das-krapfentaxi", label: "Das Krapfentaxi" },
      canOrder
        ? { href: "#bestellen", label: "Bestellen" }
        : { href: "#angebote", label: "Angebote" },
      { href: "#wirkung", label: "Wem wir helfen" },
      { href: "#datenschutz", label: "Datenschutz" },
    ],
  },
  campaignFooter: true,
  Intro,
};
