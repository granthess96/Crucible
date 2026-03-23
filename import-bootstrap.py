#!/usr/bin/env python3
# import-bootstrap.py
import boto3
import blake3
import json
from botocore.config import Config
from pathlib import Path

ENDPOINT   = "http://localhost:3900"
ACCESS_KEY = "GK0893c4d093555bdad95ab421"
SECRET_KEY = "9fef63d9e45a24f12ddaef254a4ee556c00583429830511c3d6fae04d141b32e"
BUCKET     = "vault"
CHUNK      = 1024 * 1024  # 1MB

s3 = boto3.client(
    "s3",
    endpoint_url=ENDPOINT,
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
    region_name="garage",
    config=Config(s3={"addressing_style": "path"}),
)

def hash_file(path: Path) -> str:
    h = blake3.blake3()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()

def store(path: Path, tag: str) -> str:
    print(f"\n{path.name}")
    print(f"  Hashing...")
    digest = hash_file(path)
    print(f"  Digest:  {digest}")

    key = f"blobs/{digest}"
    try:
        s3.head_object(Bucket=BUCKET, Key=key)
        print(f"  Already in Vault — skipping upload")
    except s3.exceptions.ClientError:
        print(f"  Uploading {path.stat().st_size / 1024 / 1024:.1f} MB...")
        s3.upload_file(
            str(path), BUCKET, key,
            ExtraArgs={"Metadata": {"blake3": digest, "kind": "squashfs"}},
        )
        print(f"  Stored.")

    tag_key = f"names/{tag}"
    s3.put_object(
        Bucket=BUCKET,
        Key=tag_key,
        Body=json.dumps({
            "digest":    digest,
            "kind":      "squashfs",
            "protected": True,
            "note":      "manually built bootstrap image — do not retag without cause",
        }).encode(),
        ContentType="application/json",
    )
    print(f"  Tagged:  {tag}")
    return digest

if __name__ == "__main__":
    base  = store(Path("images/base.sqsh"),  "forge-base:bootstrap_from_source")
    tools = store(Path("images/tools.sqsh"), "forge-tools:bootstrap")

    print("\n\n=== Add these to forge.toml [forge] section ===")
    print(f'base_image = "vault:blake3:{base}"')
    print(f'toolchain  = "vault:blake3:{tools}"')
