#!/usr/bin/env python3
# verify-bootstrap.py — throw away after use
import boto3
from botocore.config import Config

ENDPOINT   = "http://localhost:3900"
ACCESS_KEY = "GK0893c4d093555bdad95ab421"
SECRET_KEY = "9fef63d9e45a24f12ddaef254a4ee556c00583429830511c3d6fae04d141b32e"
BUCKET     = "vault"

s3 = boto3.client(
    "s3",
    endpoint_url=ENDPOINT,
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
    region_name="garage",
    config=Config(s3={"addressing_style": "path"}),
)

digests = {
    "forge-base:bootstrap":  "bcea4985f2cd2feb109fc277fa5e76b99b805cdf90e78cf8ddc0150d113a3bc0",
    "forge-tools:bootstrap": "d767f728468f7cd66ebd544a98aab2f79cb0869ae67d6e16c1bf2fb0b50d18d2",
}

for tag, digest in digests.items():
    # Check blob
    blob = s3.head_object(Bucket=BUCKET, Key=f"blobs/{digest}")
    size = blob["ContentLength"]
    # Check name tag
    name = s3.get_object(Bucket=BUCKET, Key=f"names/{tag}")
    print(f"{tag}")
    print(f"  blob:  {size / 1024 / 1024:.1f} MB  ✓")
    print(f"  tag:   ✓")
