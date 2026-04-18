from __future__ import annotations

import os
from dataclasses import dataclass


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


@dataclass(frozen=True)
class PublicR2Env:
    public_bucket: str
    s3_endpoint: str
    access_key_id: str
    secret_access_key: str
    base_url: str


def load_public_r2_env() -> PublicR2Env:
    return PublicR2Env(
        public_bucket=_first_env("R2_PUBLIC_BUCKET", "R2_BUCKET_NAME"),
        s3_endpoint=_first_env("R2_S3_ENDPOINT", "R2_ENDPOINT_URL"),
        access_key_id=os.getenv("R2_ACCESS_KEY_ID", "").strip(),
        secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY", "").strip(),
        base_url=_first_env("NEXT_PUBLIC_R2_BASE_URL", "R2_BASE_URL"),
    )


__all__ = ["PublicR2Env", "load_public_r2_env"]
