/// <reference types="emdash/locals" />

declare namespace App {
  interface Locals {
    /** Set by the campaign host middleware (specs/multi-domain §7.2). */
    siteHost?: import("./site-host").SiteHostContext;
  }
}
