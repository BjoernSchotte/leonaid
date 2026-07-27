#!/usr/bin/env python3
"""Validate Golden Dataset v1 and recompute all expected business results."""

from __future__ import annotations

import json
import re
import sys
import unicodedata
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


class Problems:
    def __init__(self) -> None:
        self.items: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.items.append(message)


def load(path: Path, problems: Problems) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        problems.items.append(f"{path}: invalid JSON: {error}")
        return {}
    if not isinstance(value, dict):
        problems.items.append(f"{path}: root must be an object")
        return {}
    return value


def keyed(items: Any, collection: str, problems: Problems) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        problems.items.append(f"{collection}: must be an array")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            problems.items.append(f"{collection}[{index}]: must be an object")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str):
            problems.items.append(f"{collection}[{index}]: missing id")
            continue
        if item_id in result:
            problems.items.append(f"{collection}: duplicate id {item_id}")
        result[item_id] = item
    return result


def normalize_company(value: str) -> str:
    value = value.lower().replace("k.g.", "kg").replace("e.k.", "ek")
    value = (
        value.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    fixture = root / "tests/fixtures/golden/v1"
    problems = Problems()
    manifest = load(fixture / "manifest.json", problems)
    schema = load(fixture / "schema.json", problems)
    data = load(fixture / "dataset.json", problems)
    expected = load(fixture / "expected.json", problems)

    versions = {
        (document.get("datasetVersion"), document.get("schemaVersion"))
        for document in (manifest, data, expected)
    }
    problems.require(len(versions) == 1, "dataset/schema versions differ")
    problems.require(
        schema.get("schemaVersion") == manifest.get("schemaVersion"),
        "schema.json version differs from manifest",
    )
    problems.require(
        manifest.get("synthetic") is True, "manifest must mark data synthetic"
    )
    listed_files = manifest.get("files", [])
    problems.require(
        isinstance(listed_files, list)
        and all((fixture / str(name)).is_file() for name in listed_files),
        "manifest lists a missing file",
    )

    required = schema.get("requiredCollections", [])
    problems.require(isinstance(required, list), "requiredCollections must be an array")
    collections = {
        name: keyed(data.get(name), str(name), problems)
        for name in required
        if isinstance(name, str)
    }
    problems.require(set(collections) == set(required), "required collection missing")

    all_ids: dict[str, str] = {}
    for name, items in collections.items():
        for item_id in items:
            try:
                parsed = uuid.UUID(item_id)
                problems.require(
                    str(parsed) == item_id, f"{name}: non-canonical UUID {item_id}"
                )
            except ValueError:
                problems.items.append(f"{name}: invalid UUID {item_id}")
            if item_id in all_ids:
                problems.items.append(
                    f"global duplicate id {item_id} in {all_ids[item_id]} and {name}"
                )
            all_ids[item_id] = name

    expected_counts = expected.get("counts", {})
    for name, items in collections.items():
        problems.require(
            expected_counts.get(name) == len(items),
            f"{name}: expected count differs ({expected_counts.get(name)} != {len(items)})",
        )

    enums = schema.get("enums", {})
    users = collections["users"]
    actions = collections["actions"]
    memberships = collections["actionMemberships"]
    beneficiaries = collections["beneficiaries"]
    companies = collections["companies"]
    persons = collections["persons"]
    assignments = collections["assignments"]
    offers = collections["offers"]
    commitments = collections["commitments"]
    invoices = collections["invoices"]
    activities = collections["activities"]
    matches = collections["matchScenarios"]
    routes = collections["publicRoutes"]

    for user in users.values():
        problems.require(
            user.get("role") in enums.get("userRole", []), "unknown user role"
        )
        problems.require(
            user.get("status") in enums.get("userStatus", []), "unknown user status"
        )
        email = str(user.get("email", ""))
        problems.require(
            email.endswith("@leonaid.invalid"),
            f"users: non-reserved email domain for {user['id']}",
        )
    for person in persons.values():
        email = str(person.get("email", ""))
        problems.require(
            email.endswith(".leonaid.invalid") or email.endswith("@leonaid.invalid"),
            f"persons: non-reserved email domain for {person['id']}",
        )
        company_id = person.get("companyId")
        problems.require(
            company_id is None or company_id in companies,
            f"persons: unknown company {company_id}",
        )

    role_counts = Counter(user["role"] for user in users.values())
    status_counts = Counter(user["status"] for user in users.values())
    problems.require(
        dict(role_counts) == expected.get("roleCounts"), "role counts differ"
    )
    problems.require(
        dict(status_counts) == expected.get("statusCounts"), "status counts differ"
    )

    for action in actions.values():
        problems.require(
            action.get("status") in enums.get("actionStatus", []),
            f"actions: unknown status for {action['id']}",
        )
        problems.require(
            isinstance(action.get("goalAmountCents"), int)
            and action["goalAmountCents"] > 0,
            f"actions: invalid goal for {action['id']}",
        )
        problems.require(
            isinstance(action.get("actualAmountCents"), int)
            and action["actualAmountCents"] >= 0,
            f"actions: invalid actual value for {action['id']}",
        )
        capabilities = action.get("capabilities")
        problems.require(
            isinstance(capabilities, list)
            and len(capabilities) == len(set(capabilities))
            and set(capabilities).issubset(enums.get("actionCapability", [])),
            f"actions: invalid capabilities for {action['id']}",
        )
    beneficiary_actions = Counter(
        item.get("actionId") for item in beneficiaries.values()
    )
    for beneficiary in beneficiaries.values():
        problems.require(
            beneficiary.get("actionId") in actions,
            f"beneficiaries: unknown action for {beneficiary['id']}",
        )
    for action_id in actions:
        problems.require(
            beneficiary_actions[action_id] >= 1,
            f"actions: {action_id} has no beneficiary",
        )

    membership_by_user: dict[str, set[str]] = defaultdict(set)
    for membership in memberships.values():
        user_id = membership.get("userId")
        membership_action_id = membership.get("actionId")
        problems.require(user_id in users, f"membership: unknown user {user_id}")
        problems.require(
            membership_action_id in actions,
            f"membership: unknown action {membership_action_id}",
        )
        problems.require(
            membership.get("role") in enums.get("membershipRole", []),
            f"membership: unknown role for {membership['id']}",
        )
        if user_id in users and users[user_id]["status"] == "ACTIVE":
            membership_by_user[user_id].add(str(membership_action_id))

    visible: dict[str, list[str]] = {}
    all_action_ids = sorted(actions)
    for user_id, user in users.items():
        if user["status"] == "LOCKED":
            visible[user_id] = []
        elif user["role"] == "SYSTEM_ADMIN":
            visible[user_id] = all_action_ids
        else:
            visible[user_id] = sorted(membership_by_user[user_id])
    problems.require(
        visible == expected.get("visibleActionIdsByUser"),
        "visible action IDs differ",
    )

    for company in companies.values():
        calculated = normalize_company(str(company.get("name", "")))
        problems.require(
            calculated == company.get("normalizedName"),
            f"companies: normalized name differs for {company['id']}",
        )
    contact_counts = Counter(
        person["companyId"] for person in persons.values() if person.get("companyId")
    )
    actual_contacts = {
        company_id: contact_counts[company_id] for company_id in companies
    }
    problems.require(
        actual_contacts == expected.get("companyContactCounts"),
        "company contact counts differ",
    )

    assignment_counts: Counter[str] = Counter()
    assigned_companies: set[str] = set()
    assignment_users_by_company: dict[str, set[str]] = defaultdict(set)
    assignment_users_by_person: dict[str, set[str]] = defaultdict(set)
    assignment_keys: set[tuple[str, str, str]] = set()
    for assignment in assignments.values():
        assignment_action_id = assignment.get("actionId")
        company_id = assignment.get("companyId")
        person_id = assignment.get("personId")
        acquirer_id = assignment.get("acquirerId")
        problems.require(
            assignment_action_id in actions,
            f"assignments: unknown action {assignment_action_id}",
        )
        problems.require(
            (company_id is None) != (person_id is None),
            f"assignments: exactly one target required for {assignment['id']}",
        )
        problems.require(
            acquirer_id in users and users[acquirer_id].get("role") == "ACQUIRER",
            f"assignments: invalid acquirer {acquirer_id}",
        )
        target_id = str(company_id or person_id)
        key = (str(assignment_action_id), target_id, str(acquirer_id))
        problems.require(key not in assignment_keys, f"assignments: duplicate {key}")
        assignment_keys.add(key)
        assignment_counts[str(acquirer_id)] += 1
        if company_id:
            problems.require(
                company_id in companies, f"assignments: unknown company {company_id}"
            )
            assigned_companies.add(company_id)
            assignment_users_by_company[company_id].add(str(acquirer_id))
        if person_id:
            problems.require(
                person_id in persons, f"assignments: unknown person {person_id}"
            )
            assignment_users_by_person[person_id].add(str(acquirer_id))
    problems.require(
        dict(assignment_counts) == expected.get("assignmentCountsByAcquirer"),
        "assignment counts differ",
    )
    problems.require(
        sorted(set(companies) - assigned_companies)
        == expected.get("unassignedCompanyIds"),
        "unassigned company IDs differ",
    )

    for offer in offers.values():
        problems.require(offer.get("actionId") in actions, "offers: unknown action")
        allowed_units = offer.get("allowedQuantityUnits")
        problems.require(
            isinstance(allowed_units, list)
            and bool(allowed_units)
            and offer.get("unit") in allowed_units
            and all(value in enums.get("offeringUnit", []) for value in allowed_units),
            f"offers: invalid quantity units for {offer['id']}",
        )
        problems.require(
            isinstance(offer.get("piecesPerUnit"), int) and offer["piecesPerUnit"] > 0,
            f"offers: invalid pieces for {offer['id']}",
        )
        problems.require(
            isinstance(offer.get("unitPriceCents"), int)
            and offer["unitPriceCents"] > 0,
            f"offers: invalid price for {offer['id']}",
        )
        try:
            available_from = datetime.fromisoformat(str(offer["availableFrom"]))
            available_until = datetime.fromisoformat(str(offer["availableUntil"]))
            valid_period = (
                available_from.utcoffset() is not None
                and available_until.utcoffset() is not None
                and available_from < available_until
            )
        except (KeyError, ValueError):
            valid_period = False
        problems.require(
            valid_period,
            f"offers: invalid availability for {offer['id']}",
        )

    calculations: dict[str, dict[str, int]] = {}
    active_action_id = next(
        action_id
        for action_id, action in actions.items()
        if action["status"] == "ACTIVE"
    )
    totals = {"boxes": 0, "pieces": 0, "amountCents": 0}
    for commitment in commitments.values():
        problems.require(
            commitment.get("source") in enums.get("commitmentSource", []),
            f"commitments: unknown source for {commitment['id']}",
        )
        problems.require(
            commitment.get("status") in enums.get("commitmentStatus", []),
            f"commitments: unknown status for {commitment['id']}",
        )
        company_id = commitment.get("companyId")
        person_id = commitment.get("personId")
        problems.require(
            (company_id is None) != (person_id is None),
            f"commitments: exactly one sponsor target required for {commitment['id']}",
        )
        boxes = pieces = amount = 0
        lines = commitment.get("lines")
        problems.require(
            isinstance(lines, list) and bool(lines), "commitment lines missing"
        )
        for line in lines if isinstance(lines, list) else []:
            line_offer = offers.get(str(line.get("offerId")))
            quantity = line.get("quantity")
            problems.require(
                line_offer is not None, "commitment line has unknown offer"
            )
            problems.require(
                isinstance(quantity, int) and quantity > 0,
                "commitment line quantity must be positive integer",
            )
            if line_offer is None or not isinstance(quantity, int):
                continue
            problems.require(
                line_offer["actionId"] == commitment.get("actionId"),
                "commitment and offer actions differ",
            )
            boxes += quantity
            pieces += quantity * line_offer["piecesPerUnit"]
            amount += quantity * line_offer["unitPriceCents"]
        calculations[commitment["id"]] = {
            "boxes": boxes,
            "pieces": pieces,
            "amountCents": amount,
        }
        if commitment.get("actionId") == active_action_id:
            totals["boxes"] += boxes
            totals["pieces"] += pieces
            totals["amountCents"] += amount
    problems.require(
        calculations == expected.get("commitmentCalculations"),
        "commitment calculations differ",
    )
    goal = actions[active_action_id]["goalAmountCents"]
    actual_totals = {
        **totals,
        "goalAmountCents": goal,
        "goalProgressBasisPoints": totals["amountCents"] * 10000 // goal,
    }
    problems.require(
        actual_totals == expected.get("activeActionTotals"),
        "active action totals differ",
    )

    invoice_statuses: Counter[str] = Counter()
    invoice_numbers: set[str] = set()
    open_invoice_amount = 0
    for invoice in invoices.values():
        commitment_id = invoice.get("commitmentId")
        problems.require(commitment_id in commitments, "invoice: unknown commitment")
        problems.require(
            invoice.get("status") in enums.get("invoiceStatus", []),
            f"invoice: unknown status for {invoice['id']}",
        )
        problems.require(
            invoice.get("number") not in invoice_numbers, "invoice number duplicate"
        )
        invoice_numbers.add(str(invoice.get("number")))
        if commitment_id in calculations:
            problems.require(
                invoice.get("amountCents")
                == calculations[commitment_id]["amountCents"],
                f"invoice: amount differs for {invoice['id']}",
            )
        snapshot = invoice.get("addressSnapshot")
        problems.require(
            isinstance(snapshot, dict)
            and all(
                snapshot.get(key)
                for key in ("recipient", "street", "postalCode", "city", "country")
            ),
            f"invoice: incomplete address snapshot for {invoice['id']}",
        )
        payment = invoice.get("payment")
        cancellation = invoice.get("cancellation")
        if invoice.get("status") == "PAID":
            problems.require(
                isinstance(payment, dict)
                and payment.get("amountCents") == invoice.get("amountCents")
                and payment.get("recordedByUserId") in users
                and bool(payment.get("receivedOn"))
                and bool(payment.get("reference"))
                and bool(payment.get("recordedAt")),
                f"invoice: incomplete full payment for {invoice['id']}",
            )
            problems.require(
                cancellation is None,
                f"invoice: paid Golden invoice unexpectedly cancelled {invoice['id']}",
            )
        elif invoice.get("status") == "CANCELLED":
            problems.require(
                isinstance(cancellation, dict)
                and cancellation.get("originalStatus") in {"OPEN", "PAID"}
                and cancellation.get("requestedByUserId") in users
                and len(str(cancellation.get("reason", "")).strip()) >= 8
                and bool(cancellation.get("requestedAt")),
                f"invoice: incomplete cancellation for {invoice['id']}",
            )
        else:
            problems.require(
                payment is None and cancellation is None,
                f"invoice: open Golden invoice has settlement for {invoice['id']}",
            )
            open_invoice_amount += int(invoice.get("amountCents", 0))
        invoice_statuses[str(invoice.get("status"))] += 1
    problems.require(
        dict(invoice_statuses) == expected.get("invoiceStatusCounts"),
        "invoice status counts differ",
    )
    problems.require(
        open_invoice_amount == expected.get("openInvoiceAmountCents"),
        "open invoice amount differs",
    )

    feed: dict[str, list[str]] = {
        user_id: [] for user_id in expected.get("feedActivityIdsByAcquirer", {})
    }
    for activity in activities.values():
        problems.require(
            activity.get("actionId") in actions, "activity: unknown action"
        )
        actor_id = activity.get("actorId")
        problems.require(
            actor_id is None or actor_id in users, "activity: unknown actor"
        )
        company_id = activity.get("companyId")
        commitment_id = activity.get("commitmentId")
        problems.require(
            company_id is None or company_id in companies, "activity: unknown company"
        )
        problems.require(
            commitment_id is None or commitment_id in commitments,
            "activity: unknown commitment",
        )
        viewers = assignment_users_by_company.get(str(company_id), set())
        for viewer in viewers:
            if viewer in feed:
                feed[viewer].append(activity["id"])
    problems.require(
        feed == expected.get("feedActivityIdsByAcquirer"), "feed visibility differs"
    )

    for scenario in matches.values():
        if scenario.get("kind") == "COMPANY_NORMALIZED_NAME":
            normalized = normalize_company(
                str(scenario.get("input", {}).get("name", ""))
            )
            problems.require(
                normalized == scenario.get("normalizedKey"),
                "company match normalized key differs",
            )
            found = sorted(
                company_id
                for company_id, company in companies.items()
                if company["normalizedName"] == normalized
            )
            problems.require(
                found == scenario.get("expectedCompanyIds"), "company match differs"
            )
            warning = sorted(
                {
                    user_id
                    for company_id in found
                    for user_id in assignment_users_by_company[company_id]
                }
            )
            problems.require(
                warning == scenario.get("warningAcquirerIds"),
                "company match warning acquirers differ",
            )
        elif scenario.get("kind") == "PERSON_NAME_WITHOUT_COMPANY":
            input_value = scenario.get("input", {})
            found = sorted(
                person_id
                for person_id, person in persons.items()
                if person["givenName"] == input_value.get("givenName")
                and person["familyName"] == input_value.get("familyName")
            )
            problems.require(
                found == scenario.get("expectedPersonIds"), "person match differs"
            )
            problems.require(
                scenario.get("requiresDisambiguation") is (len(found) > 1),
                "person disambiguation expectation differs",
            )

    resolution: dict[str, str] = {}
    aliases: set[str] = set()
    for route in routes.values():
        path = route.get("path")
        route_action_id = route.get("actionId")
        problems.require(
            isinstance(path, str) and path.startswith("/"), "route path invalid"
        )
        problems.require(route_action_id in actions, "route action invalid")
        problems.require(path not in resolution, f"duplicate public route {path}")
        resolution[str(path)] = str(route_action_id)
        if route.get("kind") == "ACTIVE_ALIAS":
            aliases.add(str(path))
            if route_action_id in actions:
                problems.require(
                    actions[str(route_action_id)]["status"] == "ACTIVE",
                    "active alias must resolve to active action",
                )
    problems.require(aliases == {"/krapfentaxi"}, "active alias set differs")
    problems.require(
        resolution == expected.get("publicResolution"), "public resolution differs"
    )

    if problems.items:
        for item in problems.items:
            print(f"golden-check: ERROR: {item}", file=sys.stderr)
        print(
            f"golden-check: FAILED with {len(problems.items)} problem(s)",
            file=sys.stderr,
        )
        return 1
    print(
        "golden-check: OK: "
        f"{len(all_ids)} stable IDs, {actual_totals['boxes']} boxes, "
        f"{actual_totals['pieces']} pieces, {actual_totals['amountCents']} cents"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
