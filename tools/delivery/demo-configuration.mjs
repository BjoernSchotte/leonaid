import assert from "node:assert/strict";

// Explicit local Golden-data configuration. Reusing existing window IDs makes
// repeated runs harmless to previously saved order snapshots.
export async function configureDeliveryDemo(request, origin, actionId) {
  const api = `${origin}/api/v1/actions/${actionId}`;
  const headers = { Origin: origin };
  const json = async (response) => {
    assert.equal(response.status(), 200, await response.text());
    return response.json();
  };
  const state = await json(await request.get(`${api}/management`));
  const action = state.action;
  assert.equal(
    action.name,
    "Krapfentaxi 2026",
    "Only the selected demo action",
  );
  if (action.endsOn < "2026-12-05") {
    await json(
      await request.put(`${api}/details`, {
        headers,
        data: {
          revision: action.revision,
          name: action.name,
          purpose: action.purpose,
          carrierName: action.carrierName,
          startsOn: action.startsOn,
          endsOn: "2026-12-31",
        },
      }),
    );
  }
  let configuration = await json(
    await request.get(`${api}/delivery-configuration`),
  );
  assert.equal(configuration.timezone, "Europe/Berlin");
  const additions = ["2026-12-04", "2026-12-05"]
    .flatMap((deliveryOn) =>
      [8, 10, 12].map((hour) => ({
        deliveryOn,
        startsAt: `${String(hour).padStart(2, "0")}:00`,
        endsAt: `${String(hour + 2).padStart(2, "0")}:00`,
      })),
    )
    .filter(
      (wanted) =>
        !configuration.windows.some(
          (window) =>
            !window.retired &&
            window.deliveryOn === wanted.deliveryOn &&
            window.startsAt.slice(0, 5) === wanted.startsAt &&
            window.endsAt.slice(0, 5) === wanted.endsAt,
        ),
    );
  if (!configuration.enabled || additions.length) {
    configuration = await json(
      await request.put(`${api}/delivery-configuration`, {
        headers,
        data: {
          expectedRevision: configuration.revision,
          enabled: true,
          timezone: configuration.timezone,
          windows: [...configuration.windows, ...additions],
        },
      }),
    );
  }
  return configuration;
}
