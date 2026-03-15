import boto3
import blake3
import json
from botocore.config import Config
from botocore.exceptions import ClientError
from pathlib import Path

CHUNK = 1024 * 1024  # 1MB

class GarageStore:
    def __init__(self, cfg):
        self.bucket = cfg.bucket
        self.s3 = boto3.client(
            "s3",
            endpoint_url=cfg.endpoint,
            aws_access_key_id=cfg.access_key,
            aws_secret_access_key=cfg.secret_key,
            region_name=cfg.region,
            config=Config(s3={"addressing_style": "path"}),
        )

    # ── Blob operations ──────────────────────────────────────────

    def blob_exists(self, digest: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=f"blobs/{digest}")
            return True
        except ClientError:
            return False

    def blob_size(self, digest: str) -> int | None:
        try:
            r = self.s3.head_object(Bucket=self.bucket, Key=f"blobs/{digest}")
            return r["ContentLength"]
        except ClientError:
            return None

    def put_blob(self, digest: str, source_path: Path) -> str:
        """
        Upload a blob. Verifies digest matches content.
        Idempotent — no-op if already present.
        Returns digest.
        """
        if self.blob_exists(digest):
            return digest

        actual = _hash_file(source_path)
        if actual != digest:
            raise ValueError(f"Digest mismatch: expected {digest}, got {actual}")

        self.s3.upload_file(
            str(source_path),
            self.bucket,
            f"blobs/{digest}",
            ExtraArgs={"Metadata": {"blake3": digest}},
        )
        return digest

    def put_blob_stream(self, stream, length: int) -> str:
        """
        Ingest a streaming upload, compute digest on the fly.
        Stores to a staging key first, then moves to final key.
        Returns actual digest.
        """
        import tempfile, os
        h = blake3.blake3()

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
            while chunk := stream.read(CHUNK):
                h.update(chunk)
                tmp.write(chunk)

        digest = h.hexdigest()

        if not self.blob_exists(digest):
            self.s3.upload_file(
                str(tmp_path),
                self.bucket,
                f"blobs/{digest}",
                ExtraArgs={"Metadata": {"blake3": digest}},
            )

        tmp_path.unlink()
        return digest

    def get_blob_stream(self, digest: str):
        """
        Returns a streaming response body or raises KeyError.
        """
        try:
            r = self.s3.get_object(Bucket=self.bucket, Key=f"blobs/{digest}")
            return r["Body"]
        except ClientError:
            raise KeyError(f"Blob not found: {digest}")
        
def list_blobs(self) -> list[dict]:
    result = []
    paginator = self.s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=self.bucket, Prefix="blobs/"):
        for obj in page.get("Contents", []):
            digest = obj["Key"].removeprefix("blobs/")
            result.append({"digest": digest, "size": obj["Size"]})
    return result

    # ── Name operations ──────────────────────────────────────────

    def get_name(self, name: str) -> dict:
        """Returns tag record or raises KeyError."""
        try:
            r = self.s3.get_object(Bucket=self.bucket, Key=f"names/{name}")
            return json.loads(r["Body"].read())
        except ClientError:
            raise KeyError(f"Name not found: {name}")

    def put_name(self, name: str, digest: str, protected: bool = False, note: str = "", force: bool = False) -> dict:
        """
        Create or update a name→digest tag.
        Raises PermissionError if tag exists and is protected.
        """
        try:
            existing = self.get_name(name)
            if existing.get("protected") and not force:
                raise PermissionError(f"Tag '{name}' is protected — use vaultctl name retag")
        except KeyError:
            pass  # new tag, fine

        record = {
            "digest":    digest,
            "protected": protected,
            "note":      note,
        }
        self.s3.put_object(
            Bucket=self.bucket,
            Key=f"names/{name}",
            Body=json.dumps(record).encode(),
            ContentType="application/json",
        )
        return record
    
def list_names(self) -> list[dict]:
    result = []
    paginator = self.s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=self.bucket, Prefix="names/"):
        for obj in page.get("Contents", []):
            name = obj["Key"].removeprefix("names/")
            try:
                record = self.get_name(name)
                record["name"] = name
                result.append(record)
            except KeyError:
                pass
    return result            

    # ── Health ───────────────────────────────────────────────────

    def ping(self) -> bool:
        try:
            self.s3.head_bucket(Bucket=self.bucket)
            return True
        except ClientError:
            return False


def _hash_file(path: Path) -> str:
    h = blake3.blake3()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()
