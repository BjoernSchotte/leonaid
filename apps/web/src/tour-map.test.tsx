import { fireEvent, render, waitFor } from "@testing-library/react";
import {
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
  onTestFinished,
  vi,
} from "vitest";

import { TourMap, type TourMapPin } from "@leonaid/features";

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

afterEach(() => {
  vi.restoreAllMocks();
});

const tiles = {
  url: "/e2e-tiles/{z}/{x}/{y}.svg",
  attribution: "© OpenStreetMap-Mitwirkende",
};

const pins: TourMapPin[] = [
  {
    id: "b",
    lat: 47.761,
    lon: 11.559,
    rank: 2,
    tone: "driver-1",
    selected: false,
    label: "Stopp 2: Bäckerei",
  },
  {
    id: "a",
    lat: 47.76,
    lon: 11.56,
    rank: 1,
    tone: "driver-1",
    selected: true,
    label: "Stopp 1: Autohaus",
  },
  {
    id: "c",
    lat: 47.762,
    lon: 11.561,
    rank: 0,
    tone: "unassigned",
    selected: false,
  },
];

/** Leaflet loads on the first map; the canvas says when the view is set. */
async function ready(container: HTMLElement) {
  await waitFor(() =>
    expect(
      container
        .querySelector('[data-testid="tour-map-canvas"]')
        ?.getAttribute("data-ready"),
    ).toBe("true"),
  );
}

async function renderMap(extra: Partial<Parameters<typeof TourMap>[0]> = {}) {
  const onSelect = vi.fn();
  const view = render(
    <TourMap
      label="Tourkarte"
      line={{ ids: ["a", "b"], dashed: true }}
      onSelect={onSelect}
      pins={pins}
      start={{ lat: 47.759, lon: 11.558, label: "Lions-Halle" }}
      tiles={tiles}
      {...extra}
    />,
  );
  await ready(view.container);
  return { ...view, onSelect };
}

const pinElements = (container: HTMLElement) => [
  ...container.querySelectorAll<HTMLElement>(".tour-pin[data-pin-id]"),
];

describe("TourMap", () => {
  it("renders numbered divIcon pins in rank order", async () => {
    const { container } = await renderMap();
    const numbered = pinElements(container)
      .filter((pin) => pin.textContent)
      .sort((a, b) => Number(a.textContent) - Number(b.textContent));
    expect(numbered.map((pin) => pin.dataset.pinId)).toEqual(["a", "b"]);
    expect(numbered.map((pin) => pin.textContent)).toEqual(["1", "2"]);
    const [first] = numbered;
    expect([...first!.classList]).toEqual(
      expect.arrayContaining(["tour-pin", "tour-pin--driver-1", "is-selected"]),
    );
    expect(first!.getAttribute("aria-label")).toBe("Stopp 1: Autohaus");
    // A stop without an order gets a grey pin without a number.
    const unassigned = container.querySelector('[data-pin-id="c"]');
    expect(unassigned?.classList.contains("tour-pin--unassigned")).toBe(true);
    expect(unassigned?.textContent).toBe("");
    // No default marker images, only class-styled divIcons.
    expect(container.querySelector("img.leaflet-marker-icon")).toBeNull();
    expect(
      container.querySelector(".tour-pin--start")?.getAttribute("aria-label"),
    ).toBe("Start: Lions-Halle");
    // The draft order is a dashed line.
    expect(
      container
        .querySelector("path.tour-line")
        ?.classList.contains("is-dashed"),
    ).toBe(true);
  });

  it("no element has a style attribute set by markup", async () => {
    // Leaflet positions elements through the CSSOM (allowed by the CSP);
    // markup it parses (pin HTML, attribution) carries no style attribute.
    const { container } = await renderMap();
    const parsed = [
      ...container.querySelectorAll(
        ".tour-pin *, .tour-pin, .leaflet-control-attribution, .leaflet-control-attribution *",
      ),
    ];
    expect(parsed.length).toBeGreaterThan(0);
    for (const element of parsed) {
      const markup = element.innerHTML;
      expect(markup).not.toMatch(/style=/i);
    }
    for (const element of container.querySelectorAll(
      ".tour-pin *, .leaflet-control-attribution *",
    )) {
      expect(element.hasAttribute("style")).toBe(false);
    }
  });

  it("attribution text visible", async () => {
    const { container } = await renderMap({
      tiles: { ...tiles, attribution: "© OSM <Mitwirkende> & Co" },
    });
    const attribution = container.querySelector(".leaflet-control-attribution");
    // Plain text, escaped; no Leaflet prefix link.
    expect(attribution?.textContent).toContain("© OSM <Mitwirkende> & Co");
    expect(attribution?.querySelector("a")).toBeNull();
  });

  it("pins are 44 px targets around a smaller disc", async () => {
    const { container } = await renderMap();
    for (const pin of pinElements(container)) {
      // Leaflet sizes the marker through the CSSOM from iconSize.
      expect(pin.style.width).toBe("44px");
      expect(pin.style.height).toBe("44px");
      expect(pin.querySelector(".tour-pin-dot")).toBeTruthy();
    }
  });

  it("says ready only once the pins carry their ids", async () => {
    // Leaflet builds marker elements when the map loads; their ids come
    // with the next draw. "Ready" before that let a click find no pin.
    const seen: boolean[] = [];
    const observer = new MutationObserver((records) => {
      for (const record of records) {
        const canvas = record.target as HTMLElement;
        if (canvas.getAttribute("data-ready") !== "true") continue;
        const drawn = [...canvas.querySelectorAll(".tour-pin")].filter(
          (pin) => !pin.classList.contains("tour-pin--start"),
        );
        seen.push(
          drawn.length === pins.length &&
            drawn.every((pin) => pin.hasAttribute("data-pin-id")),
        );
      }
    });
    observer.observe(document.body, {
      attributeFilter: ["data-ready"],
      attributes: true,
      subtree: true,
    });
    await renderMap();
    observer.disconnect();
    expect(seen).toEqual([true]);
  });

  it("click on pin calls onSelect", async () => {
    const { container, onSelect } = await renderMap();
    const pin = container.querySelector<HTMLElement>('[data-pin-id="b"]');
    expect(pin).not.toBeNull();
    fireEvent.click(pin!);
    expect(onSelect).toHaveBeenCalledWith("b");
  });

  it("a static map has no focusable pins and no zoom buttons", async () => {
    const { container } = await renderMap({ interactive: false });
    expect(container.querySelector(".leaflet-control-zoom")).toBeNull();
    for (const pin of pinElements(container)) {
      expect(pin.hasAttribute("tabindex")).toBe(false);
      expect(pin.getAttribute("aria-hidden")).toBe("true");
    }
  });

  it("once placing ends, map and pin clicks place nothing", async () => {
    const onPlace = vi.fn();
    const { container, onSelect, rerender } = await renderMap({ onPlace });
    rerender(
      <TourMap
        label="Tourkarte"
        line={null}
        onSelect={onSelect}
        pins={pins}
        start={null}
        tiles={tiles}
      />,
    );
    const canvas = container.querySelector('[data-testid="tour-map-canvas"]');
    expect(canvas?.classList.contains("is-placing")).toBe(false);
    const host = container.querySelector<HTMLElement>(".leaflet-container")!;
    fireEvent.click(host, { clientX: 10, clientY: 10 });
    expect(onPlace).not.toHaveBeenCalled();
    fireEvent.click(container.querySelector<HTMLElement>('[data-pin-id="b"]')!);
    expect(onPlace).not.toHaveBeenCalled();
    expect(onSelect).toHaveBeenCalledWith("b");
  });

  it("while placing, a click on a pin places there instead of selecting it", async () => {
    const onPlace = vi.fn();
    const { container, onSelect } = await renderMap({ onPlace });
    const pin = container.querySelector<HTMLElement>('[data-pin-id="b"]')!;
    fireEvent.click(pin, { clientX: 30, clientY: 40 });
    expect(onSelect).not.toHaveBeenCalled();
    expect(onPlace).toHaveBeenCalledTimes(1);
    const [lat, lon] = onPlace.mock.calls[0]!;
    expect(Number.isFinite(lat)).toBe(true);
    expect(Number.isFinite(lon)).toBe(true);
  });

  it("a map click places a pin only when placing", async () => {
    const onPlace = vi.fn();
    const { container } = await renderMap({ onPlace });
    expect(
      container
        .querySelector('[data-testid="tour-map-canvas"]')
        ?.classList.contains("is-placing"),
    ).toBe(true);
    const host = container.querySelector<HTMLElement>(".leaflet-container")!;
    fireEvent.click(host, { clientX: 10, clientY: 10 });
    expect(onPlace).toHaveBeenCalledTimes(1);
    const [lat, lon] = onPlace.mock.calls[0]!;
    expect(Number.isFinite(lat)).toBe(true);
    expect(Number.isFinite(lon)).toBe(true);
  });

  it("watches the device location only while asked and never sends it", async () => {
    const watchPosition = vi.fn(() => 7);
    const clearWatch = vi.fn();
    const own = Object.getOwnPropertyDescriptor(navigator, "geolocation");
    Object.defineProperty(navigator, "geolocation", {
      configurable: true,
      value: { watchPosition, clearWatch },
    });
    onTestFinished(() => {
      // Back to jsdom's navigator (the property lives on its prototype).
      if (own) Object.defineProperty(navigator, "geolocation", own);
      else delete (navigator as { geolocation?: unknown }).geolocation;
    });
    // Restored by restoreAllMocks after each test.
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const { rerender } = await renderMap();
    expect(watchPosition).not.toHaveBeenCalled();
    const props = {
      label: "Tourkarte",
      line: null,
      onSelect: () => {},
      pins,
      start: null,
      tiles,
    };
    rerender(<TourMap {...props} showLocation />);
    expect(watchPosition).toHaveBeenCalledTimes(1);
    rerender(<TourMap {...props} showLocation={false} />);
    expect(clearWatch).toHaveBeenCalledWith(7);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
