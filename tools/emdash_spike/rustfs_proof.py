"""Real private-bucket and IAM negative tests against the pinned RustFS image."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import urlopen

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from tools.emdash_spike.provision_rustfs import (
    ProvisionError,
    RustfsAdmin,
    provision_media,
)


def main() -> None:
    endpoint = "http://rustfs:9000"
    root_access = os.environ["RUSTFS_ACCESS_KEY"]
    root_secret = os.environ["RUSTFS_SECRET_KEY"]
    config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "path"},
        retries={"max_attempts": 1},
    )
    root = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=root_access,
        aws_secret_access_key=root_secret,
        region_name="us-east-1",
        config=config,
    )
    admin = RustfsAdmin(endpoint, root_access, root_secret)
    if "--existing" in sys.argv:
        assert (
            root.get_object(Bucket="emdash-media", Key="retained.txt")["Body"].read()
            == b"retained"
        )
        assert (
            root.get_object(Bucket="core-private", Key="private.txt")["Body"].read()
            == b"core-private-data"
        )
        assert (
            admin.request("GET", "user-info", query={"accessKey": "leonaid-emdash"})
            is not None
        )
    else:
        root.create_bucket(Bucket="core-private")
        root.put_object(
            Bucket="core-private", Key="private.txt", Body=b"core-private-data"
        )
    access, secret = "leonaid-emdash", secrets.token_hex(32)
    provision_media(admin, root, access, secret)
    provision_media(admin, root, access, secret)
    subprocess.run(
        [sys.executable, "-m", "tools.emdash_spike.provision_rustfs"],
        env={
            **os.environ,
            "RUSTFS_ENDPOINT_URL": endpoint,
            "CMS_S3_ACCESS_KEY_ID": access,
            "CMS_S3_SECRET_ACCESS_KEY": secret,
        },
        check=True,
        timeout=30,
    )
    cms = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name="us-east-1",
        config=config,
    )
    cms.put_object(Bucket="emdash-media", Key="image.txt", Body=b"cms-media")
    assert (
        cms.get_object(Bucket="emdash-media", Key="image.txt")["Body"].read()
        == b"cms-media"
    )
    assert "image.txt" in {
        item["Key"] for item in cms.list_objects_v2(Bucket="emdash-media")["Contents"]
    }
    for operation, arguments in [
        (cms.get_object, {"Bucket": "core-private", "Key": "private.txt"}),
        (
            cms.put_object,
            {"Bucket": "core-private", "Key": "intrusion", "Body": b"denied"},
        ),
        (cms.list_objects_v2, {"Bucket": "core-private"}),
        (cms.delete_bucket, {"Bucket": "emdash-media"}),
    ]:
        try:
            operation(**arguments)
        except ClientError as error:
            assert error.response["ResponseMetadata"]["HTTPStatusCode"] == 403
        else:
            raise AssertionError("CMS credentials exceeded bucket permissions")
    try:
        RustfsAdmin(endpoint, access, secret).request("GET", "list-users")
    except ProvisionError as error:
        assert "403" in str(error)
    else:
        raise AssertionError("CMS credentials accessed IAM administration")
    try:
        urlopen(endpoint + "/emdash-media/image.txt", timeout=5)
    except HTTPError as error:
        assert error.code == 403
    else:
        raise AssertionError("CMS object is anonymously accessible")
    cms.delete_object(Bucket="emdash-media", Key="image.txt")
    cms.put_object(Bucket="emdash-media", Key="retained.txt", Body=b"retained")
    admin.request(
        "PUT",
        "set-user-or-group-policy",
        query={
            "policyName": "readonly",
            "userOrGroup": access,
            "isGroup": "false",
        },
    )
    try:
        provision_media(admin, root, access, secret)
    except ProvisionError:
        pass
    else:
        raise AssertionError("unexpected existing IAM binding was silently replaced")
    admin.request(
        "PUT",
        "set-user-or-group-policy",
        query={
            "policyName": "leonaid-emdash-media",
            "userOrGroup": access,
            "isGroup": "false",
        },
    )
    assert (
        root.get_object(Bucket="core-private", Key="private.txt")["Body"].read()
        == b"core-private-data"
    )
    print(
        "emdash-rustfs-proof: OK: private media, repeated IAM provisioning, own-bucket CRUD, denied cross-bucket/admin/anonymous access"
    )


if __name__ == "__main__":
    main()
