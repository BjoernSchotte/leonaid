"""Demo delivery day for Krapfentaxi 2026 on top of Golden Dataset v1.

Local and test instances only. Adds two drivers (Dora and Emil Fahrer) and
14 confirmed orders in Bad Tölz for Saturday 2026-12-05, spread over the
windows 08-10, 10-12 and 12-14 (5/5/4): Dora drives 7 (2 already delivered),
Emil 4, 3 have no driver yet. The start point is the bakery "Bäckerei" in
the Marktstraße; the worker geocodes it (no coordinates are written here).
The versioned Golden Dataset stays unchanged.

Orders, windows, driver assignments and the delivered ticks go through the
same application services and repositories as the app. Accounts, driver
memberships and the demo offering use the Golden seed's upsert pattern.

Idempotent: fixed IDs and idempotency keys; a second run changes nothing.
Run it with ``./leonaid demo-tours`` after ``./leonaid seed``.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timezone
from typing import Any
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

import asyncpg

from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.adapters.postgres.delivery import AsyncpgDeliveryRepository
from leonaid.adapters.feature_flags.openfeature import (
    LeonAidFeatureProvider,
    OpenFeatureBooleanEvaluator,
)
from leonaid.adapters.postgres.delivery_board import AsyncpgDeliveryBoardRepository
from leonaid.adapters.postgres.feature_flags import AsyncpgFeatureFlagRepository
from leonaid.application.commitments import CommitmentDraft, CommitmentLineDraft
from leonaid.application.delivery import DeliveryService
from leonaid.application.delivery_board import DeliveryBoardService
from leonaid.application.feature_flags import FeatureFlagService
from leonaid.application.errors import ApplicationError
from leonaid.application.policies import require_action_manager
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
from leonaid.domain.delivery_board import DeliveryBoard, DropState
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
)

NAMESPACE = UUID("5f0c8a52-3d1e-4b7a-9c61-0d2e4f7a8b93")
ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")  # Krapfentaxi 2026
ACTION_NAME = "Krapfentaxi 2026"
# Klara Kern, the Golden charity admin of the action, assigns and configures.
MANAGER_ID = UUID("10000000-0000-4000-8000-000000000002")
DELIVERY_DAY = date(2026, 12, 5)
# The same windows as tools/delivery/demo-configuration.mjs: both days.
WINDOW_DAYS = (date(2026, 12, 4), DELIVERY_DAY)
WINDOW_HOURS = ((8, 10), (10, 12), (12, 14))
REQUEST_ID = "demo-tours"
CITY = "Bad Tölz"
POSTAL_CODE = "83646"
# Where Dora and Emil pick up the Krapfen (D11): a bakery in the Marktstraße
# (Bäckerei Büttner, public business address). The worker finds the point.
START_LABEL = "Bäckerei"
START_ADDRESS = f"Marktstraße 50, {POSTAL_CODE} {CITY}"

# A demo offering priced per Krapfen, so orders of 6 to 48 pieces exist.
# It is active only while this seed books new orders: the public order form
# keeps showing the Golden offerings alone.
OFFERING_ID = uuid5(NAMESPACE, "offering:krapfen-einzeln")
OFFERING_FROM = datetime(2026, 7, 1, tzinfo=timezone.utc)
OFFERING_UNTIL = datetime(2026, 12, 6, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class Driver:
    key: str
    email: str
    display_name: str

    @property
    def id(self) -> UUID:
        return uuid5(NAMESPACE, f"driver:{self.key}")


DORA = Driver("dora", "dora.fahrer@leonaid.invalid", "Dora Fahrer")
EMIL = Driver("emil", "emil.fahrer@leonaid.invalid", "Emil Fahrer")
DRIVERS = (DORA, EMIL)


@dataclass(frozen=True, slots=True)
class DemoOrder:
    slug: str
    starts_hour: int
    company: bool
    recipient: str
    street: str
    pieces: int
    driver: Driver | None = None
    delivered: bool = False
    contact_name: str | None = None
    contact_phone: str | None = None

    @property
    def idempotency_key(self) -> str:
        return f"demo-tours:v1:{self.slug}"


# Addresses of public places in Bad Tölz (town hall, library, Kurhaus,
# schools, museum, shops in the Marktstraße) with their real house numbers,
# so that later geocoding never hits a private home. Recipients and phone
# numbers are invented.
ORDERS = (
    DemoOrder(
        "autohaus-isarwinkel",
        8,
        True,
        "Autohaus Isarwinkel GmbH",
        "Prof.-Max-Lange-Platz 1",
        48,
        DORA,
        True,
        "Frau Brandl",
        "+49 8041 990101",
    ),
    DemoOrder(
        "kanzlei-huber",
        8,
        True,
        "Kanzlei Huber & Partner",
        "Am Schloßplatz 1",
        24,
        DORA,
        True,
    ),
    DemoOrder(
        "maria-obermaier", 8, False, "Maria Obermaier", "Marktstraße 48", 6, DORA
    ),
    DemoOrder(
        "physio-kurpark",
        8,
        True,
        "Physiotherapie am Kurpark",
        "Ludwigstraße 25",
        18,
        EMIL,
        False,
        "Empfang",
        "+49 8041 990104",
    ),
    DemoOrder(
        "ingenieurbuero-lechner",
        8,
        True,
        "Ingenieurbüro Lechner",
        "Max-Höfler-Platz 1",
        30,
    ),
    DemoOrder(
        "thomas-gschwendtner",
        10,
        False,
        "Thomas Gschwendtner",
        "Hindenburgstraße 21",
        12,
        DORA,
        False,
        None,
        "+49 8041 990106",
    ),
    DemoOrder(
        "zahnarzt-reiser",
        10,
        True,
        "Zahnarztpraxis Dr. Reiser",
        "Marktstraße 35",
        24,
        DORA,
    ),
    DemoOrder(
        "kinderhaus-sonnenschein",
        10,
        True,
        "Kinderhaus Sonnenschein",
        "Alter Bahnhofplatz 5",
        36,
        EMIL,
        False,
        "Frau Kiefersauer",
        "+49 8041 990108",
    ),
    DemoOrder(
        "steuerbuero-wallner",
        10,
        True,
        "Steuerbüro Wallner",
        "Marktstraße 21",
        12,
        EMIL,
    ),
    DemoOrder("familie-rieger", 10, False, "Familie Rieger", "Mühlgasse 9", 6),
    DemoOrder(
        "schreinerei-fischbacher",
        12,
        True,
        "Schreinerei Fischbacher",
        "Krankenhausstraße 45",
        42,
        DORA,
        False,
        "Herr Fischbacher",
        "+49 8041 990111",
    ),
    DemoOrder("anna-demmel", 12, False, "Anna Demmel", "Hindenburgstraße 26", 6, DORA),
    DemoOrder(
        "versicherung-kapfhammer",
        12,
        True,
        "Versicherungsbüro Kapfhammer",
        "Marktstraße 51",
        24,
        EMIL,
        False,
        None,
        "+49 8041 990113",
    ),
    DemoOrder("hotel-isarufer", 12, True, "Hotel am Isarufer", "Badstraße 28", 48),
)


class DemoSeedError(RuntimeError):
    """The instance is not in the state this demo builds on."""


def require_non_production_environment() -> None:
    if os.environ.get("LEONAID_ENV") not in {"local", "test"}:
        raise DemoSeedError(
            "demo data is allowed only in local/test; "
            "production and unknown environments are refused"
        )


async def load_principal(pool: asyncpg.Pool[Any], user_id: UUID) -> IdentityPrincipal:
    """The principal the app would build for this account's session."""

    account = await pool.fetchrow(
        "SELECT id, email, display_name, status, email_verified_at"
        " FROM user_account WHERE id = $1",
        user_id,
    )
    if account is None:
        raise DemoSeedError(f"account {user_id} is missing; run ./leonaid seed first")
    roles = await pool.fetch(
        "SELECT role FROM user_global_role WHERE user_id = $1", user_id
    )
    memberships = await pool.fetch(
        """
        SELECT membership.id, membership.action_id, action.name,
            membership.role, membership.active_from, membership.active_until,
            membership.delegate_user_id
        FROM action_membership AS membership
        JOIN charity_action AS action ON action.id = membership.action_id
        WHERE membership.user_id = $1
          AND membership.active_from <= now()
          AND (membership.active_until IS NULL OR membership.active_until > now())
        """,
        user_id,
    )
    return IdentityPrincipal(
        UserAccount(
            account["id"],
            str(account["email"]),
            str(account["display_name"]),
            AccountStatus(str(account["status"])),
            account["email_verified_at"],
        ),
        frozenset(GlobalRole(str(row["role"])) for row in roles),
        tuple(
            ActionMembership(
                row["id"],
                row["action_id"],
                str(row["name"]),
                user_id,
                ActionRole(str(row["role"])),
                row["active_from"],
                row["active_until"],
                row["delegate_user_id"],
            )
            for row in memberships
        ),
    )


async def ensure_drivers(pool: asyncpg.Pool[Any]) -> None:
    """Active accounts with the driver role; login stays passwordless."""

    async with pool.acquire() as connection:
        async with connection.transaction():
            for driver in DRIVERS:
                taken = await connection.fetchval(
                    "SELECT id FROM user_account WHERE lower(email) = $1",
                    driver.email,
                )
                if taken is not None and taken != driver.id:
                    raise DemoSeedError(
                        f"{driver.email} already belongs to another account"
                    )
                await connection.execute(
                    """
                    INSERT INTO user_account (id, email, display_name, status)
                    VALUES ($1, $2, $3, 'active')
                    ON CONFLICT (id) DO UPDATE
                    SET display_name = EXCLUDED.display_name,
                        status = EXCLUDED.status,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_account.display_name <> EXCLUDED.display_name
                       OR user_account.status <> EXCLUDED.status
                    """,
                    driver.id,
                    driver.email,
                    driver.display_name,
                )
                await connection.execute(
                    """
                    INSERT INTO action_membership (id, action_id, user_id, role)
                    VALUES ($1, $2, $3, 'driver')
                    ON CONFLICT (action_id, user_id, role) DO NOTHING
                    """,
                    uuid5(NAMESPACE, f"membership:{driver.key}"),
                    ACTION_ID,
                    driver.id,
                )


async def ensure_windows(
    pool: asyncpg.Pool[Any], manager: IdentityPrincipal
) -> dict[int, UUID]:
    """The demo windows, enabled, and the start point; returns the delivery
    day's windows by start hour."""

    service = DeliveryService(AsyncpgDeliveryRepository(pool))
    configuration = await service.get(manager, ACTION_ID)

    def find(day: date, starts: int, ends: int) -> DeliveryWindow | None:
        return next(
            (
                window
                for window in configuration.windows
                if not window.retired
                and window.delivery_on == day
                and window.starts_at == time(starts)
                and window.ends_at == time(ends)
            ),
            None,
        )

    additions = tuple(
        DeliveryWindow(
            id=uuid5(NAMESPACE, f"window:{day.isoformat()}:{starts:02d}"),
            action_id=ACTION_ID,
            delivery_on=day,
            starts_at=time(starts),
            ends_at=time(ends),
        )
        for day in WINDOW_DAYS
        for starts, ends in WINDOW_HOURS
        if find(day, starts, ends) is None
    )
    if additions or not configuration.enabled:
        configuration = await service.save(
            manager,
            replace(
                configuration,
                enabled=True,
                windows=configuration.windows + additions,
            ),
            request_id=REQUEST_ID,
        )
    start = configuration.start
    if start is None or (start.label, start.address) != (START_LABEL, START_ADDRESS):
        # The configuration path of the app; a repeated run changes nothing.
        configuration = await service.save(
            manager,
            replace(
                configuration, start=DeliveryStartPoint(START_LABEL, START_ADDRESS)
            ),
            request_id=REQUEST_ID,
        )
    windows: dict[int, UUID] = {}
    for starts, ends in WINDOW_HOURS:
        window = find(DELIVERY_DAY, starts, ends)
        if window is None:
            raise DemoSeedError(f"window {starts:02d}-{ends:02d} was not saved")
        windows[starts] = window.id
    return windows


def draft_for(order: DemoOrder, window_id: UUID) -> CommitmentDraft:
    kind = CommitmentPartyKind.COMPANY if order.company else CommitmentPartyKind.PERSON
    email = f"demo.{order.slug}@leonaid.invalid"
    contact = (
        DeliveryContactSnapshot(order.contact_name, order.contact_phone)
        if order.contact_name or order.contact_phone
        else None
    )
    return CommitmentDraft(
        BuyerSnapshot(
            kind, uuid5(NAMESPACE, f"party:{order.slug}"), order.recipient, email
        ),
        InvoiceRecipientSnapshot(
            order.recipient, order.street, POSTAL_CODE, CITY, email=email
        ),
        (CommitmentLineDraft(OFFERING_ID, order.pieces, OfferingUnit.PIECE),),
        DeliveryRecipientSnapshot(order.recipient, order.street, POSTAL_CODE, CITY),
        delivery_window_id=window_id,
        delivery_contact=contact,
        # A window a manager marked "ausgebucht" still takes demo orders.
        allow_full_window=True,
    )


async def ensure_orders(
    pool: asyncpg.Pool[Any], manager: IdentityPrincipal, windows: dict[int, UUID]
) -> dict[str, UUID]:
    """Confirmed orders; a repeated run replays them by idempotency key."""

    require_action_manager(manager, ACTION_ID)
    keys = [order.idempotency_key for order in ORDERS]
    stored = await pool.fetchval(
        "SELECT count(*) FROM command_receipt WHERE idempotency_key = ANY($1::text[])",
        keys,
    )
    booking = stored != len(keys)
    await pool.execute(
        """
        INSERT INTO offering (
            id, action_id, code, name, status, unit, allowed_quantity_units,
            pieces_per_unit, unit_price_minor, currency,
            available_from, available_until
        )
        VALUES ($1, $2, 'krapfen-einzeln', 'Krapfen einzeln', $3, 'piece',
            ARRAY['piece'], 1, 150, 'EUR', $4, $5)
        ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status
        WHERE offering.status <> EXCLUDED.status
        """,
        OFFERING_ID,
        ACTION_ID,
        "active" if booking else "inactive",
        OFFERING_FROM,
        OFFERING_UNTIL,
    )
    repository = AsyncpgCommitmentRepository(pool)
    # The app has no command that confirms an order yet; like the Golden
    # seed, the demo stores its orders as confirmed. Everything else
    # (pricing, window booking, receipts, audit) is the app's create path.
    status = CommitmentStatus.CONFIRMED
    source = CommitmentSource.ADMIN
    created: dict[str, UUID] = {}
    try:
        for order in ORDERS:
            draft = draft_for(order, windows[order.starts_hour])
            commitment = await repository.create(
                action_id=ACTION_ID,
                actor_user_id=manager.account.id,
                source=source,
                status=status,
                draft=draft,
                idempotency_key=order.idempotency_key,
                request_hash=draft.fingerprint(
                    action_id=ACTION_ID, source=source, status=status
                ),
                request_id=REQUEST_ID,
                occurred_at=datetime.now(timezone.utc),
            )
            if commitment.status is CommitmentStatus.CANCELLED:
                raise DemoSeedError(f"demo order {order.slug} was cancelled")
            created[order.slug] = commitment.id
    finally:
        if booking:
            await pool.execute(
                "UPDATE offering SET status = 'inactive' WHERE id = $1", OFFERING_ID
            )
    return created


async def manager_board(
    service: DeliveryBoardService, manager: IdentityPrincipal
) -> DeliveryBoard:
    board = await service.board(
        manager, ACTION_ID, day=DELIVERY_DAY, viewed_at=datetime.now(timezone.utc)
    )
    if board.day != DELIVERY_DAY:
        raise DemoSeedError(f"the board shows {board.day}, not {DELIVERY_DAY}")
    return board


def board_service(pool: asyncpg.Pool[Any]) -> DeliveryBoardService:
    """The board with the real flag service (missed needs delivery.tours)."""

    flags = FeatureFlagService(
        AsyncpgFeatureFlagRepository(pool),
        OpenFeatureBooleanEvaluator(LeonAidFeatureProvider()),
    )
    return DeliveryBoardService(AsyncpgDeliveryBoardRepository(pool), flags=flags)


async def ensure_tours(
    pool: asyncpg.Pool[Any],
    manager: IdentityPrincipal,
    orders: dict[str, UUID],
) -> DeliveryBoard:
    service = board_service(pool)
    for driver in (*DRIVERS, None):
        await service.assign_driver(
            manager,
            ACTION_ID,
            commitment_ids=tuple(
                orders[order.slug] for order in ORDERS if order.driver == driver
            ),
            driver_user_id=driver.id if driver else None,
            request_id=REQUEST_ID,
            occurred_at=datetime.now(timezone.utc),
        )
    # The manager view needs no driver read audit; the ticks are Dora's own.
    drops = {
        drop.commitment_id: drop
        for window in (await manager_board(service, manager)).windows
        for drop in window.drops
    }
    for order in ORDERS:
        if not order.delivered or order.driver is None:
            continue
        drop = drops[orders[order.slug]]
        if drop.state is DropState.DELIVERED:
            continue
        await service.set_state(
            await load_principal(pool, order.driver.id),
            ACTION_ID,
            drop.commitment_id,
            delivered=True,
            expected_revision=drop.revision,
            request_id=REQUEST_ID,
            occurred_at=datetime.now(timezone.utc),
        )
    board = await manager_board(service, manager)
    on_board = {
        drop.commitment_id: drop for window in board.windows for drop in window.drops
    }
    for order in ORDERS:
        shown = on_board.get(orders[order.slug])
        wanted = order.driver.id if order.driver else None
        if shown is None or shown.driver_user_id != wanted:
            raise DemoSeedError(f"demo order {order.slug} is not on its tour")
        if order.delivered and shown.state is not DropState.DELIVERED:
            raise DemoSeedError(f"demo order {order.slug} is not delivered")
    return board


def report(board: DeliveryBoard, orders: dict[str, UUID]) -> None:
    demo = set(orders.values())
    names = {driver.id: driver.display_name for driver in DRIVERS}
    zone = ZoneInfo(board.timezone)
    print("demo-tours: OK: Krapfentaxi 2026, Sa 05.12.2026")
    print(f"  start    {START_LABEL}, {START_ADDRESS} (the worker geocodes it)")
    for driver in DRIVERS:
        print(f"  account  {driver.email}  ({driver.display_name}, driver)")
    for window in board.windows:
        drops = [drop for drop in window.drops if drop.commitment_id in demo]
        if not drops:
            continue
        start = window.starts_at.astimezone(zone).strftime("%H:%M")
        end = window.ends_at.astimezone(zone).strftime("%H:%M")
        drivers = Counter(
            names.get(drop.driver_user_id, "?")
            if drop.driver_user_id
            else "ohne Fahrer"
            for drop in drops
        )
        delivered = sum(drop.state is DropState.DELIVERED for drop in drops)
        split = ", ".join(f"{name} {count}" for name, count in sorted(drivers.items()))
        print(
            f"  window   {start}-{end}  {len(drops)} orders ({split};"
            f" {delivered} delivered)"
        )
    totals = Counter(
        order.driver.display_name if order.driver else "ohne Fahrer" for order in ORDERS
    )
    print(
        "  drivers  "
        + ", ".join(f"{name} {count}" for name, count in sorted(totals.items()))
    )
    print("  login    passwordless; the sign-in code arrives in Mailpit (/mail/)")


async def run() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=4, command_timeout=30
    )
    try:
        name = await pool.fetchval(
            "SELECT name FROM charity_action WHERE id = $1", ACTION_ID
        )
        if name != ACTION_NAME:
            raise DemoSeedError(f"{ACTION_NAME} is missing; run ./leonaid seed first")
        manager = await load_principal(pool, MANAGER_ID)
        await ensure_drivers(pool)
        windows = await ensure_windows(pool, manager)
        orders = await ensure_orders(pool, manager, windows)
        board = await ensure_tours(pool, manager, orders)
        report(board, orders)
    finally:
        await pool.close()


def main() -> int:
    try:
        require_non_production_environment()
        asyncio.run(run())
    except (
        DemoSeedError,
        DomainInvariantError,
        ApplicationError,
        asyncpg.PostgresError,
        OSError,
        KeyError,
    ) as error:
        print(f"demo-tours: ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
