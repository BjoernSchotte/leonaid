import type { ImageMetadata } from "astro";
import type { AstroComponentFactory } from "astro/runtime/server/index.js";

export interface ThemeNavigationItem {
  readonly href: string;
  readonly label: string;
}

export interface ThemeShareImage {
  readonly src: string;
  readonly width: number;
  readonly height: number;
  readonly alt: string;
}

/** Campaign header: logo, name and in-page navigation instead of LeonAid's. */
export interface ThemeHeader {
  readonly logo: ImageMetadata;
  readonly homeHref: string;
  readonly homeLabel: string;
  /** Class of the in-page navigation, styled by the theme stylesheet. */
  readonly navigationClass: string;
  navigation(canOrder: boolean): readonly ThemeNavigationItem[];
}

/**
 * A public presentation theme. Themes are purely visual: business data,
 * prices, forms and legal texts always come from Core. A theme is selected by
 * data (the action's presentationTheme or the CMS theme field), never by
 * campaign names or slugs.
 */
export interface PublicTheme {
  readonly key: string;
  /** Body class that scopes the theme stylesheet; absent for LeonAid. */
  readonly bodyClass?: string;
  /** og:site_name and header name when the CMS supplies no brand. */
  readonly siteName: string;
  readonly shareImage: ThemeShareImage;
  readonly header?: ThemeHeader;
  /** Footer that names the carrying club instead of the platform. */
  readonly campaignFooter: boolean;
  /** Hero/story replacing the generic hero on Core-rendered pages. */
  readonly Intro?: AstroComponentFactory;
}
