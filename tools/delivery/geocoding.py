"""Geocoding of delivery addresses against real PostgreSQL and real HTTP.

specs/krapfentaxi-touren §5, §8.2, D5, D14 e. The geocoder under test is the
production ``NominatimGeocoder``; it talks to a Nominatim-compatible HTTP
server on 127.0.0.1 with canned answers per postal code. The proof shows the
flag and day scope, that only the four address fields leave the server, the
stored ``found``/``not_found``/``failed`` rows and their retry, the 1 request/s
throttle, stale rows after an address change, the manual pin, the advisory
lock, the privacy erasure, and the action's start point (D11): the worker
looks it up once per address, the API never does.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time as monotonic
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.feature_flags.openfeature import (
    LeonAidFeatureProvider,
    OpenFeatureBooleanEvaluator,
)
from leonaid.adapters.nominatim import NominatimGeocoder
from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.adapters.postgres.delivery import AsyncpgDeliveryRepository
from leonaid.adapters.postgres.delivery_geo import AsyncpgDeliveryGeoRepository
from leonaid.adapters.postgres.feature_flags import AsyncpgFeatureFlagRepository
from leonaid.adapters.postgres.privacy import AsyncpgPrivacyRepository
from leonaid.application.commitments import CommitmentDraft, CommitmentLineDraft
from leonaid.application.delivery_geo import GeocodingJob
from leonaid.application.feature_flags import FeatureFlagService
from leonaid.application.privacy import PrivacyService
from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.commitments import (
    BuyerSnapshot,
    CommitmentPartyKind,
    CommitmentSource,
    CommitmentStatus,
    DeliveryRecipientSnapshot,
    InvoiceRecipientSnapshot,
)
from leonaid.domain.delivery import (
    DeliveryContactSnapshot,
    DeliveryStartPoint,
    DeliveryWindow,
)
from leonaid.domain.delivery_geo import Found, GeocodeQuery, GeoPoint, PendingGeocode
from leonaid.domain.identity import (
    AccountStatus,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
)

REQUEST = "geocoding-proof"
USER_AGENT = "LeonAid geocoding proof (proof@example.invalid)"
# 08:00 in Berlin on the "today" of this proof; other proofs use earlier days.
NOW = datetime(2037, 12, 30, 7, tzinfo=timezone.utc)
YESTERDAY, TODAY, TOMORROW = date(2037, 12, 29), date(2037, 12, 30), date(2037, 12, 31)
QUERY_KEYS = {
    "street",
    "postalcode",
    "city",
    "countrycodes",
    "format",
    "addressdetails",
    "limit",
}
PHONE = "+49 30 98765"
# Canned answers per postal code: lat, lon, importance and returned postcode.
FOUND = {
    "10115": ("52.532000", "13.384000", 0.41, "10115"),
    "10178": ("52.521000", "13.410000", 0.33, "10178"),
    "10117": ("52.517000", "13.389000", 0.01, "10117"),  # too unsure
    "10119": ("52.530000", "13.400000", 0.50, "10999"),  # other postcode
}
SLOW_POSTCODE = "99999"  # answers after 2 s; the geocoder gives up at 0.5 s
BROKEN_POSTCODE = "50000"  # 503


class _GeocoderServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _GeocoderHandler)
        self.requests: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def taken(self) -> list[dict[str, Any]]:
        """The requests since the last call."""
        with self.lock:
            taken, self.requests = self.requests, []
        return taken

    def handle_error(self, request: object, client_address: object) -> None:
        # The slow answer meets a client that already gave up: expected.
        return


class _GeocoderHandler(BaseHTTPRequestHandler):
    server: _GeocoderServer

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        parts = urlsplit(self.path)
        params = {key: values[0] for key, values in parse_qs(parts.query).items()}
        with self.server.lock:
            self.server.requests.append(
                {
                    "path": parts.path,
                    "raw": self.path,
                    "params": params,
                    "userAgent": self.headers.get("User-Agent"),
                }
            )
        postcode = params.get("postalcode", "")
        if postcode == SLOW_POSTCODE:
            monotonic.sleep(2)
        if postcode == BROKEN_POSTCODE:
            self._send(503, b"busy")
            return
        answer = FOUND.get(postcode)
        document: list[dict[str, Any]] = []
        if answer is not None:
            lat, lon, importance, returned = answer
            document.append(
                {
                    "lat": lat,
                    "lon": lon,
                    "importance": importance,
                    "address": {"postcode": returned, "city": params.get("city")},
                }
            )
        self._send(200, json.dumps(document).encode())

    def _send(self, status: int, body: bytes) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def geocoder_server() -> Iterator[_GeocoderServer]:
    server = _GeocoderServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


class _Fixture:
    def __init__(
        self,
        pool: asyncpg.Pool,
        action_id: UUID,
        admin_id: UUID,
        server: _GeocoderServer,
    ) -> None:
        self.pool = pool
        self.action_id = action_id
        self.admin_id = admin_id
        self.server = server
        self.url = f"http://127.0.0.1:{server.server_address[1]}/search"
        self.repository = AsyncpgDeliveryGeoRepository(pool)
        self.flags = FeatureFlagService(
            AsyncpgFeatureFlagRepository(pool),
            OpenFeatureBooleanEvaluator(LeonAidFeatureProvider()),
        )
        self.orders = AsyncpgCommitmentRepository(pool)
        self.geocoders: list[NominatimGeocoder] = []
        self.offering_id: UUID | None = None
        self.yesterday = DeliveryWindow(
            uuid4(), action_id, YESTERDAY, time(8), time(10)
        )
        self.today = DeliveryWindow(uuid4(), action_id, TODAY, time(8), time(10))
        self.tomorrow = DeliveryWindow(uuid4(), action_id, TOMORROW, time(8), time(10))
        # Orders of the first section, used again later.
        self.past = self.first = self.second = UUID(int=0)

    async def setup(self) -> None:
        schedules = AsyncpgDeliveryRepository(self.pool)
        configuration = await schedules.get(self.action_id)
        await schedules.save(
            replace(
                configuration,
                windows=(
                    *configuration.windows,
                    self.yesterday,
                    self.today,
                    self.tomorrow,
                ),
            )
        )

    def job(self, *, min_interval: float = 0.0) -> GeocodingJob:
        geocoder = NominatimGeocoder(
            self.url, USER_AGENT, min_interval=min_interval, timeout=0.5
        )
        self.geocoders.append(geocoder)
        return GeocodingJob(
            AsyncpgDeliveryGeoRepository(self.pool), geocoder, self.flags
        )

    async def close(self) -> None:
        for geocoder in self.geocoders:
            await geocoder.close()

    async def flag(self, enabled: bool) -> None:
        await self.pool.execute(
            "UPDATE feature_flag SET enabled=$1, revision=revision+1"
            " WHERE key='delivery.tours'",
            enabled,
        )

    async def order(
        self,
        name: str,
        street: str,
        postal_code: str,
        window: DeliveryWindow | None = None,
        *,
        email: str | None = None,
    ) -> UUID:
        if self.offering_id is None:
            self.offering_id = await self.pool.fetchval(
                "SELECT id FROM offering WHERE action_id=$1 LIMIT 1", self.action_id
            )
        assert self.offering_id is not None
        draft = CommitmentDraft(
            BuyerSnapshot(
                CommitmentPartyKind.PERSON,
                uuid4(),
                name,
                email or f"geo.{uuid4().hex[:8]}@example.invalid",
            ),
            InvoiceRecipientSnapshot(name, "Rechnungsweg 1", "12345", "Berlin"),
            (CommitmentLineDraft(self.offering_id, 1, OfferingUnit.BOX, 3600),),
            DeliveryRecipientSnapshot(name, street, postal_code, "Berlin"),
            delivery_window_id=(window or self.today).id,
            delivery_contact=DeliveryContactSnapshot("Pförtner", PHONE),
        )
        status = CommitmentStatus.REVIEW_READY
        created = await self.orders.create(
            action_id=self.action_id,
            actor_user_id=self.admin_id,
            source=CommitmentSource.ADMIN,
            status=status,
            draft=draft,
            idempotency_key=f"geocoding:{uuid4()}",
            request_hash=draft.fingerprint(
                action_id=self.action_id, source=CommitmentSource.ADMIN, status=status
            ),
            request_id=REQUEST,
            occurred_at=NOW,
        )
        return created.id

    async def row(self, commitment_id: UUID) -> asyncpg.Record | None:
        return await self.pool.fetchrow(
            "SELECT * FROM delivery_geo WHERE commitment_id=$1", commitment_id
        )

    async def move(self, commitment_id: UUID, street: str, postal_code: str) -> None:
        # What a delivery completion does to the address snapshot.
        await self.pool.execute(
            """
            UPDATE commitment SET delivery_recipient_snapshot =
                delivery_recipient_snapshot
                || jsonb_build_object('streetLine1', $2::text, 'postalCode', $3::text)
            WHERE id = $1
            """,
            commitment_id,
            street,
            postal_code,
        )


def _streets(requests: list[dict[str, Any]]) -> list[str]:
    return sorted(str(item["params"]["street"]) for item in requests)


async def prove_geocoding(pool: asyncpg.Pool, action_id: UUID, admin_id: UUID) -> None:
    with geocoder_server() as server:
        fx = _Fixture(pool, action_id, admin_id, server)
        await fx.setup()
        try:
            await prove_geocoding_respects_flag_and_scope(fx)
            await fx.flag(True)
            await _prove_outcomes(fx)
            await _prove_throttle(fx)
            await _prove_changed_address_and_pin(fx)
            await _prove_advisory_lock(fx)
            await _prove_privacy_erasure(fx)
            await _prove_start_point(fx)
        finally:
            await fx.flag(False)
            await fx.close()
    print(
        "GEOCODING PASS: flag off asks nothing, past days never, four address"
        " fields only, no address in audit/outbox, found/not_found/failed rows"
        " with three retries an hour apart, 1 request/s, changed address"
        " re-geocodes, manual pin kept until the address changes, one run per"
        " advisory lock, erasure deletes the row, start point looked up once"
        " per address (kept on a label change, a hand-set point wins)"
    )


async def prove_geocoding_respects_flag_and_scope(fx: _Fixture) -> None:
    fx.past = await fx.order("Geo Gestern", "Gestrige Gasse 1", "10115", fx.yesterday)
    fx.first = await fx.order("Geo Heute", "Heutiger Weg 1", "10115", fx.today)
    fx.second = await fx.order("Geo Morgen", "Morgiger Weg 2", "10115", fx.tomorrow)
    await fx.flag(False)
    assert await fx.job().run_once(now=NOW) == 0
    assert fx.server.taken() == []
    # The stops are there; only the flag holds the job back.
    pending = await fx.repository.pending(today=TODAY, now=NOW, limit=30)
    assert {item.commitment_id for item in pending} == {fx.first, fx.second}

    await fx.flag(True)
    counts = (
        "SELECT (SELECT count(*) FROM audit_event), (SELECT count(*) FROM outbox_event)"
    )
    before = tuple(await fx.pool.fetchrow(counts))
    assert await fx.job().run_once(now=NOW) == 2
    requests = fx.server.taken()
    assert _streets(requests) == ["Heutiger Weg 1", "Morgiger Weg 2"]
    for request in requests:
        assert request["path"] == "/search"
        assert set(request["params"]) == QUERY_KEYS, request["params"]
        assert request["params"]["countrycodes"] == "de"
        assert request["params"]["city"] == "Berlin"
        assert request["userAgent"] == USER_AGENT
        # No name, contact or phone of the order leaves the server.
        for secret in ("Geo", "Pförtner", PHONE, "98765", "example.invalid"):
            assert secret not in request["raw"] and secret not in str(
                request["params"]
            ), secret
    assert await fx.row(fx.past) is None
    # The job writes no audit event and no outbox job, so no address there.
    assert tuple(await fx.pool.fetchrow(counts)) == before
    for table in ("audit_event", "outbox_event"):
        assert not await fx.pool.fetchval(
            f"SELECT count(*) FROM {table} WHERE payload::text LIKE '%Heutiger Weg%'"
        ), table


async def _prove_outcomes(fx: _Fixture) -> None:
    found = await fx.row(fx.first)
    assert found is not None
    assert (found["outcome"], found["source"], found["attempts"]) == (
        "found",
        "geocoder",
        1,
    )
    assert (found["lat"], found["lon"]) == (Decimal("52.532000"), Decimal("13.384000"))
    assert found["geocoder"] == "nominatim:127.0.0.1"
    assert len(found["address_hash"]) == 64

    unsure = await fx.order("Geo Unsicher", "Unsichere Straße 3", "10117")
    elsewhere = await fx.order("Geo Anderswo", "Andere Straße 4", "10119")
    nothing = await fx.order("Geo Nichts", "Unbekannter Pfad 5", "10999")
    broken = await fx.order("Geo Kaputt", "Kaputte Allee 6", BROKEN_POSTCODE)
    slow = await fx.order("Geo Langsam", "Langsamer Ring 7", SLOW_POSTCODE)
    assert await fx.job().run_once(now=NOW) == 5
    assert len(fx.server.taken()) == 5
    for commitment_id in (unsure, elsewhere, nothing):
        row = await fx.row(commitment_id)
        assert row is not None and row["outcome"] == "not_found"
        assert row["lat"] is None and row["lon"] is None
    for commitment_id in (broken, slow):
        row = await fx.row(commitment_id)
        assert row is not None and row["outcome"] == "failed"
        assert row["attempts"] == 1 and row["lat"] is None

    # Nothing is asked again at once; not_found never for the same address.
    assert await fx.job().run_once(now=NOW) == 0
    assert fx.server.taken() == []
    # A failure is asked again after an hour, three times at most.
    for hours, attempts in ((1, 2), (2, 3)):
        assert await fx.job().run_once(now=NOW + timedelta(hours=hours)) == 2
        assert sorted(item["params"]["postalcode"] for item in fx.server.taken()) == [
            BROKEN_POSTCODE,
            SLOW_POSTCODE,
        ]
        for commitment_id in (broken, slow):
            row = await fx.row(commitment_id)
            assert row is not None and row["attempts"] == attempts
    assert await fx.job().run_once(now=NOW + timedelta(hours=5)) == 0
    assert fx.server.taken() == []
    # The pin is the way out (spec §6.4); the database refuses a half point.
    for sql in (
        "UPDATE delivery_geo SET lat = 1 WHERE commitment_id = $1",
        "UPDATE delivery_geo SET source = 'manual' WHERE commitment_id = $1",
        "UPDATE delivery_geo SET outcome = 'found' WHERE commitment_id = $1",
    ):
        try:
            await fx.pool.execute(sql, broken)
        except asyncpg.CheckViolationError:
            pass
        else:
            raise AssertionError(sql)


async def _prove_throttle(fx: _Fixture) -> None:
    for number in range(3):
        await fx.order(f"Geo Takt {number}", f"Taktstraße {number}", "10115")
    started = monotonic.monotonic()
    assert await fx.job(min_interval=1.0).run_once(now=NOW) == 3
    elapsed = monotonic.monotonic() - started
    assert elapsed >= 2.0, elapsed
    assert len(fx.server.taken()) == 3


async def _prove_changed_address_and_pin(fx: _Fixture) -> None:
    before = await fx.row(fx.second)
    assert before is not None and before["outcome"] == "found"
    await fx.move(fx.second, "Neue Adresse 9", "10178")
    pending = await fx.repository.pending(today=TODAY, now=NOW, limit=30)
    assert [item.commitment_id for item in pending] == [fx.second]
    assert await fx.job().run_once(now=NOW) == 1
    assert _streets(fx.server.taken()) == ["Neue Adresse 9"]
    after = await fx.row(fx.second)
    assert after is not None and after["address_hash"] != before["address_hash"]
    assert (after["lat"], after["lon"], after["attempts"]) == (
        Decimal("52.521000"),
        Decimal("13.410000"),
        1,
    )

    # A lookup made for the old address is dropped once the address changed.
    assert not await fx.repository.pending(today=TODAY, now=NOW, limit=30)
    await fx.move(fx.second, "Zwischenstand 1", "10115")
    (old,) = await fx.repository.pending(today=TODAY, now=NOW, limit=30)
    await fx.move(fx.second, "Endstand 2", "10178")
    lookup = Found(GeoPoint(Decimal(1), Decimal(1)), 0.9)
    assert not await fx.repository.record(old, lookup, geocoder="proof", at=NOW)
    kept = await fx.row(fx.second)
    assert kept is not None and kept["lat"] == Decimal("52.521000")

    # The manual pin survives while the address stays...
    pin = GeoPoint(Decimal("52.5"), Decimal("13.4"))
    await fx.repository.set_pin(
        action_id=fx.action_id, commitment_id=fx.second, point=pin, at=NOW
    )
    pinned = await fx.row(fx.second)
    assert pinned is not None
    assert (pinned["source"], pinned["outcome"], pinned["geocoder"]) == (
        "manual",
        "found",
        "manual",
    )
    assert (pinned["lat"], pinned["lon"]) == (pin.lat, pin.lon)
    assert not await fx.repository.pending(today=TODAY, now=NOW, limit=30)
    assert await fx.job().run_once(now=NOW) == 0
    assert fx.server.taken() == []
    # ... a late geocoder answer for the same address does not replace it ...
    same = PendingGeocode(
        fx.action_id,
        fx.second,
        TOMORROW,
        GeocodeQuery("Endstand 2", "10178", "Berlin", "DE"),
        pinned["address_hash"],
    )
    assert not await fx.repository.record(same, lookup, geocoder="proof", at=NOW)
    still = await fx.row(fx.second)
    assert still is not None and still["source"] == "manual"
    # ... and goes when the address changes.
    await fx.move(fx.second, "Letzte Adresse 3", "10115")
    assert await fx.job().run_once(now=NOW) == 1
    assert _streets(fx.server.taken()) == ["Letzte Adresse 3"]
    moved = await fx.row(fx.second)
    assert moved is not None and moved["source"] == "geocoder"
    assert moved["lat"] == Decimal("52.532000")


async def _prove_advisory_lock(fx: _Fixture) -> None:
    await fx.order("Geo Sperre 1", "Sperrweg 1", "10115")
    await fx.order("Geo Sperre 2", "Sperrweg 2", "10178")
    # A one-second gap keeps the first run inside the lock long enough.
    counts = await asyncio.gather(
        fx.job(min_interval=1.0).run_once(now=NOW),
        fx.job(min_interval=1.0).run_once(now=NOW),
    )
    assert sorted(counts) == [0, 2], counts
    assert _streets(fx.server.taken()) == ["Sperrweg 1", "Sperrweg 2"]
    # The lock is released: a later run gets it (and finds nothing to do).
    assert (
        await fx.pool.fetchval(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'"
        )
        == 0
    )


async def _prove_privacy_erasure(fx: _Fixture) -> None:
    email = "geo-subject@example.invalid"
    erased = await fx.order("Geo Löschung", "Löschweg 1", "10115", email=email)
    assert await fx.job().run_once(now=NOW) == 1
    fx.server.taken()
    repo = AsyncpgPrivacyRepository(fx.pool, subject_hmac_secret="synthetic-proof-" * 4)
    service = PrivacyService(repo)
    actor = IdentityPrincipal(
        UserAccount(fx.admin_id, "admin@example.invalid", "Test", AccountStatus.ACTIVE),
        frozenset({GlobalRole.SYSTEM_ADMIN}),
        (),
    )
    report = await service.export(actor, email=email)
    (delivery,) = report.order_deliveries
    assert delivery.coordinates == GeoPoint(Decimal("52.532"), Decimal("13.384"))
    await service.erase(actor, email=email, confirmation=email, request_id=REQUEST)
    assert await fx.row(erased) is None
    # The placeholder address of an erased order is never sent.
    assert await fx.job().run_once(now=NOW) == 0
    assert fx.server.taken() == []


async def _prove_start_point(fx: _Fixture) -> None:
    schedules = AsyncpgDeliveryRepository(fx.pool)

    async def save(start: DeliveryStartPoint | None) -> DeliveryStartPoint | None:
        current = await schedules.get(fx.action_id)
        return (await schedules.save(replace(current, start=start))).start

    found = "Startweg 1, 10178 Berlin"
    saved = await save(DeliveryStartPoint("Bäckerei", found, None))
    assert saved == DeliveryStartPoint("Bäckerei", found, None, locating=True)
    # Saving never asks the geocoder; the worker does.
    assert fx.server.taken() == []
    assert await fx.job().run_once(now=NOW) == 1
    (request,) = fx.server.taken()
    assert set(request["params"]) == QUERY_KEYS
    assert (
        request["params"]["street"],
        request["params"]["postalcode"],
        request["params"]["city"],
    ) == ("Startweg 1", "10178", "Berlin")
    start = (await schedules.get(fx.action_id)).start
    assert start == DeliveryStartPoint(
        "Bäckerei", found, GeoPoint.parse("52.521", "13.41")
    )
    row = await fx.pool.fetchrow(
        "SELECT start_geo_outcome, start_geo_attempts, start_geocoder"
        " FROM action_delivery_configuration WHERE action_id=$1",
        fx.action_id,
    )
    assert row is not None and tuple(row) == (
        "found",
        1,
        "nominatim:127.0.0.1",
    )
    # Found once: never asked again, and a label change keeps the point.
    assert await fx.job().run_once(now=NOW + timedelta(days=1)) == 0
    renamed = await save(DeliveryStartPoint("Backstube", found, None))
    assert renamed == DeliveryStartPoint("Backstube", found, start.point)
    assert await fx.job().run_once(now=NOW) == 0

    # An address without "street, postcode city": not found, no request.
    vague = await save(DeliveryStartPoint("Bäckerei", "Am Markt", None))
    assert vague is not None and vague.point is None and vague.locating
    assert await fx.job().run_once(now=NOW) == 0
    assert fx.server.taken() == []
    assert (await schedules.get(fx.action_id)).start == DeliveryStartPoint(
        "Bäckerei", "Am Markt", None, locating=False
    )

    # A provider failure is retried an hour later, like a stop.
    await save(DeliveryStartPoint("Bäckerei", "Startweg 2, 50000 Köln", None))
    assert await fx.job().run_once(now=NOW) == 1
    stored = (await schedules.get(fx.action_id)).start
    assert stored is not None and stored.point is None and stored.locating
    assert await fx.job().run_once(now=NOW) == 0
    assert await fx.job().run_once(now=NOW + timedelta(hours=1)) == 1
    fx.server.taken()
    # A late answer for an address the manager changed meanwhile is dropped.
    assert not await fx.repository.record_start(
        fx.action_id,
        "Startweg 2, 50000 Köln (alt)",
        Found(GeoPoint.parse("1", "1"), 0.9),
        geocoder="nominatim:127.0.0.1",
        at=NOW,
    )

    # A point set by hand wins and is never looked up.
    pinned = GeoPoint.parse("50.9375", "6.9603")
    hand = await save(DeliveryStartPoint("Bäckerei", "Domplatz, Köln", pinned))
    assert hand == DeliveryStartPoint("Bäckerei", "Domplatz, Köln", pinned)
    assert await fx.job().run_once(now=NOW + timedelta(hours=3)) == 0
    assert fx.server.taken() == []
    # The database refuses a point without an address.
    try:
        await fx.pool.execute(
            "UPDATE action_delivery_configuration SET start_label=NULL,"
            " start_address=NULL WHERE action_id=$1",
            fx.action_id,
        )
    except asyncpg.CheckViolationError:
        pass
    else:
        raise AssertionError("start point without an address was stored")
    assert await save(None) is None
    row = await fx.pool.fetchrow(
        "SELECT start_lat, start_geo_outcome, start_geo_attempts"
        " FROM action_delivery_configuration WHERE action_id=$1",
        fx.action_id,
    )
    assert row is not None and tuple(row) == (None, None, 0)
