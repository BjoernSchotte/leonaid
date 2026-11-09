import { ExternalLink } from "lucide-react";

import { Icon } from "@leonaid/ui";

import { TourMap } from "./tour-map";
import { osmHref } from "./tour-model";

export interface TourMapSlotProps {
  /** Null while the address has no pin (geocoding pending or not found). */
  readonly lat: number | null;
  readonly lon: number | null;
  /** "Lieferweg 2, 86150 Augsburg": the OSM search without a pin. */
  readonly address: string;
  /** The stop's number on its pin. */
  readonly position: number;
  readonly tiles: { readonly url: string; readonly attribution: string };
  readonly start: {
    readonly lat: number;
    readonly lon: number;
    readonly label: string;
  } | null;
  /** A tap on the map: the map view with this stop. */
  readonly onOpen: () => void;
}

/**
 * The map of a stop in the dock (spec D17, critique §3 C3): a still 140 px
 * Leaflet map with the stop's pin and the start point; a tap opens the map
 * view with pan and zoom. Under it, "In OpenStreetMap öffnen" in a new tab.
 * Without a pin: one muted line and the OSM search.
 */
export function TourMapSlot({
  address,
  lat,
  lon,
  onOpen,
  position,
  start,
  tiles,
}: TourMapSlotProps) {
  const located = lat !== null && lon !== null;
  return (
    <div className="tour-map">
      {located ? (
        <div className="tour-map-frame" data-testid="tour-map">
          <TourMap
            interactive={false}
            label={`Karte: ${address}`}
            line={null}
            onSelect={onOpen}
            pins={[
              {
                id: "stop",
                lat,
                lon,
                rank: position,
                selected: true,
                tone: "driver-0",
              },
            ]}
            start={start}
            tiles={tiles}
          />
          <button
            aria-label="Karte groß öffnen"
            className="tour-map-open"
            onClick={onOpen}
            type="button"
          />
        </div>
      ) : (
        <p className="tour-map-none" data-testid="tour-map">
          Adresse ohne Kartenpunkt
        </p>
      )}
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
