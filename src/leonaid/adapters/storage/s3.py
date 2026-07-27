"""S3-compatible adapter for the provider-neutral object-storage port."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import timedelta
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from leonaid.application.object_storage import (
    ObjectDeletionAuthorization,
    ObjectLocation,
    ObjectStorageConflict,
    ObjectStorageIntegrityError,
    ObjectStorageNotFound,
    ObjectStorageUnavailable,
    ObjectWrite,
    RetrievedObject,
    StoredObject,
)

NOT_FOUND_CODES = {"404", "NoSuchBucket", "NoSuchKey", "NoSuchVersion", "NotFound"}
PRECONDITION_CODES = {"409", "412", "ConditionalRequestConflict", "PreconditionFailed"}


class S3ObjectStorage:
    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
        path_style: bool = True,
    ) -> None:
        if not endpoint_url.strip() or not bucket.strip():
            raise ValueError("S3-Endpunkt und Bucket dürfen nicht leer sein.")
        self._bucket = bucket
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path" if path_style else "virtual"},
                connect_timeout=3,
                read_timeout=15,
                retries={"max_attempts": 0},
            ),
        )

    @property
    def bucket(self) -> str:
        return self._bucket

    async def ensure_private_versioned_bucket(self) -> None:
        await asyncio.to_thread(self._ensure_private_versioned_bucket)

    def _ensure_private_versioned_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as error:
            if self._error_code(error) not in NOT_FOUND_CODES:
                raise self._unavailable(
                    "Bucket konnte nicht geprüft werden."
                ) from error
            try:
                self._client.create_bucket(Bucket=self._bucket)
            except (BotoCoreError, ClientError) as create_error:
                raise self._unavailable(
                    "Privater Bucket konnte nicht angelegt werden."
                ) from create_error
        except BotoCoreError as error:
            raise self._unavailable("Bucket konnte nicht geprüft werden.") from error
        try:
            self._client.put_bucket_versioning(
                Bucket=self._bucket,
                VersioningConfiguration={"Status": "Enabled"},
            )
            versioning = self._client.get_bucket_versioning(Bucket=self._bucket)
        except (BotoCoreError, ClientError) as error:
            raise self._unavailable(
                "Bucket-Versionierung konnte nicht aktiviert werden."
            ) from error
        if versioning.get("Status") != "Enabled":
            raise ObjectStorageIntegrityError(
                "Der private Bucket bestätigt keine aktive Versionierung."
            )

    async def put_immutable(self, write: ObjectWrite) -> StoredObject:
        if write.location.bucket != self._bucket:
            raise ObjectStorageConflict(
                "Der Schreibauftrag gehört nicht zum konfigurierten Bucket."
            )
        existing = await self.head(write.location)
        if existing is not None:
            return self._require_same(existing, write)
        metadata = {
            **{key.casefold(): value for key, value in write.metadata.items()},
            "sha256": write.sha256,
        }
        try:
            response = await asyncio.to_thread(
                self._client.put_object,
                Bucket=write.location.bucket,
                Key=write.location.key,
                Body=write.content,
                ContentType=write.media_type,
                ContentLength=len(write.content),
                Metadata=metadata,
                ChecksumSHA256=base64.b64encode(
                    hashlib.sha256(write.content).digest()
                ).decode("ascii"),
                IfNoneMatch="*",
            )
        except ClientError as error:
            if self._error_code(error) in PRECONDITION_CODES:
                collided = await self.head(write.location)
                if collided is not None:
                    return self._require_same(collided, write)
                raise ObjectStorageConflict(
                    "Der unveränderliche Object Key wurde parallel belegt."
                ) from error
            raise self._unavailable(
                "Objekt konnte nicht gespeichert werden."
            ) from error
        except BotoCoreError as error:
            raise self._unavailable(
                "Objekt konnte nicht gespeichert werden."
            ) from error
        version_id = self._version_id(response)
        stored = await self.head(
            ObjectLocation(
                bucket=write.location.bucket,
                key=write.location.key,
                version_id=version_id,
            )
        )
        if stored is None:
            raise ObjectStorageIntegrityError(
                "Das geschriebene Objekt ist über seine Version-ID nicht lesbar."
            )
        return self._require_same(stored, write)

    async def head(self, location: ObjectLocation) -> StoredObject | None:
        self._require_bucket(location)
        try:
            response = await asyncio.to_thread(
                self._client.head_object,
                **self._object_parameters(location),
            )
        except ClientError as error:
            if self._error_code(error) in NOT_FOUND_CODES:
                return None
            raise self._unavailable(
                "Objekt-Metadaten sind nicht erreichbar."
            ) from error
        except BotoCoreError as error:
            raise self._unavailable(
                "Objekt-Metadaten sind nicht erreichbar."
            ) from error
        metadata = {
            str(key).casefold(): str(value)
            for key, value in dict(response.get("Metadata", {})).items()
        }
        sha256 = metadata.get("sha256", "")
        return StoredObject(
            location=ObjectLocation(
                bucket=location.bucket,
                key=location.key,
                version_id=self._version_id(response),
            ),
            media_type=str(response.get("ContentType", "application/octet-stream")),
            size_bytes=int(response.get("ContentLength", -1)),
            sha256=sha256,
            metadata={key: value for key, value in metadata.items() if key != "sha256"},
        )

    async def get(self, location: ObjectLocation) -> RetrievedObject:
        self._require_bucket(location)
        if not location.version_id:
            raise ObjectStorageIntegrityError(
                "Ein geschützter Download benötigt eine exakte Version-ID."
            )
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                **self._object_parameters(location),
            )
            content = await asyncio.to_thread(response["Body"].read)
        except ClientError as error:
            if self._error_code(error) in NOT_FOUND_CODES:
                raise ObjectStorageNotFound(
                    "Die angeforderte Objektversion wurde nicht gefunden."
                ) from error
            raise self._unavailable("Objektinhalt ist nicht erreichbar.") from error
        except (BotoCoreError, OSError) as error:
            raise self._unavailable("Objektinhalt ist nicht erreichbar.") from error
        metadata = {
            str(key).casefold(): str(value)
            for key, value in dict(response.get("Metadata", {})).items()
        }
        stored = StoredObject(
            location=ObjectLocation(
                bucket=location.bucket,
                key=location.key,
                version_id=self._version_id(response),
            ),
            media_type=str(response.get("ContentType", "application/octet-stream")),
            size_bytes=int(response.get("ContentLength", len(content))),
            sha256=metadata.get("sha256", ""),
            metadata={key: value for key, value in metadata.items() if key != "sha256"},
        )
        digest = hashlib.sha256(content).hexdigest()
        if digest != stored.sha256:
            raise ObjectStorageIntegrityError(
                "Der gelesene Objektinhalt verletzt seine SHA-256-Prüfsumme."
            )
        return RetrievedObject(stored=stored, content=content)

    async def protected_download_url(
        self,
        location: ObjectLocation,
        *,
        expires_in: timedelta,
    ) -> str:
        self._require_bucket(location)
        if not location.version_id:
            raise ObjectStorageIntegrityError(
                "Eine Download-URL benötigt eine exakte Version-ID."
            )
        seconds = int(expires_in.total_seconds())
        if seconds < 1 or seconds > 900:
            raise ValueError("Download-URLs müssen zwischen 1 und 900 Sekunden gelten.")
        try:
            return str(
                await asyncio.to_thread(
                    self._client.generate_presigned_url,
                    "get_object",
                    Params=self._object_parameters(location),
                    ExpiresIn=seconds,
                )
            )
        except (BotoCoreError, ClientError) as error:
            raise self._unavailable(
                "Geschützte Download-URL konnte nicht erzeugt werden."
            ) from error

    async def delete(
        self,
        location: ObjectLocation,
        *,
        authorization: ObjectDeletionAuthorization,
    ) -> None:
        del authorization
        self._require_bucket(location)
        if not location.version_id:
            raise ObjectStorageIntegrityError(
                "Kontrollierte Löschung benötigt eine exakte Version-ID."
            )
        try:
            await asyncio.to_thread(
                self._client.delete_object,
                **self._object_parameters(location),
            )
        except (BotoCoreError, ClientError) as error:
            raise self._unavailable(
                "Objektversion konnte nicht gelöscht werden."
            ) from error
        if await self.head(location) is not None:
            raise ObjectStorageIntegrityError(
                "Die kontrolliert gelöschte Objektversion ist weiterhin vorhanden."
            )

    @staticmethod
    def _require_same(existing: StoredObject, write: ObjectWrite) -> StoredObject:
        if (
            existing.sha256 != write.sha256
            or existing.size_bytes != len(write.content)
            or existing.media_type != write.media_type
        ):
            raise ObjectStorageConflict(
                "Der unveränderliche Object Key enthält bereits andere Bytes."
            )
        return existing

    def _require_bucket(self, location: ObjectLocation) -> None:
        if location.bucket != self._bucket:
            raise ObjectStorageConflict(
                "Der Speicherzugriff gehört nicht zum konfigurierten Bucket."
            )

    @staticmethod
    def _version_id(response: dict[str, Any]) -> str:
        version_id = response.get("VersionId")
        if not isinstance(version_id, str) or not version_id or version_id == "null":
            raise ObjectStorageIntegrityError(
                "Der S3-Endpunkt lieferte keine unveränderliche Version-ID."
            )
        return version_id

    @staticmethod
    def _error_code(error: ClientError) -> str:
        code = error.response.get("Error", {}).get("Code")
        if code is not None:
            return str(code)
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return str(status)

    @staticmethod
    def _object_parameters(location: ObjectLocation) -> dict[str, str]:
        parameters = {"Bucket": location.bucket, "Key": location.key}
        if location.version_id is not None:
            parameters["VersionId"] = location.version_id
        return parameters

    @staticmethod
    def _unavailable(message: str) -> ObjectStorageUnavailable:
        return ObjectStorageUnavailable(message)
