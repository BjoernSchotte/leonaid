"""Delivery day board against real PostgreSQL (KLF-062).

Proves per-drop drivers, the delivered/missed state with undo and audit,
window closure and reopening, the "Nachliefern" tasks with the tasks module
on and off, the driver's field and scope limits, and the read audit and its
90-day purge.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.adapters.postgres.delivery import AsyncpgDeliveryRepository
from leonaid.adapters.postgres.delivery_board import (
    AsyncpgDeliveryBoardRepository,
    order_link,
    order_reference,
    purge_read_audits,
)
from leonaid.application.commitments import CommitmentDraft, CommitmentLineDraft
from leonaid.application.delivery_board import DeliveryBoardService
from leonaid.application.errors import Conflict, PermissionDenied
from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.commitments import (
    BuyerSnapshot,
    CommitmentPartyKind,
    CommitmentSource,
    CommitmentStatus,
    DeliveryRecipientSnapshot,
    InvoiceRecipientSnapshot,
)
from leonaid.domain.delivery import DeliveryContactSnapshot
from leonaid.domain.delivery_board import DeliveryBoard, DeliveryDrop, DropState
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    IdentityPrincipal,
    UserAccount,
)
from leonaid.modules.tasks.delivery_follow_up import TaskDeliveryFollowUp


async def _user(pool: asyncpg.Pool, name: str) -> UUID:
    identifier = uuid4()
    await pool.execute(
        "INSERT INTO user_account(id,email,display_name,status)"
        " VALUES ($1,$2,$3,'active')",
        identifier,
        f"{identifier}@example.invalid",
        name,
    )
    return identifier


def _principal(user_id: UUID, action_id: UUID, role: ActionRole) -> IdentityPrincipal:
    user = UserAccount(user_id, "proof@example.invalid", "Proof", AccountStatus.ACTIVE)
    now = datetime.now(timezone.utc)
    return IdentityPrincipal(
        user,
        frozenset(),
        (ActionMembership(uuid4(), action_id, "Test", user.id, role, now),),
    )


async def _expect(operation: object, kind: type[Exception], code: str) -> None:
    try:
        await operation  # type: ignore[misc]
    except kind as error:
        assert getattr(error, "code", None) == code, (code, error)
    else:
        raise AssertionError(f"expected {code}")


async def prove_board(pool: asyncpg.Pool, action_id: UUID, admin_id: UUID) -> None:
    schedules = AsyncpgDeliveryRepository(pool)
    configuration = await schedules.get(action_id)
    # Earlier proofs retire some windows; orders need bookable ones.
    available = [item for item in configuration.windows if not item.retired]
    assert len(available) >= 2, "two bookable windows needed"
    window, other_window = available[0], available[1]
    offering_id = await pool.fetchval(
        "SELECT id FROM offering WHERE action_id=$1 LIMIT 1", action_id
    )
    orders = AsyncpgCommitmentRepository(pool)
    now = datetime.now(timezone.utc)

    async def order(name: str, window_id: UUID) -> UUID:
        draft = CommitmentDraft(
            BuyerSnapshot(
                CommitmentPartyKind.PERSON,
                uuid4(),
                name,
                f"{name.lower().replace(' ', '.')}@example.invalid",
            ),
            InvoiceRecipientSnapshot(name, "Rechnungsweg 1", "12345", "Test"),
            (CommitmentLineDraft(offering_id, 3, OfferingUnit.BOX, 3600),),
            DeliveryRecipientSnapshot(name, "Lieferweg 2", "12345", "Test"),
            delivery_window_id=window_id,
            delivery_contact=DeliveryContactSnapshot("Empfang", "+49 30 123"),
        )
        status = CommitmentStatus.REVIEW_READY
        created = await orders.create(
            action_id=action_id,
            actor_user_id=admin_id,
            source=CommitmentSource.ADMIN,
            status=status,
            draft=draft,
            idempotency_key=f"board:{uuid4()}",
            request_hash=draft.fingerprint(
                action_id=action_id, source=CommitmentSource.ADMIN, status=status
            ),
            request_id="board-proof",
            occurred_at=now,
        )
        return created.id

    eins = await order("Board Eins", window.id)
    zwei = await order("Board Zwei", window.id)
    drei = await order("Board Drei", window.id)
    fremd = await order("Board Fremd", other_window.id)

    anna_driver = await _user(pool, "Fahrerin Anna")
    ben_driver = await _user(pool, "Fahrer Ben")
    for driver in (anna_driver, ben_driver):
        await pool.execute(
            "INSERT INTO action_membership(id,action_id,user_id,role)"
            " VALUES ($1,$2,$3,'driver')",
            uuid4(),
            action_id,
            driver,
        )
    acquirer = await _user(pool, "Akquise")

    with_tasks = DeliveryBoardService(
        AsyncpgDeliveryBoardRepository(pool, lambda _c: TaskDeliveryFollowUp()),
        follow_up_tasks=True,
    )
    admin = _principal(admin_id, action_id, ActionRole.CHARITY_ADMIN)
    anna = _principal(anna_driver, action_id, ActionRole.DRIVER)
    ben = _principal(ben_driver, action_id, ActionRole.DRIVER)
    outsider = _principal(acquirer, action_id, ActionRole.ACQUIRER)
    day = window.delivery_on

    async def board(
        actor: IdentityPrincipal, at: datetime | None = None
    ) -> DeliveryBoard:
        return await with_tasks.board(
            actor, action_id, day=day, viewed_at=at or datetime.now(timezone.utc)
        )

    async def drop(
        actor: IdentityPrincipal, commitment_id: UUID
    ) -> DeliveryDrop | None:
        for item in (await board(actor)).windows:
            for value in item.drops:
                if value.commitment_id == commitment_id:
                    return value
        return None

    # Only managers and drivers read; managers see every drop of the day.
    await _expect(board(outsider), PermissionDenied, "delivery_board_forbidden")
    manager_view = await board(admin)
    assert manager_view.manager and manager_view.day == day
    ids = {value.commitment_id for item in manager_view.windows for value in item.drops}
    assert {eins, zwei, drei} <= ids
    other_day = await with_tasks.board(
        admin,
        action_id,
        day=other_window.delivery_on,
        viewed_at=datetime.now(timezone.utc),
    )
    assert fremd in {
        value.commitment_id for item in other_day.windows for value in item.drops
    }
    assert {driver.display_name for driver in manager_view.drivers} == {
        "Fahrerin Anna",
        "Fahrer Ben",
    }

    # Drivers per drop; a window-wide assignment is the bulk form.
    await _expect(
        with_tasks.assign_driver(
            admin,
            action_id,
            commitment_ids=(eins,),
            driver_user_id=acquirer,
            request_id="board-proof",
            occurred_at=now,
        ),
        Conflict,
        "delivery_driver_invalid",
    )
    await _expect(
        with_tasks.assign_driver(
            anna,
            action_id,
            commitment_ids=(eins,),
            driver_user_id=anna_driver,
            request_id="board-proof",
            occurred_at=now,
        ),
        PermissionDenied,
        "delivery_management_required",
    )
    assert (
        await with_tasks.assign_driver(
            admin,
            action_id,
            commitment_ids=(eins, zwei, drei),
            driver_user_id=anna_driver,
            request_id="board-proof",
            occurred_at=now,
        )
        == 3
    )
    assert (
        await with_tasks.assign_driver(
            admin,
            action_id,
            commitment_ids=(drei,),
            driver_user_id=ben_driver,
            request_id="board-proof",
            occurred_at=now,
        )
        == 1
    )

    # Anna sees only her drops: no order status, no other window, no drei.
    anna_view = await board(anna)
    anna_ids = {
        value.commitment_id for item in anna_view.windows for value in item.drops
    }
    assert anna_ids == {eins, zwei}, anna_ids
    assert not anna_view.manager and not anna_view.drivers
    assert all(
        value.order_status is None for item in anna_view.windows for value in item.drops
    )
    assert anna_view.days == (day,)
    # P3: drivers get no who or when of changes and no driver name.
    assert all(
        value.state_changed_at is None
        and value.state_changed_by_name is None
        and value.driver_name is None
        for item in anna_view.windows
        for value in item.drops
    )
    ben_view = await board(ben)
    assert {
        value.commitment_id for item in ben_view.windows for value in item.drops
    } == {drei}
    # One read audit per driver, window and day, however often she looks.
    await board(anna)
    assert (
        await pool.fetchval(
            "SELECT count(*) FROM delivery_read_audit WHERE driver_user_id=$1",
            anna_driver,
        )
        == 1
    )

    # Ticking: only her own drops; revision guards; same target is a no-op.
    first = await drop(anna, eins)
    assert first is not None and first.state is DropState.OPEN
    # A driver cannot probe orders: an unknown id answers like one not hers.
    await _expect(
        with_tasks.set_state(
            anna,
            action_id,
            uuid4(),
            delivered=True,
            expected_revision=0,
            request_id="board-proof",
            occurred_at=now,
        ),
        PermissionDenied,
        "delivery_not_assigned",
    )
    await _expect(
        with_tasks.set_state(
            anna,
            action_id,
            drei,
            delivered=True,
            expected_revision=1,
            request_id="board-proof",
            occurred_at=now,
        ),
        PermissionDenied,
        "delivery_not_assigned",
    )
    await _expect(
        with_tasks.set_state(
            anna,
            action_id,
            eins,
            delivered=True,
            expected_revision=first.revision + 5,
            request_id="board-proof",
            occurred_at=now,
        ),
        Conflict,
        "delivery_state_conflict",
    )
    delivered = await with_tasks.set_state(
        anna,
        action_id,
        eins,
        delivered=True,
        expected_revision=first.revision,
        request_id="board-proof",
        occurred_at=now,
    )
    assert delivered.state is DropState.DELIVERED and delivered.order_status is None
    assert delivered.state_changed_by_name is None and delivered.driver_name is None
    again = await with_tasks.set_state(
        anna,
        action_id,
        eins,
        delivered=True,
        expected_revision=first.revision,
        request_id="board-proof",
        occurred_at=now,
    )
    assert again.revision == delivered.revision
    undone = await with_tasks.set_state(
        anna,
        action_id,
        eins,
        delivered=False,
        expected_revision=delivered.revision,
        request_id="board-proof",
        occurred_at=now,
    )
    assert undone.state is DropState.OPEN
    redone = await with_tasks.set_state(
        anna,
        action_id,
        eins,
        delivered=True,
        expected_revision=undone.revision,
        request_id="board-proof",
        occurred_at=now,
    )
    assert redone.state is DropState.DELIVERED
    assert (
        await pool.fetchval(
            "SELECT count(*) FROM audit_event WHERE entity_id=$1"
            " AND event_type LIKE 'delivery.marked_%'",
            eins,
        )
        == 3
    )

    # Closing: only managers; open drops become missed with one task each,
    # assigned to the closer; closing twice changes nothing.
    await _expect(
        with_tasks.close_window(
            anna, action_id, window.id, request_id="board-proof", occurred_at=now
        ),
        PermissionDenied,
        "delivery_management_required",
    )
    # Earlier proofs may have booked more orders into this window.
    open_before = {
        value.commitment_id
        for item in (await board(admin)).windows
        if item.id == window.id
        for value in item.drops
        if value.state is DropState.OPEN
    }
    assert {zwei, drei} <= open_before and eins not in open_before
    assert await with_tasks.close_window(
        admin, action_id, window.id, request_id="board-proof", occurred_at=now
    ) == len(open_before)
    assert await with_tasks.close_window(
        admin, action_id, window.id, request_id="board-proof", occurred_at=now
    ) == len(open_before)
    tasks = await pool.fetch(
        """
        SELECT follow_up.commitment_id, task.status, task.assignee_user_id,
            task.title, task.description, commitment.public_reference,
            list.title AS list_title, list.action_id
        FROM task_delivery_follow_up AS follow_up
        JOIN task ON task.id = follow_up.task_id
        JOIN task_list AS list ON list.id = task.list_id
        JOIN commitment ON commitment.id = follow_up.commitment_id
        WHERE follow_up.commitment_id = ANY($1::uuid[])
        """,
        [zwei, drei],
    )
    assert {row["commitment_id"] for row in tasks} == {zwei, drei}
    for row in tasks:
        assert row["status"] == "open"
        assert row["assignee_user_id"] == admin_id
        assert row["list_title"] == "Nachliefern"
        assert row["action_id"] == action_id
        reference = order_reference(row["commitment_id"], row["public_reference"])
        assert row["title"] == f"Nachliefern: Bestellung {reference}", row["title"]
        assert order_link(action_id, row["commitment_id"]) in row["description"]
        # No personal data: no buyer, recipient, street, contact or phone.
        text = f"{row['title']}\n{row['description']}"
        for personal in ("Board ", "Lieferweg", "Rechnungsweg", "Empfang", "+49"):
            assert personal not in text, (personal, text)
    # A regular delivery cannot be taken back in a closed window, not even
    # by a manager: that needs a reopen.
    regular = await drop(admin, eins)
    assert regular is not None and regular.state is DropState.DELIVERED
    assert not regular.missed_at_closure
    await _expect(
        with_tasks.set_state(
            admin,
            action_id,
            eins,
            delivered=False,
            expected_revision=regular.revision,
            request_id="board-proof",
            occurred_at=now,
        ),
        Conflict,
        "delivery_window_closed",
    )
    # An order booked into the window after its closure stays open; a
    # manager can tick it (audited, no task), but not take it back.
    spaet = await order("Board Spaet", window.id)
    booked_late = await drop(admin, spaet)
    assert booked_late is not None and booked_late.state is DropState.OPEN
    ticked_late = await with_tasks.set_state(
        admin,
        action_id,
        spaet,
        delivered=True,
        expected_revision=booked_late.revision,
        request_id="board-proof",
        occurred_at=now,
    )
    assert ticked_late.state is DropState.DELIVERED
    assert not await pool.fetchval(
        "SELECT EXISTS (SELECT 1 FROM task_delivery_follow_up WHERE commitment_id=$1)",
        spaet,
    )
    await _expect(
        with_tasks.set_state(
            admin,
            action_id,
            spaet,
            delivered=False,
            expected_revision=ticked_late.revision,
            request_id="board-proof",
            occurred_at=now,
        ),
        Conflict,
        "delivery_window_closed",
    )
    missed = await drop(admin, zwei)
    assert missed is not None and missed.state is DropState.MISSED

    # Drivers cannot change a closed window; managers deliver later, which
    # closes the task; undoing that reopens it.
    current = await drop(anna, zwei)
    assert current is not None
    await _expect(
        with_tasks.set_state(
            anna,
            action_id,
            zwei,
            delivered=True,
            expected_revision=current.revision,
            request_id="board-proof",
            occurred_at=now,
        ),
        Conflict,
        "delivery_window_closed",
    )
    later = await with_tasks.set_state(
        admin,
        action_id,
        zwei,
        delivered=True,
        expected_revision=current.revision,
        request_id="board-proof",
        occurred_at=now,
    )
    assert later.state is DropState.DELIVERED

    async def task_status(commitment_id: UUID) -> str:
        return str(
            await pool.fetchval(
                "SELECT task.status FROM task_delivery_follow_up AS follow_up"
                " JOIN task ON task.id = follow_up.task_id"
                " WHERE follow_up.commitment_id=$1",
                commitment_id,
            )
        )

    assert await task_status(zwei) == "done"
    back = await with_tasks.set_state(
        admin,
        action_id,
        zwei,
        delivered=False,
        expected_revision=later.revision,
        request_id="board-proof",
        occurred_at=now,
    )
    assert back.state is DropState.MISSED
    assert await task_status(zwei) == "open"
    # A cancelled order takes no state changes, not even from a manager.
    await pool.execute("UPDATE commitment SET status='cancelled' WHERE id=$1", spaet)
    cancelled = await drop(admin, spaet)
    assert cancelled is not None
    await _expect(
        with_tasks.set_state(
            admin,
            action_id,
            spaet,
            delivered=False,
            expected_revision=cancelled.revision,
            request_id="board-proof",
            occurred_at=now,
        ),
        Conflict,
        "delivery_order_not_deliverable",
    )

    # Reopening clears missed drops and closes their tasks; closing again
    # reopens the same tasks, no duplicates.
    assert await with_tasks.reopen_window(
        admin, action_id, window.id, request_id="board-proof", occurred_at=now
    ) == len(open_before)
    reopened = await drop(admin, drei)
    assert reopened is not None and reopened.state is DropState.OPEN
    assert await task_status(drei) == "done"
    # Another admin closes again: the task moves to them (Q-T1).
    second_admin_id = await _user(pool, "Zweite Leitung")
    await pool.execute(
        "INSERT INTO action_membership(id,action_id,user_id,role)"
        " VALUES ($1,$2,$3,'charity_admin')",
        uuid4(),
        action_id,
        second_admin_id,
    )
    second_admin = _principal(second_admin_id, action_id, ActionRole.CHARITY_ADMIN)
    await with_tasks.close_window(
        second_admin,
        action_id,
        window.id,
        request_id="board-proof",
        occurred_at=now,
    )
    assert await task_status(drei) == "open"
    moved = await pool.fetchrow(
        "SELECT task.assignee_user_id, list.owner_user_id"
        " FROM task_delivery_follow_up AS follow_up"
        " JOIN task ON task.id = follow_up.task_id"
        " JOIN task_list AS list ON list.id = task.list_id"
        " WHERE follow_up.commitment_id=$1",
        drei,
    )
    assert moved is not None
    assert moved["assignee_user_id"] == second_admin_id
    assert moved["owner_user_id"] == second_admin_id
    assert (
        await pool.fetchval(
            "SELECT count(*) FROM task_delivery_follow_up WHERE commitment_id"
            " = ANY($1::uuid[])",
            [zwei, drei],
        )
        == 2
    )

    # With the tasks module switched off: same board, no tasks.
    without_tasks = DeliveryBoardService(
        AsyncpgDeliveryBoardRepository(pool), follow_up_tasks=False
    )
    assert (
        await without_tasks.close_window(
            admin,
            action_id,
            other_window.id,
            request_id="board-proof",
            occurred_at=now,
        )
        >= 1
    )
    fremd_state = await pool.fetchval(
        "SELECT state FROM commitment_delivery WHERE commitment_id=$1", fremd
    )
    assert fremd_state == "missed"
    assert not await pool.fetchval(
        "SELECT EXISTS (SELECT 1 FROM task_delivery_follow_up WHERE commitment_id=$1)",
        fremd,
    )
    assert not (
        await without_tasks.board(admin, action_id, day=day, viewed_at=now)
    ).follow_up_tasks

    # Read audits older than 90 days are purged; newer ones stay.
    await pool.execute(
        "INSERT INTO delivery_read_audit(driver_user_id,window_id,viewed_on,"
        "action_id,first_viewed_at) VALUES ($1,$2,$3,$4,$5)",
        ben_driver,
        window.id,
        date(2000, 1, 1),
        action_id,
        now - timedelta(days=91),
    )
    assert await purge_read_audits(pool, now=now, limit=100) == 1
    assert await pool.fetchval("SELECT count(*) FROM delivery_read_audit") >= 1
    print(
        "KLF-062 PASS: per-drop drivers, scoped driver reads without amounts,"
        " P3 driver fields, no order probing, read audit and purge, tick/undo"
        " with revisions, closure with Nachliefern tasks without personal"
        " data (mirrored on later delivery, undo and reopen, moved to the"
        " re-closer), closed-window undo only for missed drops, late"
        " bookings tickable, cancelled orders refused, tasks module off"
    )
