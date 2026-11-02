#!/usr/bin/env python3
"""Provision and verify LeonAid's declared Twenty metadata contract."""

from __future__ import annotations

import argparse
import json
import os
import socket
import stat
import sys
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn, TypeVar
from urllib.parse import urlsplit

import httpx

from tools.seed.golden import SeedError, TwentyClient

JsonObject = dict[str, Any]
JsonList = list[JsonObject]


class TwentySchemaError(RuntimeError):
    """Twenty does not match the declared LeonAid CRM contract."""


class SchemaDrift(TwentySchemaError):
    """One or more managed metadata values differ from the manifest."""

    def __init__(self, differences: list[JsonObject]) -> None:
        self.differences = differences
        lines = ["Twenty schema differs from infra/twenty/schema.json:"]
        for difference in differences:
            lines.append(
                "  - "
                f"{difference['path']}: "
                f"expected={json.dumps(difference['expected'], ensure_ascii=False, sort_keys=True)} "
                f"actual={json.dumps(difference['actual'], ensure_ascii=False, sort_keys=True)}"
            )
        super().__init__("\n".join(lines))


TRANSIENT_FLAT_ENTITY_ERROR = "Could not find flat entity"

# Twenty 2.54 caches the workspace metadata ("flat maps") in Redis. A metadata
# mutation commits, flushes the affected keys and recomputes them. A reader in
# another process (twenty-worker jobs run after every metadata event) that
# started its own recompute from the database before that commit writes its
# stale result after the fresh one, with a new hash. Every process then serves
# the stale map until the next invalidation or the 7-day cache TTL: a created
# field stays invisible, and the worker fails with "Index field not found for
# field id ..." because the index map is fresh while the field map is not.
# Waiting longer cannot repair that. After STALE_CACHE_SECONDS without the
# created entity, the provisioner deletes the workspace cache namespace once
# more, exactly like Twenty's own `cache:flush --namespace engine:workspace`,
# and all processes recompute from the committed database state.
STALE_CACHE_SECONDS = 15.0
VISIBILITY_TIMEOUT_SECONDS = 90.0
WORKSPACE_CACHE_PATTERN = "engine:workspace:*"
DEFAULT_TWENTY_REDIS_URL = "redis://twenty-redis:6379"

T = TypeVar("T")


class RedisError(RuntimeError):
    """The Twenty cache Redis rejected a command or was unreachable."""


def redis_command(connection: socket.socket, reader: Any, *arguments: str) -> Any:
    payload = f"*{len(arguments)}\r\n".encode()
    for argument in arguments:
        encoded = argument.encode()
        payload += b"$" + str(len(encoded)).encode() + b"\r\n" + encoded + b"\r\n"
    connection.sendall(payload)
    return redis_reply(reader)


def redis_reply(reader: Any) -> Any:
    line = reader.readline()
    if not line.endswith(b"\r\n"):
        raise RedisError("Twenty cache Redis closed the connection")
    kind, value = line[:1], line[1:-2]
    if kind == b"+":
        return value.decode()
    if kind == b"-":
        raise RedisError(f"Twenty cache Redis error: {value.decode()[:200]}")
    if kind == b":":
        return int(value)
    if kind == b"$":
        length = int(value)
        if length < 0:
            return None
        data = reader.read(length + 2)
        return data[:-2].decode()
    if kind == b"*":
        count = int(value)
        return None if count < 0 else [redis_reply(reader) for _ in range(count)]
    raise RedisError("Twenty cache Redis sent an unknown reply")


def flush_workspace_cache(url: str, pattern: str = WORKSPACE_CACHE_PATTERN) -> int:
    """Delete Twenty's workspace cache keys; returns the number deleted."""
    parts = urlsplit(url)
    if parts.scheme != "redis" or not parts.hostname:
        raise RedisError("TWENTY_REDIS_URL must be redis://host[:port][/db]")
    deleted = 0
    with socket.create_connection(
        (parts.hostname, parts.port or 6379), timeout=10
    ) as connection:
        reader = connection.makefile("rb")
        if parts.password:
            user = [parts.username] if parts.username else []
            redis_command(connection, reader, "AUTH", *user, parts.password)
        database = parts.path.lstrip("/")
        if database:
            redis_command(connection, reader, "SELECT", database)
        cursor = "0"
        while True:
            cursor, keys = redis_command(
                connection, reader, "SCAN", cursor, "MATCH", pattern, "COUNT", "500"
            )
            if keys:
                deleted += int(redis_command(connection, reader, "DEL", *keys))
            if cursor == "0":
                return deleted


def json_object(value: Any, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise TwentySchemaError(f"{label} must be a JSON object")
    return value


def json_list(value: Any, label: str) -> JsonList:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise TwentySchemaError(f"{label} must be a list of JSON objects")
    return value


def load_manifest(path: Path) -> JsonObject:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TwentySchemaError(f"Twenty manifest is not readable: {error}") from error
    value = json_object(manifest, str(path))
    if value.get("schemaVersion") != 1:
        raise TwentySchemaError("unexpected Twenty schema version")
    objects = json_list(value.get("objects"), "objects")
    object_names = [item.get("nameSingular") for item in objects]
    if any(not isinstance(name, str) or not name for name in object_names):
        raise TwentySchemaError("every custom object needs nameSingular")
    if len(object_names) != len(set(object_names)):
        raise TwentySchemaError("duplicate custom object names in the manifest")
    standard_names: list[str] = []
    for item in json_list(value.get("standardObjects", []), "standardObjects"):
        name = item.get("nameSingular")
        if not isinstance(name, str) or not name:
            raise TwentySchemaError("every standard object needs nameSingular")
        if name in object_names:
            raise TwentySchemaError(
                f"standard object is also declared as a custom object: {name}"
            )
        for field in json_list(item.get("fields"), f"standardObjects.{name}.fields"):
            # Standard objects only receive additional scalar fields. Relations
            # and options would need the two-phase handling of custom objects.
            if field.get("type") == "RELATION" or "options" in field:
                raise TwentySchemaError(
                    f"standard object {name} supports only additional scalar fields"
                )
        standard_names.append(name)
    if len(standard_names) != len(set(standard_names)):
        raise TwentySchemaError("duplicate standard object names in the manifest")
    return value


def standard_objects(manifest: JsonObject) -> JsonList:
    """Standard Twenty objects that receive LeonAid-managed scalar fields."""

    return json_list(manifest.get("standardObjects", []), "standardObjects")


def one_by(
    items: JsonList,
    key: str,
    value: str,
    label: str,
) -> JsonObject | None:
    matches = [item for item in items if item.get(key) == value]
    if len(matches) > 1:
        raise TwentySchemaError(f"{label} occurs more than once: {value}")
    return matches[0] if matches else None


def normalize_options(value: Any) -> list[JsonObject]:
    if value is None:
        return []
    options = json_list(value, "field.options")
    selected = [
        {
            "id": item.get("id"),
            "label": item.get("label"),
            "value": item.get("value"),
            "color": item.get("color"),
            "position": item.get("position"),
        }
        for item in options
    ]
    return sorted(selected, key=lambda item: (item["position"], str(item["value"])))


def normalized_instant(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TwentySchemaError(f"timestamp is not a string: {value!r}")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def field_snapshot(desired_field: JsonObject, actual_field: JsonObject) -> JsonObject:
    item: JsonObject = {
        "name": actual_field["name"],
        "label": actual_field["label"],
        "description": actual_field.get("description"),
        "icon": actual_field.get("icon"),
        "type": actual_field["type"],
        "isNullable": actual_field["isNullable"],
        "isUnique": actual_field["isUnique"],
    }
    if "options" in desired_field:
        item["options"] = normalize_options(actual_field.get("options"))
    relation = actual_field.get("relation")
    if isinstance(relation, dict):
        target = json_object(
            relation["targetObjectMetadata"],
            "relation.targetObjectMetadata",
        )
        target_field = json_object(
            relation["targetFieldMetadata"],
            "relation.targetFieldMetadata",
        )
        item["relation"] = {
            "type": relation["type"],
            "targetObject": target["nameSingular"],
            "targetFieldLabel": target_field["label"],
            "targetFieldIcon": target_field["icon"],
        }
    return item


def difference(
    differences: list[JsonObject],
    path: str,
    expected: Any,
    actual: Any,
) -> None:
    if expected != actual:
        differences.append({"path": path, "expected": expected, "actual": actual})


class Provisioner:
    """Narrow adapter for the supported Twenty v2.54.0 Metadata API.

    Twenty 2.54 dropped View.isCustom. A LeonAid view is identified by the
    fixed id from infra/twenty/schema.json, which the id comparison checks.
    """

    def __init__(self, manifest: JsonObject) -> None:
        self.manifest = manifest
        self.client = TwentyClient()
        self.client.authenticate()

    def close(self) -> None:
        self.client.close()

    def metadata(self, query: str, variables: JsonObject | None = None) -> JsonObject:
        if self.client.access_token is None:
            raise TwentySchemaError("Twenty admin session missing")
        return self.client.graphql(
            query,
            variables or {},
            bearer=self.client.access_token,
        )

    def objects(self) -> JsonList:
        response = self.client.request("GET", "/rest/metadata/objects?limit=100")
        if response.is_error:
            raise TwentySchemaError(
                f"Twenty REST Metadata API HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
        payload = json_object(response.json(), "REST Metadata response")
        return json_list(payload.get("data"), "REST Metadata data")

    def object_details(self, object_id: str) -> JsonObject:
        data = self.metadata(
            """
            query ObjectDetails($id: UUID!) {
              object(id: $id) {
                id
                nameSingular
                fieldsList {
                  id
                  name
                  label
                  description
                  icon
                  type
                  isActive
                  isNullable
                  isUnique
                  options
                  relation {
                    type
                    sourceObjectMetadata { nameSingular }
                    targetObjectMetadata { nameSingular }
                    sourceFieldMetadata { name }
                    targetFieldMetadata { name label icon }
                  }
                }
              }
            }
            """,
            {"id": object_id},
        )
        return json_object(data.get("object"), f"object({object_id})")

    def views(self, object_id: str) -> JsonList:
        data = self.metadata(
            """
            query Views($objectId: String!) {
              getViews(objectMetadataId: $objectId) {
                id
                name
                objectMetadataId
                type
                icon
                position
                isCompact
                openRecordIn
                isActive
                viewFields {
                  id
                  fieldMetadataId
                  isVisible
                  size
                  position
                }
              }
            }
            """,
            {"objectId": object_id},
        )
        return json_list(data.get("getViews"), "getViews")

    def roles(self) -> JsonList:
        data = self.metadata(
            """
            query Roles {
              getRoles {
                id
                label
                description
                icon
                isEditable
                canBeAssignedToUsers
                canBeAssignedToAgents
                canBeAssignedToApiKeys
                canUpdateAllSettings
                canAccessAllTools
                canReadAllObjectRecords
                canUpdateAllObjectRecords
                canSoftDeleteAllObjectRecords
                canDestroyAllObjectRecords
                permissionFlags { flag }
                objectPermissions {
                  objectMetadataId
                  canReadObjectRecords
                  canUpdateObjectRecords
                  canSoftDeleteObjectRecords
                  canDestroyObjectRecords
                }
                fieldPermissions {
                  objectMetadataId
                  fieldMetadataId
                  canReadFieldValue
                  canUpdateFieldValue
                }
              }
            }
            """
        )
        return json_list(data.get("getRoles"), "getRoles")

    def api_keys(self) -> JsonList:
        data = self.metadata(
            """
            query ApiKeys {
              apiKeys {
                id
                name
                expiresAt
                revokedAt
                role { id label }
              }
            }
            """
        )
        return json_list(data.get("apiKeys"), "apiKeys")

    def object_map(self) -> dict[str, JsonObject]:
        result: dict[str, JsonObject] = {}
        for item in self.objects():
            name = item.get("nameSingular")
            if not isinstance(name, str):
                continue
            if name in result:
                raise TwentySchemaError(f"Twenty object is duplicated: {name}")
            result[name] = item
        return result

    def create_object(self, desired: JsonObject) -> None:
        create = {
            key: desired[key]
            for key in (
                "nameSingular",
                "namePlural",
                "labelSingular",
                "labelPlural",
                "description",
                "icon",
            )
        }
        create["skipNameField"] = False
        create["isRemote"] = False
        self.metadata(
            """
            mutation CreateObject($input: CreateOneObjectInput!) {
              createOneObject(input: $input) { id nameSingular }
            }
            """,
            {"input": {"object": create}},
        )

    def update_object_searchability(self, object_id: str, desired: bool) -> None:
        self.metadata(
            """
            mutation UpdateObject($input: UpdateOneObjectInput!) {
              updateOneObject(input: $input) { id isSearchable }
            }
            """,
            {"input": {"id": object_id, "update": {"isSearchable": desired}}},
        )

    def create_field(
        self,
        desired: JsonObject,
        object_id: str,
        objects: dict[str, JsonObject],
    ) -> None:
        field: JsonObject = {
            key: desired[key]
            for key in (
                "name",
                "label",
                "description",
                "icon",
                "type",
                "isNullable",
                "isUnique",
            )
        }
        field.update(
            {
                "objectMetadataId": object_id,
                "isActive": True,
                "isSystem": False,
                "isUIEditable": True,
                "isUIReadOnly": False,
            }
        )
        if "options" in desired:
            field["options"] = desired["options"]
        relation = desired.get("relation")
        if isinstance(relation, dict):
            target_name = relation.get("targetObject")
            target = objects.get(str(target_name))
            if target is None:
                raise TwentySchemaError(
                    f"relation target missing before provisioning: {target_name}"
                )
            field["relationCreationPayload"] = {
                "type": relation["type"],
                "targetObjectMetadataId": target["id"],
                "targetFieldLabel": relation["targetFieldLabel"],
                "targetFieldIcon": relation["targetFieldIcon"],
            }
        self.metadata(
            """
            mutation CreateField($input: CreateOneFieldMetadataInput!) {
              createOneField(input: $input) { id name type }
            }
            """,
            {"input": {"field": field}},
        )

    def create_view(self, desired: JsonObject, object_id: str) -> None:
        view_input = {
            "id": desired["id"],
            "name": desired["name"],
            "objectMetadataId": object_id,
            "type": desired["type"],
            "icon": desired["icon"],
            "position": desired["position"],
            "isCompact": desired["isCompact"],
            "openRecordIn": desired["openRecordIn"],
        }
        self.metadata(
            """
            mutation CreateView($input: CreateViewInput!) {
              createView(input: $input) { id name }
            }
            """,
            {"input": view_input},
        )

    def create_view_field(
        self,
        desired: JsonObject,
        view_id: str,
        field_id: str,
    ) -> None:
        self.metadata(
            """
            mutation CreateViewField($input: CreateViewFieldInput!) {
              createViewField(input: $input) { id fieldMetadataId }
            }
            """,
            {
                "input": {
                    "id": desired["id"],
                    "viewId": view_id,
                    "fieldMetadataId": field_id,
                    "isVisible": True,
                    "size": desired["size"],
                    "position": desired["position"],
                }
            },
        )

    def update_view_field(
        self,
        view_field_id: str,
        *,
        visible: bool,
        size: float,
        position: float,
    ) -> None:
        self.metadata(
            """
            mutation UpdateViewField($input: UpdateViewFieldInput!) {
              updateViewField(input: $input) { id }
            }
            """,
            {
                "input": {
                    "id": view_field_id,
                    "update": {
                        "isVisible": visible,
                        "size": size,
                        "position": position,
                    },
                }
            },
        )

    def create_role(self, desired: JsonObject) -> None:
        role_input = {
            key: desired[key]
            for key in (
                "id",
                "label",
                "description",
                "icon",
                "canBeAssignedToUsers",
                "canBeAssignedToAgents",
                "canBeAssignedToApiKeys",
            )
        }
        role_input.update(
            {
                "canUpdateAllSettings": False,
                "canAccessAllTools": False,
                "canReadAllObjectRecords": False,
                "canUpdateAllObjectRecords": False,
                "canSoftDeleteAllObjectRecords": False,
                "canDestroyAllObjectRecords": False,
            }
        )
        self.metadata(
            """
            mutation CreateRole($input: CreateRoleInput!) {
              createOneRole(createRoleInput: $input) { id label }
            }
            """,
            {"input": role_input},
        )

    def upsert_role_permissions(
        self,
        desired: JsonObject,
        objects: dict[str, JsonObject],
    ) -> None:
        role_id = str(desired["id"])
        object_permissions: JsonList = []
        field_permissions: JsonList = []
        for permission in json_list(desired.get("objects"), "role.objects"):
            object_name = str(permission["object"])
            actual_object = objects.get(object_name)
            if actual_object is None:
                raise TwentySchemaError(f"role object does not exist: {object_name}")
            object_id = str(actual_object["id"])
            object_permissions.append(
                {
                    "objectMetadataId": object_id,
                    "canReadObjectRecords": permission["canRead"],
                    "canUpdateObjectRecords": permission["canUpdate"],
                    "canSoftDeleteObjectRecords": permission["canSoftDelete"],
                    "canDestroyObjectRecords": permission["canDestroy"],
                }
            )
            if permission.get("allFields") is True:
                continue
            read_fields = set(permission.get("readFields", []))
            update_fields = set(permission.get("updateFields", []))
            actual_fields = json_list(actual_object.get("fields"), object_name)
            existing_names = {
                str(field["name"])
                for field in actual_fields
                if isinstance(field.get("name"), str)
            }
            missing = sorted((read_fields | update_fields) - existing_names)
            if missing:
                raise TwentySchemaError(
                    f"role field missing in {object_name}: {', '.join(missing)}"
                )
            for field in actual_fields:
                field_name = str(field.get("name"))
                can_read = field_name in read_fields
                can_update = field_name in update_fields
                restriction: JsonObject = {
                    "objectMetadataId": object_id,
                    "fieldMetadataId": field["id"],
                }
                if not can_read:
                    restriction["canReadFieldValue"] = False
                if not can_update:
                    restriction["canUpdateFieldValue"] = False
                field_permissions.append(restriction)
        self.metadata(
            """
            mutation ObjectPermissions($input: UpsertObjectPermissionsInput!) {
              upsertObjectPermissions(upsertObjectPermissionsInput: $input) {
                objectMetadataId
              }
            }
            """,
            {
                "input": {
                    "roleId": role_id,
                    "objectPermissions": object_permissions,
                }
            },
        )
        if field_permissions:
            self.metadata(
                """
                mutation FieldPermissions($input: UpsertFieldPermissionsInput!) {
                  upsertFieldPermissions(upsertFieldPermissionsInput: $input) {
                    fieldMetadataId
                  }
                }
                """,
                {
                    "input": {
                        "roleId": role_id,
                        "fieldPermissions": field_permissions,
                    }
                },
            )
        self.metadata(
            """
            mutation PermissionFlags($input: UpsertPermissionFlagsInput!) {
              upsertPermissionFlags(upsertPermissionFlagsInput: $input) {
                flag
              }
            }
            """,
            {
                "input": {
                    "roleId": role_id,
                    "permissionFlagKeys": desired["permissionFlags"],
                }
            },
        )

    def create_api_key(self, desired: JsonObject, role_id: str) -> JsonObject:
        data = self.metadata(
            """
            mutation CreateApiKey($input: CreateApiKeyInput!) {
              createApiKey(input: $input) {
                id
                name
                expiresAt
                role { id label }
              }
            }
            """,
            {
                "input": {
                    "name": desired["name"],
                    "expiresAt": desired["expiresAt"],
                    "roleId": role_id,
                }
            },
        )
        return json_object(data.get("createApiKey"), "createApiKey")

    def generate_api_token(self, api_key_id: str, expires_at: str) -> str:
        data = self.metadata(
            """
            mutation GenerateApiKeyToken($apiKeyId: UUID!, $expiresAt: String!) {
              generateApiKeyToken(apiKeyId: $apiKeyId, expiresAt: $expiresAt) {
                token
              }
            }
            """,
            {"apiKeyId": api_key_id, "expiresAt": expires_at},
        )
        result = json_object(data.get("generateApiKeyToken"), "generateApiKeyToken")
        token = result.get("token")
        if not isinstance(token, str) or len(token) < 32:
            raise TwentySchemaError("Twenty did not create a valid API key token")
        return token

    def ensure_objects(self) -> None:
        existing = self.object_map()
        for desired in json_list(self.manifest["objects"], "objects"):
            name = str(desired["nameSingular"])
            actual = existing.get(name)
            if actual is None:
                self.create_object(desired)
                existing = self.wait_for_object(name)
                actual = existing[name]
                if bool(actual.get("isSearchable")) != bool(desired["isSearchable"]):
                    self.update_object_searchability(
                        str(actual["id"]),
                        bool(desired["isSearchable"]),
                    )
                    existing = self.wait_for_object(name)
                    actual = existing[name]
            drifts = self.object_differences(desired, actual)
            if drifts:
                raise SchemaDrift(drifts)

    def wait_until_visible(
        self,
        label: str,
        probe: Callable[[], T | None],
        timeout: float = VISIBILITY_TIMEOUT_SECONDS,
    ) -> T:
        """Poll until a created entity is visible; repair a stale Twenty cache."""
        start = time.monotonic()
        next_flush = start + STALE_CACHE_SECONDS
        flushes = 0
        while True:
            value = probe()
            if value is not None:
                if flushes:
                    print(
                        f"twenty-schema: {label} visible after {flushes} "
                        "cache recompute(s)",
                        file=sys.stderr,
                    )
                return value
            now = time.monotonic()
            if now >= start + timeout:
                raise TwentySchemaError(
                    f"Twenty Metadata API did not publish {label} "
                    f"after {timeout:.0f}s and {flushes} cache recompute(s)"
                )
            if now >= next_flush:
                flushes += 1
                next_flush = now + STALE_CACHE_SECONDS
                self.repair_stale_cache(label, now - start)
            time.sleep(0.5)

    def repair_stale_cache(self, label: str, waited: float) -> None:
        url = os.environ.get("TWENTY_REDIS_URL", DEFAULT_TWENTY_REDIS_URL)
        try:
            deleted = flush_workspace_cache(url)
        except (OSError, RedisError, ValueError) as error:
            # Keep waiting: without the repair the deadline reports the failure.
            print(
                f"twenty-schema: WARNING: {label} invisible after {waited:.0f}s; "
                f"workspace cache unreachable ({type(error).__name__}: {error})",
                file=sys.stderr,
            )
            return
        print(
            f"twenty-schema: {label} invisible after {waited:.0f}s; stale "
            f"Twenty workspace cache dropped ({deleted} keys)",
            file=sys.stderr,
        )

    def wait_for_object(self, name: str) -> dict[str, JsonObject]:
        def probe() -> dict[str, JsonObject] | None:
            objects = self.object_map()
            return objects if name in objects else None

        return self.wait_until_visible(f"Object {name}", probe)

    def wait_for_field(self, object_id: str, field_name: str) -> dict[str, JsonObject]:
        def probe() -> dict[str, JsonObject] | None:
            # Validate the same GraphQL view we consume, not an independently
            # refreshed REST metadata cache that can become visible first.
            details = self.object_details(object_id)
            fields = {
                str(field["name"]): field
                for field in json_list(details.get("fieldsList"), "fieldsList")
            }
            return fields if field_name in fields else None

        return self.wait_until_visible(f"Field {object_id}.{field_name}", probe)

    def object_differences(
        self,
        desired: JsonObject,
        actual: JsonObject,
    ) -> list[JsonObject]:
        differences: list[JsonObject] = []
        prefix = f"objects.{desired['nameSingular']}"
        for key in (
            "nameSingular",
            "namePlural",
            "labelSingular",
            "labelPlural",
            "description",
            "icon",
            "isSearchable",
        ):
            difference(differences, f"{prefix}.{key}", desired[key], actual.get(key))
        difference(differences, f"{prefix}.isActive", True, actual.get("isActive"))
        return differences

    def field_differences(
        self,
        object_name: str,
        desired: JsonObject,
        actual: JsonObject,
    ) -> list[JsonObject]:
        differences: list[JsonObject] = []
        prefix = f"objects.{object_name}.fields.{desired['name']}"
        for key in (
            "name",
            "label",
            "description",
            "icon",
            "type",
            "isNullable",
            "isUnique",
        ):
            difference(differences, f"{prefix}.{key}", desired[key], actual.get(key))
        difference(differences, f"{prefix}.isActive", True, actual.get("isActive"))
        if "options" in desired:
            difference(
                differences,
                f"{prefix}.options",
                normalize_options(desired["options"]),
                normalize_options(actual.get("options")),
            )
        relation = desired.get("relation")
        if isinstance(relation, dict):
            actual_relation = actual.get("relation")
            if not isinstance(actual_relation, dict):
                difference(differences, f"{prefix}.relation", relation, actual_relation)
            else:
                difference(
                    differences,
                    f"{prefix}.relation.type",
                    relation["type"],
                    actual_relation.get("type"),
                )
                target = actual_relation.get("targetObjectMetadata")
                difference(
                    differences,
                    f"{prefix}.relation.targetObject",
                    relation["targetObject"],
                    target.get("nameSingular") if isinstance(target, dict) else None,
                )
                target_field = actual_relation.get("targetFieldMetadata")
                difference(
                    differences,
                    f"{prefix}.relation.targetFieldLabel",
                    relation["targetFieldLabel"],
                    target_field.get("label")
                    if isinstance(target_field, dict)
                    else None,
                )
                difference(
                    differences,
                    f"{prefix}.relation.targetFieldIcon",
                    relation["targetFieldIcon"],
                    target_field.get("icon")
                    if isinstance(target_field, dict)
                    else None,
                )
        return differences

    def ensure_fields(self) -> None:
        objects = self.object_map()
        desired_objects = json_list(self.manifest["objects"], "objects")
        for relation_phase in (False, True):
            for desired_object in desired_objects:
                object_name = str(desired_object["nameSingular"])
                actual_object = objects[object_name]
                object_id = str(actual_object["id"])
                details = self.object_details(object_id)
                fields = {
                    str(field["name"]): field
                    for field in json_list(details.get("fieldsList"), "fieldsList")
                }
                for desired in json_list(desired_object["fields"], "fields"):
                    is_relation = desired.get("type") == "RELATION"
                    if is_relation != relation_phase:
                        continue
                    field_name = str(desired["name"])
                    actual = fields.get(field_name)
                    if actual is None:
                        self.create_field(desired, object_id, objects)
                        fields = self.wait_for_field(object_id, field_name)
                        objects = self.object_map()
                        actual = fields.get(field_name)
                    if actual is None:
                        raise TwentySchemaError(
                            f"field missing after provisioning: {object_name}.{field_name}"
                        )
                    drifts = self.field_differences(object_name, desired, actual)
                    if drifts:
                        raise SchemaDrift(drifts)
            objects = self.object_map()

    def ensure_standard_fields(self) -> None:
        objects = self.object_map()
        for desired_object in standard_objects(self.manifest):
            object_name = str(desired_object["nameSingular"])
            actual_object = objects.get(object_name)
            if actual_object is None:
                raise TwentySchemaError(f"standard object missing: {object_name}")
            object_id = str(actual_object["id"])
            details = self.object_details(object_id)
            fields = {
                str(field["name"]): field
                for field in json_list(details.get("fieldsList"), "fieldsList")
            }
            for desired in json_list(desired_object["fields"], "fields"):
                field_name = str(desired["name"])
                actual = fields.get(field_name)
                if actual is None:
                    self.create_field(desired, object_id, objects)
                    fields = self.wait_for_field(object_id, field_name)
                    actual = fields.get(field_name)
                if actual is None:
                    raise TwentySchemaError(
                        f"field missing after provisioning: {object_name}.{field_name}"
                    )
                drifts = self.field_differences(object_name, desired, actual)
                if drifts:
                    raise SchemaDrift(drifts)

    def ensure_views(self) -> None:
        objects = self.object_map()
        for desired in json_list(self.manifest["views"], "views"):
            object_name = str(desired["object"])
            actual_object = objects.get(object_name)
            if actual_object is None:
                raise TwentySchemaError(f"view object missing: {object_name}")
            object_id = str(actual_object["id"])
            views = self.views(object_id)
            actual = one_by(views, "id", str(desired["id"]), "View-ID")
            created = False
            if actual is None:
                same_name = one_by(
                    views,
                    "name",
                    str(desired["name"]),
                    f"View-Name {object_name}",
                )
                if same_name is not None:
                    raise SchemaDrift(
                        [
                            {
                                "path": f"views.{desired['name']}.id",
                                "expected": desired["id"],
                                "actual": same_name.get("id"),
                            }
                        ]
                    )
                self.create_view(desired, object_id)
                created = True
                actual = self.wait_for_view(object_id, str(desired["id"]))
            self.reconcile_view_fields(
                desired,
                actual,
                actual_object,
                created=created,
            )
            refreshed = self.wait_for_view(object_id, str(desired["id"]))
            drifts = self.view_differences(desired, refreshed, actual_object)
            if drifts:
                raise SchemaDrift(drifts)

    def wait_for_view(self, object_id: str, view_id: str) -> JsonObject:
        return self.wait_until_visible(
            f"View {view_id}",
            lambda: one_by(self.views(object_id), "id", view_id, "View-ID"),
            timeout=60,
        )

    def reconcile_view_fields(
        self,
        desired: JsonObject,
        actual: JsonObject,
        actual_object: JsonObject,
        *,
        created: bool,
    ) -> None:
        fields = {
            str(field["name"]): field
            for field in json_list(actual_object.get("fields"), "object.fields")
        }
        view_fields = json_list(actual.get("viewFields"), "view.viewFields")
        by_metadata_id = {
            str(view_field["fieldMetadataId"]): view_field for view_field in view_fields
        }
        desired_metadata_ids: set[str] = set()
        for expected in json_list(desired["fields"], "view.fields"):
            field_name = str(expected["field"])
            field = fields.get(field_name)
            if field is None:
                raise TwentySchemaError(
                    f"view field does not exist: {desired['name']}.{field_name}"
                )
            field_id = str(field["id"])
            desired_metadata_ids.add(field_id)
            view_field = by_metadata_id.get(field_id)
            if view_field is None:
                self.create_view_field(expected, str(desired["id"]), field_id)
                continue
            expected_size = float(expected["size"])
            expected_position = float(expected["position"])
            differs = (
                view_field.get("isVisible") is not True
                or float(view_field.get("size", -1)) != expected_size
                or float(view_field.get("position", -1)) != expected_position
            )
            if differs and created:
                self.update_view_field(
                    str(view_field["id"]),
                    visible=True,
                    size=expected_size,
                    position=expected_position,
                )
        if created:
            for view_field in view_fields:
                if (
                    str(view_field["fieldMetadataId"]) not in desired_metadata_ids
                    and view_field.get("isVisible") is True
                ):
                    self.update_view_field(
                        str(view_field["id"]),
                        visible=False,
                        size=float(view_field.get("size", 0)),
                        position=float(view_field.get("position", 0)),
                    )

    def view_differences(
        self,
        desired: JsonObject,
        actual: JsonObject,
        actual_object: JsonObject,
    ) -> list[JsonObject]:
        differences: list[JsonObject] = []
        prefix = f"views.{desired['name']}"
        for key in (
            "id",
            "name",
            "type",
            "icon",
            "position",
            "isCompact",
            "openRecordIn",
        ):
            difference(differences, f"{prefix}.{key}", desired[key], actual.get(key))
        difference(differences, f"{prefix}.isActive", True, actual.get("isActive"))

        fields = {
            str(field["id"]): str(field["name"])
            for field in json_list(actual_object.get("fields"), "object.fields")
        }
        expected_by_name = {
            str(item["field"]): item
            for item in json_list(desired["fields"], "view.fields")
        }
        actual_visible: dict[str, JsonObject] = {}
        for view_field in json_list(actual.get("viewFields"), "view.viewFields"):
            if view_field.get("isVisible") is not True:
                continue
            name = fields.get(str(view_field.get("fieldMetadataId")))
            if name is not None:
                actual_visible[name] = view_field
        difference(
            differences,
            f"{prefix}.visibleFields",
            sorted(expected_by_name),
            sorted(actual_visible),
        )
        for name, expected in expected_by_name.items():
            actual_field = actual_visible.get(name)
            if actual_field is None:
                continue
            difference(
                differences,
                f"{prefix}.fields.{name}.position",
                float(expected["position"]),
                float(actual_field["position"]),
            )
            difference(
                differences,
                f"{prefix}.fields.{name}.size",
                float(expected["size"]),
                float(actual_field["size"]),
            )
        return differences

    def ensure_roles(self) -> None:
        objects = self.object_map()
        for desired in json_list(self.manifest["roles"], "roles"):
            roles = self.roles()
            actual = one_by(roles, "id", str(desired["id"]), "Role-ID")
            if actual is None:
                same_label = one_by(
                    roles,
                    "label",
                    str(desired["label"]),
                    "Role-Label",
                )
                if same_label is not None:
                    raise SchemaDrift(
                        [
                            {
                                "path": f"roles.{desired['label']}.id",
                                "expected": desired["id"],
                                "actual": same_label.get("id"),
                            }
                        ]
                    )
                self.create_role(desired)
                self.wait_for_role(str(desired["id"]))
            self.upsert_role_permissions(desired, objects)
            actual = self.wait_for_role(str(desired["id"]))
            drifts = self.role_differences(desired, actual, objects)
            if drifts:
                raise SchemaDrift(drifts)

    def wait_for_role(self, role_id: str) -> JsonObject:
        return self.wait_until_visible(
            f"Role {role_id}",
            lambda: one_by(self.roles(), "id", role_id, "Role-ID"),
            timeout=60,
        )

    def expected_field_restrictions(
        self,
        desired: JsonObject,
        objects: dict[str, JsonObject],
    ) -> list[JsonObject]:
        restrictions: list[JsonObject] = []
        for permission in json_list(desired["objects"], "role.objects"):
            if permission.get("allFields") is True:
                continue
            object_name = str(permission["object"])
            actual_object = objects[object_name]
            read_fields = set(permission.get("readFields", []))
            update_fields = set(permission.get("updateFields", []))
            for field in json_list(actual_object.get("fields"), "object.fields"):
                name = str(field["name"])
                can_read = name in read_fields
                can_update = name in update_fields
                if can_read and can_update:
                    continue
                restrictions.append(
                    {
                        "object": object_name,
                        "field": name,
                        "canRead": can_read,
                        "canUpdate": can_update,
                    }
                )
        return sorted(restrictions, key=lambda item: (item["object"], item["field"]))

    def role_differences(
        self,
        desired: JsonObject,
        actual: JsonObject,
        objects: dict[str, JsonObject],
    ) -> list[JsonObject]:
        differences: list[JsonObject] = []
        prefix = f"roles.{desired['label']}"
        for key in (
            "id",
            "label",
            "description",
            "icon",
            "canBeAssignedToUsers",
            "canBeAssignedToAgents",
            "canBeAssignedToApiKeys",
        ):
            difference(differences, f"{prefix}.{key}", desired[key], actual.get(key))
        for key in (
            "canUpdateAllSettings",
            "canAccessAllTools",
            "canReadAllObjectRecords",
            "canUpdateAllObjectRecords",
            "canSoftDeleteAllObjectRecords",
            "canDestroyAllObjectRecords",
        ):
            difference(differences, f"{prefix}.{key}", False, actual.get(key))
        flags = sorted(
            str(item["flag"])
            for item in json_list(actual.get("permissionFlags") or [], "flags")
        )
        difference(
            differences,
            f"{prefix}.permissionFlags",
            sorted(desired["permissionFlags"]),
            flags,
        )

        name_by_id = {
            str(item["id"]): name for name, item in objects.items() if "id" in item
        }
        actual_permissions: list[JsonObject] = []
        for permission in json_list(
            actual.get("objectPermissions") or [],
            "objectPermissions",
        ):
            values = {
                "canRead": permission.get("canReadObjectRecords") is True,
                "canUpdate": permission.get("canUpdateObjectRecords") is True,
                "canSoftDelete": permission.get("canSoftDeleteObjectRecords") is True,
                "canDestroy": permission.get("canDestroyObjectRecords") is True,
            }
            if not any(values.values()):
                continue
            name = name_by_id.get(str(permission.get("objectMetadataId")))
            if name is None:
                name = f"unknown:{permission.get('objectMetadataId')}"
            actual_permissions.append({"object": name, **values})
        expected_permissions = [
            {
                "object": permission["object"],
                "canRead": permission["canRead"],
                "canUpdate": permission["canUpdate"],
                "canSoftDelete": permission["canSoftDelete"],
                "canDestroy": permission["canDestroy"],
            }
            for permission in json_list(desired["objects"], "role.objects")
        ]

        def sort_key(item: JsonObject) -> str:
            return str(item["object"])

        difference(
            differences,
            f"{prefix}.objectPermissions",
            sorted(expected_permissions, key=sort_key),
            sorted(actual_permissions, key=sort_key),
        )

        field_by_id: dict[str, tuple[str, str]] = {}
        for object_name, actual_object in objects.items():
            for field in json_list(actual_object.get("fields"), "object.fields"):
                field_by_id[str(field["id"])] = (object_name, str(field["name"]))
        actual_restrictions: list[JsonObject] = []
        allowed_object_names = {
            str(permission["object"])
            for permission in json_list(desired["objects"], "role.objects")
        }
        for permission in json_list(
            actual.get("fieldPermissions") or [],
            "fieldPermissions",
        ):
            coordinates = field_by_id.get(str(permission.get("fieldMetadataId")))
            if coordinates is None or coordinates[0] not in allowed_object_names:
                continue
            actual_restrictions.append(
                {
                    "object": coordinates[0],
                    "field": coordinates[1],
                    "canRead": permission.get("canReadFieldValue") is not False,
                    "canUpdate": permission.get("canUpdateFieldValue") is not False,
                }
            )

        def field_sort(item: JsonObject) -> tuple[str, str]:
            return (str(item["object"]), str(item["field"]))

        difference(
            differences,
            f"{prefix}.fieldRestrictions",
            self.expected_field_restrictions(desired, objects),
            sorted(actual_restrictions, key=field_sort),
        )
        return differences

    def ensure_api_key(self, token_output: Path | None) -> None:
        desired = json_object(self.manifest["apiKey"], "apiKey")
        role_label = str(desired["role"])
        role = one_by(self.roles(), "label", role_label, "API-Key-Role")
        if role is None:
            raise TwentySchemaError(f"API key role missing: {role_label}")
        keys = self.api_keys()
        actual = one_by(keys, "name", str(desired["name"]), "API-Key")
        if actual is None:
            actual = self.create_api_key(desired, str(role["id"]))
        drifts: list[JsonObject] = []
        actual_role = actual.get("role")
        difference(
            drifts,
            f"apiKey.{desired['name']}.role",
            role_label,
            actual_role.get("label") if isinstance(actual_role, dict) else None,
        )
        difference(
            drifts,
            f"apiKey.{desired['name']}.expiresAt",
            normalized_instant(desired["expiresAt"]),
            normalized_instant(actual.get("expiresAt")),
        )
        difference(
            drifts,
            f"apiKey.{desired['name']}.revokedAt",
            None,
            actual.get("revokedAt"),
        )
        if drifts:
            raise SchemaDrift(drifts)
        if token_output is not None and not token_output.exists():
            token = self.generate_api_token(
                str(actual["id"]),
                str(desired["expiresAt"]),
            )
            write_secret(token_output, "TWENTY_INTEGRATION_API_KEY", token)

    def check(self) -> JsonObject:
        differences: list[JsonObject] = []
        objects = self.object_map()
        for desired_object in json_list(self.manifest["objects"], "objects"):
            object_name = str(desired_object["nameSingular"])
            actual_object = objects.get(object_name)
            if actual_object is None:
                difference(
                    differences,
                    f"objects.{object_name}",
                    "present",
                    "missing",
                )
                continue
            differences.extend(self.object_differences(desired_object, actual_object))
            details = self.object_details(str(actual_object["id"]))
            fields = {
                str(field["name"]): field
                for field in json_list(details.get("fieldsList"), "fieldsList")
            }
            for desired_field in json_list(desired_object["fields"], "fields"):
                field_name = str(desired_field["name"])
                actual_field = fields.get(field_name)
                if actual_field is None:
                    difference(
                        differences,
                        f"objects.{object_name}.fields.{field_name}",
                        "present",
                        "missing",
                    )
                    continue
                differences.extend(
                    self.field_differences(
                        object_name,
                        desired_field,
                        actual_field,
                    )
                )
        for desired_object in standard_objects(self.manifest):
            object_name = str(desired_object["nameSingular"])
            actual_object = objects.get(object_name)
            if actual_object is None:
                difference(
                    differences,
                    f"standardObjects.{object_name}",
                    "present",
                    "missing",
                )
                continue
            details = self.object_details(str(actual_object["id"]))
            fields = {
                str(field["name"]): field
                for field in json_list(details.get("fieldsList"), "fieldsList")
            }
            for desired_field in json_list(desired_object["fields"], "fields"):
                field_name = str(desired_field["name"])
                actual_field = fields.get(field_name)
                if actual_field is None:
                    difference(
                        differences,
                        f"objects.{object_name}.fields.{field_name}",
                        "present",
                        "missing",
                    )
                    continue
                differences.extend(
                    self.field_differences(object_name, desired_field, actual_field)
                )
        for desired_view in json_list(self.manifest["views"], "views"):
            object_name = str(desired_view["object"])
            actual_object = objects.get(object_name)
            if actual_object is None:
                continue
            actual_view = one_by(
                self.views(str(actual_object["id"])),
                "id",
                str(desired_view["id"]),
                "View-ID",
            )
            if actual_view is None:
                difference(
                    differences,
                    f"views.{desired_view['name']}",
                    "present",
                    "missing",
                )
            else:
                differences.extend(
                    self.view_differences(
                        desired_view,
                        actual_view,
                        actual_object,
                    )
                )
        roles = self.roles()
        for desired_role in json_list(self.manifest["roles"], "roles"):
            actual_role = one_by(
                roles,
                "id",
                str(desired_role["id"]),
                "Role-ID",
            )
            if actual_role is None:
                difference(
                    differences,
                    f"roles.{desired_role['label']}",
                    "present",
                    "missing",
                )
            else:
                differences.extend(
                    self.role_differences(desired_role, actual_role, objects)
                )
        desired_key = json_object(self.manifest["apiKey"], "apiKey")
        actual_key = one_by(
            self.api_keys(),
            "name",
            str(desired_key["name"]),
            "API-Key",
        )
        if actual_key is None:
            difference(
                differences,
                f"apiKey.{desired_key['name']}",
                "present",
                "missing",
            )
        else:
            actual_role = actual_key.get("role")
            difference(
                differences,
                f"apiKey.{desired_key['name']}.role",
                desired_key["role"],
                actual_role.get("label") if isinstance(actual_role, dict) else None,
            )
            difference(
                differences,
                f"apiKey.{desired_key['name']}.expiresAt",
                normalized_instant(desired_key["expiresAt"]),
                normalized_instant(actual_key.get("expiresAt")),
            )
            difference(
                differences,
                f"apiKey.{desired_key['name']}.revokedAt",
                None,
                actual_key.get("revokedAt"),
            )
        if differences:
            raise SchemaDrift(differences)
        return self.snapshot()

    def apply(self, token_output: Path | None) -> JsonObject:
        self.ensure_objects()
        self.ensure_fields()
        self.ensure_standard_fields()
        self.ensure_views()
        self.ensure_roles()
        self.ensure_api_key(token_output)
        return self.check()

    def snapshot(self) -> JsonObject:
        objects = self.object_map()
        managed_objects: list[JsonObject] = []
        for desired in json_list(self.manifest["objects"], "objects"):
            object_name = str(desired["nameSingular"])
            actual = objects[object_name]
            details = self.object_details(str(actual["id"]))
            fields_by_name = {
                str(field["name"]): field
                for field in json_list(details["fieldsList"], "fieldsList")
            }
            fields = [
                field_snapshot(
                    desired_field, fields_by_name[str(desired_field["name"])]
                )
                for desired_field in json_list(desired["fields"], "fields")
            ]
            managed_objects.append(
                {
                    "nameSingular": actual["nameSingular"],
                    "namePlural": actual["namePlural"],
                    "labelSingular": actual["labelSingular"],
                    "labelPlural": actual["labelPlural"],
                    "description": actual.get("description"),
                    "icon": actual.get("icon"),
                    "isSearchable": actual["isSearchable"],
                    "fields": fields,
                }
            )
        managed_standard_objects: list[JsonObject] = []
        for desired in standard_objects(self.manifest):
            object_name = str(desired["nameSingular"])
            details = self.object_details(str(objects[object_name]["id"]))
            fields_by_name = {
                str(field["name"]): field
                for field in json_list(details["fieldsList"], "fieldsList")
            }
            managed_standard_objects.append(
                {
                    "nameSingular": object_name,
                    "fields": [
                        field_snapshot(
                            desired_field,
                            fields_by_name[str(desired_field["name"])],
                        )
                        for desired_field in json_list(desired["fields"], "fields")
                    ],
                }
            )
        views: list[JsonObject] = []
        for desired in json_list(self.manifest["views"], "views"):
            actual_object = objects[str(desired["object"])]
            actual_view = one_by(
                self.views(str(actual_object["id"])),
                "id",
                str(desired["id"]),
                "View-ID",
            )
            if actual_view is None:
                raise TwentySchemaError(f"view missing in snapshot: {desired['name']}")
            field_name_by_id = {
                str(field["id"]): str(field["name"])
                for field in json_list(actual_object["fields"], "object.fields")
            }
            visible = [
                {
                    "field": field_name_by_id[str(item["fieldMetadataId"])],
                    "position": float(item["position"]),
                    "size": float(item["size"]),
                }
                for item in json_list(actual_view["viewFields"], "viewFields")
                if item.get("isVisible") is True
                and str(item.get("fieldMetadataId")) in field_name_by_id
            ]
            views.append(
                {
                    "id": actual_view["id"],
                    "object": desired["object"],
                    "name": actual_view["name"],
                    "type": actual_view["type"],
                    "icon": actual_view["icon"],
                    "position": actual_view["position"],
                    "isCompact": actual_view["isCompact"],
                    "openRecordIn": actual_view["openRecordIn"],
                    "fields": sorted(visible, key=lambda item: item["position"]),
                }
            )
        roles = self.roles()
        role_snapshot: list[JsonObject] = []
        for desired in json_list(self.manifest["roles"], "roles"):
            actual_role = one_by(
                roles,
                "id",
                str(desired["id"]),
                "Role-ID",
            )
            if actual_role is None:
                raise TwentySchemaError(f"role missing in snapshot: {desired['label']}")
            role_snapshot.append(
                {
                    "id": actual_role["id"],
                    "label": actual_role["label"],
                    "description": actual_role.get("description"),
                    "icon": actual_role.get("icon"),
                    "canBeAssignedToUsers": actual_role["canBeAssignedToUsers"],
                    "canBeAssignedToAgents": actual_role["canBeAssignedToAgents"],
                    "canBeAssignedToApiKeys": actual_role["canBeAssignedToApiKeys"],
                    "permissionFlags": sorted(
                        str(item["flag"])
                        for item in json_list(
                            actual_role.get("permissionFlags") or [],
                            "permissionFlags",
                        )
                    ),
                    "objects": desired["objects"],
                }
            )
        key = one_by(
            self.api_keys(),
            "name",
            str(self.manifest["apiKey"]["name"]),
            "API-Key",
        )
        if key is None:
            raise TwentySchemaError("API key missing in snapshot")
        key_role = json_object(key["role"], "apiKey.role")
        return {
            "schemaVersion": self.manifest["schemaVersion"],
            "twentyVersion": self.manifest["twenty"]["version"],
            "objects": managed_objects,
            "standardObjects": managed_standard_objects,
            "views": views,
            "roles": role_snapshot,
            "apiKey": {
                "name": key["name"],
                "role": key_role["label"],
                "expiresAt": normalized_instant(key["expiresAt"]),
                "revokedAt": key.get("revokedAt"),
            },
        }

    def mutate_field(self, object_name: str, field_name: str, label: str) -> None:
        actual_object = self.object_map().get(object_name)
        if actual_object is None:
            raise TwentySchemaError(f"object for drift mutation missing: {object_name}")
        fields = json_list(actual_object.get("fields"), "object.fields")
        field = one_by(fields, "name", field_name, "Field")
        if field is None:
            raise TwentySchemaError(
                f"field for drift mutation missing: {object_name}.{field_name}"
            )
        self.metadata(
            """
            mutation UpdateField($input: UpdateOneFieldMetadataInput!) {
              updateOneField(input: $input) { id label }
            }
            """,
            {"input": {"id": field["id"], "update": {"label": label}}},
        )


def apply_with_metadata_retry(
    provisioner: Provisioner,
    token_output: Path | None,
) -> JsonObject:
    deadline = time.monotonic() + 90
    while True:
        try:
            return provisioner.apply(token_output)
        except SeedError as error:
            if (
                TRANSIENT_FLAT_ENTITY_ERROR not in str(error)
                or time.monotonic() >= deadline
            ):
                raise
            time.sleep(0.5)


def write_json(path: Path, value: JsonObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_secret(path: Path, name: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{name}={value}\n", encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def read_secret(path: Path, name: str) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise TwentySchemaError(f"API key file is not readable: {error}") from error
    prefix = f"{name}="
    values = [line[len(prefix) :] for line in lines if line.startswith(prefix)]
    if len(values) != 1 or len(values[0]) < 32:
        raise TwentySchemaError(f"{path} has no valid {name}")
    return values[0]


def is_permission_denied(response: httpx.Response) -> bool:
    if response.status_code in {401, 403}:
        return True
    if response.status_code != 400:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    return isinstance(payload, dict) and payload.get("code") == "PERMISSION_DENIED"


def verify_integration_key(path: Path, base_url: str) -> None:
    token = read_secret(path, "TWENTY_INTEGRATION_API_KEY")
    client = httpx.Client(
        base_url=base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    try:
        proof_match_key = f"poc 030 berechtigungsnachweis {uuid.uuid4().hex}"
        allowed = client.post(
            "/rest/companies",
            json={
                "name": "POC-030 Berechtigungsnachweis",
                "leonaidMatchKey": proof_match_key,
            },
        )
        if allowed.status_code not in {200, 201}:
            raise TwentySchemaError(
                "integration key cannot write an allowed company: "
                f"HTTP {allowed.status_code} {allowed.text[:300]}"
            )
        created_payload = json_object(allowed.json(), "Create Company response")
        created_data: Any = created_payload.get("data", created_payload)
        if isinstance(created_data, dict) and len(created_data) == 1:
            nested = next(iter(created_data.values()))
            if isinstance(nested, dict):
                created_data = nested
        created = json_object(created_data, "Create Company data")
        proof_id = created.get("id")
        if not isinstance(proof_id, str):
            raise TwentySchemaError("Twenty returned no ID for the allowed company")
        company = client.get(f"/rest/companies/{proof_id}")
        if company.status_code != 200:
            raise TwentySchemaError(
                "integration key cannot read an allowed company: "
                f"HTTP {company.status_code}"
            )
        payload = json_object(company.json(), "Company response")
        data = payload.get("data", payload)
        if isinstance(data, dict) and len(data) == 1:
            nested = next(iter(data.values()))
            if isinstance(nested, dict):
                data = nested
        record = json_object(data, "Company data")
        if "domainName" in record or "annualRevenue" in record:
            raise TwentySchemaError(
                "integration key sees company fields that are not granted"
            )
        if record.get("leonaidMatchKey") != proof_match_key:
            raise TwentySchemaError(
                "integration key cannot maintain the LeonAid match key"
            )
        by_key = client.get(
            "/rest/companies",
            params={
                "limit": 2,
                "filter": f"leonaidMatchKey[eq]:{json.dumps(proof_match_key)}",
            },
        )
        if by_key.status_code != 200:
            raise TwentySchemaError(
                "integration key cannot filter by the match key: "
                f"HTTP {by_key.status_code}"
            )
        key_payload = json_object(by_key.json(), "Match-Key-Filter response")
        key_data = json_object(key_payload.get("data"), "Match-Key-Filter data")
        key_ids = [
            item.get("id") for item in json_list(key_data.get("companies"), "companies")
        ]
        if key_ids != [proof_id]:
            raise TwentySchemaError(
                "match key filter does not return exactly the proof company"
            )

        custom = client.get("/rest/charityActions?limit=1")
        if custom.status_code != 200:
            raise TwentySchemaError(
                "integration key cannot read charity actions: "
                f"HTTP {custom.status_code}"
            )
        unrelated = client.get("/rest/opportunities?limit=1")
        if not is_permission_denied(unrelated):
            raise TwentySchemaError(
                "integration key could read unrelated opportunities: "
                f"HTTP {unrelated.status_code} {unrelated.text[:300]}"
            )
        administrative = client.post(
            "/metadata",
            json={"query": "query Forbidden { getRoles { id label } }"},
        )
        denied = is_permission_denied(administrative)
        if administrative.status_code == 200:
            admin_payload = json_object(
                administrative.json(),
                "administrative response",
            )
            admin_data = admin_payload.get("data")
            denied = bool(admin_payload.get("errors")) and (
                not isinstance(admin_data, dict) or not admin_data.get("getRoles")
            )
        if not denied:
            raise TwentySchemaError(
                "integration key could read administrative role metadata"
            )
    finally:
        client.close()


def run(arguments: argparse.Namespace) -> None:
    manifest = load_manifest(arguments.manifest.resolve())
    if arguments.command == "verify-key":
        verify_integration_key(
            arguments.token_file.resolve(),
            os.environ["TWENTY_BASE_URL"],
        )
        print(
            "twenty-key: OK: allowed CRM objects usable; "
            "unrelated objects and administration denied"
        )
        return

    if arguments.command == "flush-workspace-cache":
        deleted = flush_workspace_cache(
            os.environ.get("TWENTY_REDIS_URL", DEFAULT_TWENTY_REDIS_URL)
        )
        print(f"twenty-cache: OK: {deleted} workspace cache keys dropped")
        return

    provisioner = Provisioner(manifest)
    try:
        if arguments.command == "apply":
            value = apply_with_metadata_retry(
                provisioner,
                arguments.token_output.resolve()
                if arguments.token_output is not None
                else None,
            )
            if arguments.snapshot_output is not None:
                write_json(arguments.snapshot_output.resolve(), value)
            print(
                "twenty-provision: OK: schema, views, roles and API key "
                "match the declaration"
            )
        elif arguments.command == "check":
            value = provisioner.check()
            if arguments.snapshot_output is not None:
                write_json(arguments.snapshot_output.resolve(), value)
            print("twenty-check: OK: no drift from the declaration")
        elif arguments.command == "snapshot":
            write_json(arguments.output.resolve(), provisioner.check())
            print(f"twenty-snapshot: OK: {arguments.output}")
        else:
            provisioner.mutate_field(
                arguments.object,
                arguments.field,
                arguments.label,
            )
            print(
                "twenty-mutate: OK: "
                f"{arguments.object}.{arguments.field}.label changed on purpose"
            )
    finally:
        provisioner.close()


def die(error: Exception) -> NoReturn:
    print(f"twenty-schema: ERROR: {error}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("infra/twenty/schema.json"),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    apply_command = commands.add_parser("apply")
    apply_command.add_argument("--token-output", type=Path)
    apply_command.add_argument("--snapshot-output", type=Path)

    check_command = commands.add_parser("check")
    check_command.add_argument("--snapshot-output", type=Path)

    snapshot_command = commands.add_parser("snapshot")
    snapshot_command.add_argument("output", type=Path)

    mutate_command = commands.add_parser("mutate-field")
    mutate_command.add_argument("--object", required=True)
    mutate_command.add_argument("--field", required=True)
    mutate_command.add_argument("--label", required=True)

    commands.add_parser("flush-workspace-cache")

    verify_key_command = commands.add_parser("verify-key")
    verify_key_command.add_argument("--token-file", required=True, type=Path)

    arguments = parser.parse_args()
    try:
        run(arguments)
    except (
        TwentySchemaError,
        SeedError,
        httpx.HTTPError,
        KeyError,
        RedisError,
        OSError,
    ) as error:
        die(error)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
