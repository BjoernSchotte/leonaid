#!/usr/bin/env python3
"""Provision and verify LeonAid's declared Twenty metadata contract."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

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
        lines = ["Twenty-Schema weicht von infra/twenty/schema.json ab:"]
        for difference in differences:
            lines.append(
                "  - "
                f"{difference['path']}: "
                f"erwartet={json.dumps(difference['expected'], ensure_ascii=False, sort_keys=True)} "
                f"vorhanden={json.dumps(difference['actual'], ensure_ascii=False, sort_keys=True)}"
            )
        super().__init__("\n".join(lines))


def json_object(value: Any, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise TwentySchemaError(f"{label} muss ein JSON-Objekt sein")
    return value


def json_list(value: Any, label: str) -> JsonList:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise TwentySchemaError(f"{label} muss eine Liste aus JSON-Objekten sein")
    return value


def load_manifest(path: Path) -> JsonObject:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TwentySchemaError(f"Twenty-Manifest ist nicht lesbar: {error}") from error
    value = json_object(manifest, str(path))
    if value.get("schemaVersion") != 1:
        raise TwentySchemaError("unerwartete Twenty-Schema-Version")
    objects = json_list(value.get("objects"), "objects")
    object_names = [item.get("nameSingular") for item in objects]
    if any(not isinstance(name, str) or not name for name in object_names):
        raise TwentySchemaError("jedes Custom Object braucht nameSingular")
    if len(object_names) != len(set(object_names)):
        raise TwentySchemaError("doppelte Custom-Object-Namen im Manifest")
    return value


def one_by(
    items: JsonList,
    key: str,
    value: str,
    label: str,
) -> JsonObject | None:
    matches = [item for item in items if item.get(key) == value]
    if len(matches) > 1:
        raise TwentySchemaError(f"{label} ist mehrfach vorhanden: {value}")
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
        raise TwentySchemaError(f"Zeitpunkt ist kein String: {value!r}")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def difference(
    differences: list[JsonObject],
    path: str,
    expected: Any,
    actual: Any,
) -> None:
    if expected != actual:
        differences.append({"path": path, "expected": expected, "actual": actual})


class Provisioner:
    """Narrow adapter for the supported Twenty v2.24.0 Metadata API."""

    def __init__(self, manifest: JsonObject) -> None:
        self.manifest = manifest
        self.client = TwentyClient()
        self.client.authenticate()

    def close(self) -> None:
        self.client.close()

    def metadata(self, query: str, variables: JsonObject | None = None) -> JsonObject:
        if self.client.access_token is None:
            raise TwentySchemaError("Twenty-Admin-Sitzung fehlt")
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
                isCustom
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
                raise TwentySchemaError(f"Twenty Object ist doppelt: {name}")
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
                    f"Relationsziel fehlt vor Provisionierung: {target_name}"
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
                raise TwentySchemaError(
                    f"Rollenobjekt ist nicht vorhanden: {object_name}"
                )
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
                    f"Rollenfeld fehlt in {object_name}: {', '.join(missing)}"
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
            raise TwentySchemaError("Twenty erzeugte keinen gültigen API-Key-Token")
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

    def wait_for_object(self, name: str) -> dict[str, JsonObject]:
        deadline = time.monotonic() + 90
        while True:
            objects = self.object_map()
            if name in objects:
                return objects
            if time.monotonic() >= deadline:
                raise TwentySchemaError(
                    f"Twenty Metadata API veröffentlichte Object nicht: {name}"
                )
            time.sleep(0.5)

    def wait_for_field(self, object_name: str, field_name: str) -> None:
        deadline = time.monotonic() + 90
        while True:
            actual_object = self.object_map().get(object_name)
            if actual_object is not None:
                fields = json_list(actual_object.get("fields"), object_name)
                if any(field.get("name") == field_name for field in fields):
                    return
            if time.monotonic() >= deadline:
                raise TwentySchemaError(
                    "Twenty Metadata API veröffentlichte Field nicht: "
                    f"{object_name}.{field_name}"
                )
            time.sleep(0.5)

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
                        self.wait_for_field(object_name, field_name)
                        objects = self.object_map()
                        details = self.object_details(object_id)
                        fields = {
                            str(field["name"]): field
                            for field in json_list(
                                details.get("fieldsList"), "fieldsList"
                            )
                        }
                        actual = fields.get(field_name)
                    if actual is None:
                        raise TwentySchemaError(
                            f"Field fehlt nach Provisionierung: {object_name}.{field_name}"
                        )
                    drifts = self.field_differences(object_name, desired, actual)
                    if drifts:
                        raise SchemaDrift(drifts)
            objects = self.object_map()

    def ensure_views(self) -> None:
        objects = self.object_map()
        for desired in json_list(self.manifest["views"], "views"):
            object_name = str(desired["object"])
            actual_object = objects.get(object_name)
            if actual_object is None:
                raise TwentySchemaError(f"View-Object fehlt: {object_name}")
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
        deadline = time.monotonic() + 60
        while True:
            view = one_by(self.views(object_id), "id", view_id, "View-ID")
            if view is not None:
                return view
            if time.monotonic() >= deadline:
                raise TwentySchemaError(f"Twenty veröffentlichte View nicht: {view_id}")
            time.sleep(0.5)

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
                    f"View-Feld existiert nicht: {desired['name']}.{field_name}"
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
        difference(differences, f"{prefix}.isCustom", True, actual.get("isCustom"))
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
        deadline = time.monotonic() + 60
        while True:
            role = one_by(self.roles(), "id", role_id, "Role-ID")
            if role is not None:
                return role
            if time.monotonic() >= deadline:
                raise TwentySchemaError(f"Twenty veröffentlichte Role nicht: {role_id}")
            time.sleep(0.5)

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
            raise TwentySchemaError(f"API-Key-Role fehlt: {role_label}")
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
                    "vorhanden",
                    "fehlt",
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
                        "vorhanden",
                        "fehlt",
                    )
                    continue
                differences.extend(
                    self.field_differences(
                        object_name,
                        desired_field,
                        actual_field,
                    )
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
                    "vorhanden",
                    "fehlt",
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
                    "vorhanden",
                    "fehlt",
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
                "vorhanden",
                "fehlt",
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
            fields: list[JsonObject] = []
            for desired_field in json_list(desired["fields"], "fields"):
                actual_field = fields_by_name[str(desired_field["name"])]
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
                fields.append(item)
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
                raise TwentySchemaError(f"View fehlt im Snapshot: {desired['name']}")
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
                raise TwentySchemaError(f"Role fehlt im Snapshot: {desired['label']}")
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
            raise TwentySchemaError("API-Key fehlt im Snapshot")
        key_role = json_object(key["role"], "apiKey.role")
        return {
            "schemaVersion": self.manifest["schemaVersion"],
            "twentyVersion": self.manifest["twenty"]["version"],
            "objects": managed_objects,
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
            raise TwentySchemaError(f"Object für Drift-Mutation fehlt: {object_name}")
        fields = json_list(actual_object.get("fields"), "object.fields")
        field = one_by(fields, "name", field_name, "Field")
        if field is None:
            raise TwentySchemaError(
                f"Field für Drift-Mutation fehlt: {object_name}.{field_name}"
            )
        self.metadata(
            """
            mutation UpdateField($input: UpdateOneFieldMetadataInput!) {
              updateOneField(input: $input) { id label }
            }
            """,
            {"input": {"id": field["id"], "update": {"label": label}}},
        )


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
        raise TwentySchemaError(f"API-Key-Datei ist nicht lesbar: {error}") from error
    prefix = f"{name}="
    values = [line[len(prefix) :] for line in lines if line.startswith(prefix)]
    if len(values) != 1 or len(values[0]) < 32:
        raise TwentySchemaError(f"{path} enthält keinen gültigen {name}")
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
        allowed = client.post(
            "/rest/companies",
            json={"name": "POC-030 Berechtigungsnachweis"},
        )
        if allowed.status_code not in {200, 201}:
            raise TwentySchemaError(
                "Integrations-Key darf erlaubte Company nicht schreiben: "
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
            raise TwentySchemaError("Twenty lieferte keine ID für die erlaubte Company")
        company = client.get(f"/rest/companies/{proof_id}")
        if company.status_code != 200:
            raise TwentySchemaError(
                "Integrations-Key darf erlaubte Company nicht lesen: "
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
                "Integrations-Key sieht nicht freigegebene Company-Felder"
            )

        custom = client.get("/rest/charityActions?limit=1")
        if custom.status_code != 200:
            raise TwentySchemaError(
                "Integrations-Key darf Charity-Aktionen nicht lesen: "
                f"HTTP {custom.status_code}"
            )
        unrelated = client.get("/rest/opportunities?limit=1")
        if not is_permission_denied(unrelated):
            raise TwentySchemaError(
                "Integrations-Key konnte fachfremde Opportunities lesen: "
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
                "Integrations-Key konnte administrative Rollen-Metadaten lesen"
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
            "twenty-key: OK: erlaubte CRM-Objekte nutzbar; "
            "fachfremde Objekte und Administration verweigert"
        )
        return

    provisioner = Provisioner(manifest)
    try:
        if arguments.command == "apply":
            value = provisioner.apply(
                arguments.token_output.resolve()
                if arguments.token_output is not None
                else None
            )
            if arguments.snapshot_output is not None:
                write_json(arguments.snapshot_output.resolve(), value)
            print(
                "twenty-provision: OK: Schema, Views, Rollen und API-Key "
                "sind deklarationsgleich"
            )
        elif arguments.command == "check":
            value = provisioner.check()
            if arguments.snapshot_output is not None:
                write_json(arguments.snapshot_output.resolve(), value)
            print("twenty-check: OK: kein Drift zur Deklaration")
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
                f"{arguments.object}.{arguments.field}.label absichtlich geändert"
            )
    finally:
        provisioner.close()


def die(error: Exception) -> NoReturn:
    print(f"twenty-schema: FEHLER: {error}", file=sys.stderr)
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

    verify_key_command = commands.add_parser("verify-key")
    verify_key_command.add_argument("--token-file", required=True, type=Path)

    arguments = parser.parse_args()
    try:
        run(arguments)
    except (TwentySchemaError, SeedError, httpx.HTTPError, KeyError) as error:
        die(error)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
