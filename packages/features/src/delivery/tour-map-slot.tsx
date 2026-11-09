import { ExternalLink, MapPin } from "lucide-react";

import { Icon } from "@leonaid/ui";

import { osmHref } from "./tour-model";

export interface TourMapSlotProps {
  /** Null until the address has a pin (geocoding, slice 2). */
  readonly lat: number | null;
  readonly lon: number | null;
  /** "Lieferweg 2, 86150 Augsburg": the OSM search without a pin. */
  readonly address: string;
}

/**
 * The map of the next stop in the dock (spec D17, critique §3 C3): a 140 px
 * box and, under it, "In OpenStreetMap öffnen" in a new tab. Until the
 * inline Leaflet map arrives (Task 11 replaces the box's inside), the box
 * says "Karte folgt"; the external link already works.
 */
export function TourMapSlot({ address, lat, lon }: TourMapSlotProps) {
  return (
    <div className="tour-map">
      <div className="tour-map-box" data-testid="tour-map">
        <Icon icon={MapPin} size={18} />
        <span>Karte folgt</span>
      </div>
      <a
        className="tour-map-link"
        href={osmHref({ address, lat, lon })}
        rel="noopener"
        target="_blank"
      >
        <span>In OpenStreetMap öffnen</span>
        <Icon icon={ExternalLink} size={14} />
      </a>
    </div>
  );
}
