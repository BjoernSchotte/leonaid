import { cn } from "../lib/utils";

/** Routes of the installation's legal pages (apps/public, every host). */
export const IMPRINT_HREF = "/impressum";
export const PRIVACY_HREF = "/datenschutz";
/** The members' section of the privacy page: the apps' default target. */
export const MEMBER_PRIVACY_HREF = `${PRIVACY_HREF}#mitglieder`;

export interface LegalLinksProps {
  readonly className?: string;
  readonly privacyHref?: string;
}

/** Impressum and Datenschutz links for the signed-in apps' shells. */
export function LegalLinks({
  className,
  privacyHref = MEMBER_PRIVACY_HREF,
}: LegalLinksProps) {
  return (
    <nav
      aria-label="Impressum und Datenschutz"
      className={cn("legal-links", className)}
      data-testid="legal-links"
    >
      <a href={IMPRINT_HREF}>Impressum</a>
      <span aria-hidden="true" className="legal-links-separator">
        ·
      </span>
      <a href={privacyHref}>Datenschutz</a>
    </nav>
  );
}
