import type * as Leaflet from "leaflet";
import { useEffect, useRef, useState } from "react";

import { buttonClassName, cn } from "@leonaid/ui";

/*
 * The map of the delivery tours (spec krapfentaxi-touren §6.1, §7.2, §8.1,
 * D7, D17): Leaflet, bundled, raster tiles from the installation's tile URL.
 * Strict CSP: pins are divIcons with class names and a number only, no
 * default marker images and no style markup; Leaflet positions them through
 * the CSSOM. The device location stays in this browser.
 *
 * Leaflet loads on the first map (its own chunk): it reads `window` when
 * imported, and most pages of both apps show no map.
 */

type LeafletLib = typeof Leaflet;
let leafletLoad: Promise<LeafletLib> | null = null;
function loadLeaflet(): Promise<LeafletLib> {
  leafletLoad ??= import("leaflet").then(
    // The CommonJS build arrives as the default export in some bundlers.
    (module) =>
      ((module as { default?: LeafletLib }).default ?? module) as LeafletLib,
  );
  return leafletLoad;
}

export type TourPinTone =
  | "driver-0"
  | "driver-1"
  | "driver-2"
  | "driver-3"
  | "driver-4"
  | "driver-5"
  | "driver-6"
  | "driver-7"
  | "unassigned"
  | "done";

/** Driver colours repeat after this many drivers. */
export const DRIVER_TONES = 8;

export const driverTone = (index: number): TourPinTone =>
  `driver-${((index % DRIVER_TONES) + DRIVER_TONES) % DRIVER_TONES}` as TourPinTone;

export interface TourMapPin {
  readonly id: string;
  readonly lat: number;
  readonly lon: number;
  /** The number on the pin; 0 shows none (stops without an order). */
  readonly rank: number;
  readonly tone: TourPinTone;
  readonly selected: boolean;
  /** Accessible name, e.g. "Stopp 3: Maria Obermaier". */
  readonly label?: string;
}

export interface TourMapProps {
  readonly tiles: { readonly url: string; readonly attribution: string };
  readonly start: {
    readonly lat: number;
    readonly lon: number;
    readonly label: string;
  } | null;
  readonly pins: readonly TourMapPin[];
  /** A straight line through these pins, in this order. */
  readonly line: {
    readonly ids: readonly string[];
    readonly dashed: boolean;
  } | null;
  readonly onSelect: (id: string) => void;
  /** Set: a click on the map places a pin there (manager, §6.4). */
  readonly onPlace?: (lat: number, lon: number) => void;
  /**
   * With onPlace: a button that places the pin at the map centre (marked
   * by a crosshair), for keyboard users who pan with the arrow keys.
   */
  readonly placeAtCenterLabel?: string;
  /** Show the device location (opt-in; never sent anywhere). */
  readonly showLocation?: boolean;
  readonly onLocationError?: () => void;
  /** False: a still picture (dock): no pan, no zoom, pins not focusable. */
  readonly interactive?: boolean;
  /** Accessible name of the map region. */
  readonly label?: string;
  readonly className?: string;
}

/** Without any point: Germany. */
const FALLBACK_VIEW = {
  center: [51.1657, 10.4515] as Leaflet.LatLngTuple,
  zoom: 5,
};
/** Closest zoom for a single point or close points (house level). */
const MAX_FIT_ZOOM = 17;
/** The pin's target: 44 px (WCAG 2.5.5); the disc inside is 28 px. */
const PIN_SIZE = 44;
const START_SIZE = 30;
const LOCATION_SIZE = 18;

const HTML_ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};
/** Leaflet writes attributions as HTML; ours is plain text. */
const escapeHtml = (text: string) =>
  text.replace(/[&<>"']/g, (character) => HTML_ESCAPES[character] ?? "");

/** A house outline for the start point (no style attributes). */
const START_ICON =
  '<svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"><path d="M3 11.5 12 4l9 7.5V20H3z"/></svg>';

function pinIcon(L: LeafletLib, pin: TourMapPin) {
  return L.divIcon({
    className: cn(
      "tour-pin",
      `tour-pin--${pin.tone}`,
      pin.selected && "is-selected",
    ),
    html: `<span class="tour-pin-dot">${pin.rank > 0 ? String(pin.rank) : ""}</span>`,
    iconAnchor: [PIN_SIZE / 2, PIN_SIZE / 2],
    iconSize: [PIN_SIZE, PIN_SIZE],
  });
}

/** Where the map looks: every pin and the start; changes only with them. */
function viewKey(
  pins: readonly TourMapPin[],
  start: TourMapProps["start"],
): string {
  const points = pins.map((pin) => `${pin.id}@${pin.lat},${pin.lon}`).sort();
  if (start) points.push(`start@${start.lat},${start.lon}`);
  return points.join("|");
}

export function TourMap({
  className,
  interactive = true,
  label = "Karte",
  line,
  onLocationError,
  onPlace,
  onSelect,
  pins,
  placeAtCenterLabel,
  showLocation = false,
  start,
  tiles,
}: TourMapProps) {
  const host = useRef<HTMLDivElement | null>(null);
  const [L, setLeaflet] = useState<LeafletLib | null>(null);
  const mapRef = useRef<Leaflet.Map | null>(null);
  const layer = useRef<Leaflet.LayerGroup | null>(null);
  const fitted = useRef<string | null>(null);
  const [ready, setReady] = useState(false);
  // Handlers change every render; the map's listeners read the latest.
  const handlers = useRef({ onLocationError, onPlace, onSelect });
  handlers.current = { onLocationError, onPlace, onSelect };

  useEffect(() => {
    let live = true;
    void loadLeaflet().then((lib) => {
      if (live) setLeaflet(() => lib);
    });
    return () => {
      live = false;
    };
  }, []);

  // One Leaflet map per tile source and mode.
  useEffect(() => {
    const element = host.current;
    if (!element || !L) return;
    const map = L.map(element, {
      attributionControl: false,
      boxZoom: interactive,
      doubleClickZoom: interactive,
      dragging: interactive,
      keyboard: interactive,
      scrollWheelZoom: interactive,
      touchZoom: interactive,
      zoomControl: interactive,
    });
    L.control
      .attribution({ prefix: false })
      .addAttribution(escapeHtml(tiles.attribution))
      .addTo(map);
    L.tileLayer(tiles.url, { maxZoom: 19 }).addTo(map);
    layer.current = L.layerGroup().addTo(map);
    map.on("click", (event: Leaflet.LeafletMouseEvent) =>
      handlers.current.onPlace?.(event.latlng.lat, event.latlng.lng),
    );
    map.whenReady(() => setReady(true));
    mapRef.current = map;
    // The box can change size (dock folds, window resizes, view switch).
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => {
            map.invalidateSize();
            // A fit made while the box had no size is redone.
            if (fitted.current === "") fitted.current = null;
          });
    observer?.observe(element);
    return () => {
      observer?.disconnect();
      map.remove();
      mapRef.current = null;
      layer.current = null;
      fitted.current = null;
      setReady(false);
    };
  }, [L, interactive, tiles.attribution, tiles.url]);

  // Pins, start point and line, redrawn only when their content changes
  // (callers rebuild the arrays on every render); the view moves only when
  // the points do.
  const key = viewKey(pins, start);
  const drawn = JSON.stringify([pins, line, start]);
  const content = useRef({ line, pins, start });
  content.current = { line, pins, start };
  useEffect(() => {
    const map = mapRef.current;
    const group = layer.current;
    const element = host.current;
    if (!L || !map || !group || !element) return;
    const { line, pins, start } = content.current;
    // A redraw replaces the markers; a focused pin keeps the focus.
    const active = document.activeElement;
    const focusedPin =
      active instanceof HTMLElement && element.contains(active)
        ? active.dataset.pinId
        : undefined;
    group.clearLayers();

    const located = new Map(pins.map((pin) => [pin.id, pin]));
    const path = (line?.ids ?? [])
      .map((id) => located.get(id))
      .filter((pin): pin is TourMapPin => Boolean(pin))
      .map((pin) => [pin.lat, pin.lon] as Leaflet.LatLngTuple);
    if (line && path.length > 1) {
      L.polyline(path, {
        className: cn("tour-line", line.dashed && "is-dashed"),
        interactive: false,
      }).addTo(group);
    }
    if (start) {
      const marker = L.marker([start.lat, start.lon], {
        icon: L.divIcon({
          className: "tour-pin tour-pin--start",
          html: `<span class="tour-pin-dot">${START_ICON}</span>`,
          iconAnchor: [START_SIZE / 2, START_SIZE / 2],
          iconSize: [START_SIZE, START_SIZE],
        }),
        interactive: false,
        keyboard: false,
      }).addTo(group);
      marker.getElement()?.setAttribute("aria-label", `Start: ${start.label}`);
      marker.getElement()?.setAttribute("role", "img");
    }
    for (const pin of pins) {
      const marker = L.marker([pin.lat, pin.lon], {
        icon: pinIcon(L, pin),
        interactive,
        keyboard: interactive,
        zIndexOffset: pin.selected ? 1000 : 0,
      });
      marker.on("click", () => handlers.current.onSelect(pin.id));
      marker.addTo(group);
      const icon = marker.getElement();
      if (icon) {
        icon.dataset.pinId = pin.id;
        if (pin.label) icon.setAttribute("aria-label", pin.label);
        if (interactive) {
          icon.setAttribute("aria-pressed", String(pin.selected));
          if (pin.id === focusedPin) icon.focus({ preventScroll: true });
        } else {
          icon.setAttribute("aria-hidden", "true");
        }
      }
    }

    if (fitted.current === key) return;
    const points: Leaflet.LatLngTuple[] = pins.map((pin) => [pin.lat, pin.lon]);
    if (start) points.push([start.lat, start.lon]);
    const size = map.getSize();
    if (!points.length) {
      map.setView(FALLBACK_VIEW.center, FALLBACK_VIEW.zoom);
    } else if (points.length === 1 || size.x === 0 || size.y === 0) {
      // Leaflet cannot fit bounds into a box without size (hidden, tests).
      map.setView(L.latLngBounds(points).getCenter(), MAX_FIT_ZOOM);
    } else {
      map.fitBounds(L.latLngBounds(points), {
        maxZoom: MAX_FIT_ZOOM,
        padding: [PIN_SIZE / 2, PIN_SIZE / 2],
      });
    }
    fitted.current = size.x === 0 || size.y === 0 ? "" : key;
  }, [L, drawn, interactive, key, ready]);

  // The device location: only while asked for, only in this browser.
  useEffect(() => {
    const map = mapRef.current;
    if (!showLocation || !map || !L) return;
    if (!("geolocation" in navigator)) {
      handlers.current.onLocationError?.();
      return;
    }
    let marker: Leaflet.Marker | null = null;
    const watch = navigator.geolocation.watchPosition(
      ({ coords }) => {
        const at: Leaflet.LatLngTuple = [coords.latitude, coords.longitude];
        if (marker) {
          marker.setLatLng(at);
          return;
        }
        marker = L.marker(at, {
          icon: L.divIcon({
            className: "tour-pin tour-pin--me",
            html: '<span class="tour-pin-dot"></span>',
            iconAnchor: [LOCATION_SIZE / 2, LOCATION_SIZE / 2],
            iconSize: [LOCATION_SIZE, LOCATION_SIZE],
          }),
          interactive: false,
          keyboard: false,
          zIndexOffset: 2000,
        }).addTo(map);
        marker.getElement()?.setAttribute("aria-label", "Dein Standort");
        marker.getElement()?.setAttribute("role", "img");
      },
      () => handlers.current.onLocationError?.(),
      { enableHighAccuracy: true, maximumAge: 10_000, timeout: 20_000 },
    );
    return () => {
      navigator.geolocation.clearWatch(watch);
      marker?.remove();
    };
  }, [L, ready, showLocation]);

  return (
    <div
      aria-label={label}
      className={cn(
        "tour-map-canvas",
        !interactive && "is-static",
        onPlace && "is-placing",
        className,
      )}
      data-ready={ready ? "true" : undefined}
      data-testid="tour-map-canvas"
      role="region"
    >
      {/* Leaflet owns this element's classes; React never re-renders them. */}
      <div className="tour-map-host" ref={host} />
      {onPlace && placeAtCenterLabel ? (
        <>
          <span aria-hidden="true" className="tour-map-crosshair" />
          <button
            className={cn(
              buttonClassName({ size: "sm", variant: "secondary" }),
              "tour-map-center",
            )}
            onClick={() => {
              const center = mapRef.current?.getCenter();
              if (center) onPlace(center.lat, center.lng);
            }}
            type="button"
          >
            {placeAtCenterLabel}
          </button>
        </>
      ) : null}
    </div>
  );
}
