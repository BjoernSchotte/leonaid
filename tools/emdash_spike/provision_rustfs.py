"""Operator-only native RustFS IAM provisioning; never pass root keys to the CMS."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from botocore.exceptions import ClientError
import boto3
from botocore.config import Config


class ProvisionError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


class RustfsAdmin:
    def __init__(self, endpoint: str, access: str, secret: str) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.credentials = Credentials(access, secret)

    def request(
        self,
        method: str,
        operation: str,
        *,
        query: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        allow_missing: bool = False,
    ) -> Any:
        url = f"{self.endpoint}/rustfs/admin/v3/{operation}"
        if query:
            url += "?" + urlencode(query)
        body = (
            json.dumps(payload, separators=(",", ":")).encode()
            if payload is not None
            else b""
        )
        signed = AWSRequest(
            method=method,
            url=url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-amz-content-sha256": hashlib.sha256(body).hexdigest(),
            },
        )
        SigV4Auth(self.credentials, "s3", "us-east-1").add_auth(signed)
        request = Request(url, data=body, headers=dict(signed.headers), method=method)
        try:
            with build_opener(NoRedirect).open(request, timeout=10) as response:
                content = response.read()
                return json.loads(content) if content else None
        except HTTPError as error:
            if allow_missing and error.code == 404:
                return None
            # Never include signed headers, response bodies or credentials.
            raise ProvisionError(
                f"admin operation {operation} returned {error.code}"
            ) from None


def media_policy(bucket: str) -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
                "Resource": [f"arn:aws:s3:::{bucket}"],
            },
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                "Resource": [f"arn:aws:s3:::{bucket}/*"],
            },
        ],
    }


def provision_media_user(
    admin: RustfsAdmin, access: str, secret: str, bucket: str
) -> None:
    if access == admin.credentials.access_key or len(secret) < 32:
        raise ProvisionError("unsafe CMS credentials")
    if access != "leonaid-emdash" or bucket != "emdash-media":
        raise ProvisionError("unexpected CMS namespace")
    policy_name = "leonaid-emdash-media"
    existing = admin.request(
        "GET", "user-info", query={"accessKey": access}, allow_missing=True
    )
    if existing is not None:
        if existing.get("policyName") != policy_name or existing.get("memberOf"):
            raise ProvisionError("existing CMS user requires policy/group review")
    policies = admin.request("GET", "list-canned-policies")
    if not isinstance(policies, dict) or "readwrite" not in policies:
        raise ProvisionError("unexpected policy inventory")
    policy = policies.get(policy_name)
    if policy is not None:
        document = policy.get("policy", policy)
        if isinstance(document, str):
            document = json.loads(document)
        if document != media_policy(bucket):
            raise ProvisionError("existing CMS policy requires review")
    else:
        admin.request(
            "PUT",
            "add-canned-policy",
            query={"name": policy_name},
            payload=media_policy(bucket),
        )
    admin.request(
        "PUT",
        "add-user",
        query={"accessKey": access},
        payload={"secretKey": secret, "status": "enabled"},
    )
    admin.request(
        "PUT",
        "set-user-or-group-policy",
        query={
            "policyName": policy_name,
            "userOrGroup": access,
            "isGroup": "false",
        },
    )


def provision_media(admin: RustfsAdmin, s3: Any, access: str, secret: str) -> None:
    """Create only the dedicated bucket; never overwrite an existing public policy."""
    try:
        s3.create_bucket(Bucket="emdash-media")
    except ClientError as error:
        if error.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
            raise ProvisionError("CMS bucket creation refused") from None
    try:
        s3.get_bucket_policy(Bucket="emdash-media")
    except ClientError as error:
        if error.response["Error"]["Code"] != "NoSuchBucketPolicy":
            raise ProvisionError("CMS bucket policy inspection failed") from None
    else:
        raise ProvisionError("existing CMS bucket policy requires review")
    provision_media_user(admin, access, secret, "emdash-media")


def main() -> None:
    endpoint = os.environ["RUSTFS_ENDPOINT_URL"]
    root_access = os.environ["RUSTFS_ACCESS_KEY"]
    root_secret = os.environ["RUSTFS_SECRET_KEY"]
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=root_access,
        aws_secret_access_key=root_secret,
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    provision_media(
        RustfsAdmin(endpoint, root_access, root_secret),
        s3,
        os.environ["CMS_S3_ACCESS_KEY_ID"],
        os.environ["CMS_S3_SECRET_ACCESS_KEY"],
    )
    print("emdash-rustfs: OK: private bucket and scoped IAM user provisioned")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Credential-bearing request/response details must stay out of logs.
        raise SystemExit(
            "emdash-rustfs: FAILED: review target and existing policy state privately"
        ) from None
