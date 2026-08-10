"""data.binance.vision 공개 아카이브 카탈로그 조사 — 읽기 전용 진단 스크립트.

바이낸스는 spot/futures(um·cm)/option 히스토리를 S3 버킷(data.binance.vision)에 공개한다.
이 스크립트는 (1) 어떤 데이터 타입이 존재하는지 트리 탐색, (2) 특정 데이터셋의 실제 커버리지
(첫/마지막 파일, 개수), (3) 샘플 1일치 다운로드 후 스키마·행수를 출력한다.

버킷은 익명 접근 가능하며 S3 REST GET Bucket(v1) 형식이라 marker 페이지네이션이 필요하다
(max-keys 상한 1000 — 이걸 놓치면 "마지막 파일"을 오판한다).

DB·트레이딩과 무관. 2026-08-11 전수 감사(docs/arena/research/binance-data-catalog-audit-20260811.md)
재현용.

사용:
    .venv/bin/python3 scripts/analysis/binance_archive_catalog.py tree data/futures/um/daily/
    .venv/bin/python3 scripts/analysis/binance_archive_catalog.py range \\
        data/futures/um/daily/metrics/BTCUSDT/ data/option/daily/BVOLIndex/BTCBVOLUSDT/
    .venv/bin/python3 scripts/analysis/binance_archive_catalog.py sample \\
        data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2026-08-08.zip
"""

from __future__ import annotations

import io
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

LIST_BASE = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DOWNLOAD_BASE = "https://data.binance.vision"
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


def _get(params: dict[str, str]) -> ET.Element:
    query = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{LIST_BASE}?{query}", timeout=30) as response:
        return ET.fromstring(response.read())


def list_prefixes(prefix: str) -> list[str]:
    """prefix 바로 아래 '디렉터리'(CommonPrefixes)만 나열."""
    root = _get({"delimiter": "/", "prefix": prefix, "max-keys": "1000"})
    return [
        node.findtext(NS + "Prefix")
        for node in root.findall(NS + "CommonPrefixes")
        if node.findtext(NS + "Prefix") not in (None, prefix)
    ]


def list_keys(prefix: str) -> list[str]:
    """prefix 아래 전체 키를 marker 페이지네이션으로 수집(.CHECKSUM 제외)."""
    marker = ""
    keys: list[str] = []
    while True:
        root = _get({"prefix": prefix, "max-keys": "1000", "marker": marker})
        page = [node.findtext(NS + "Key") for node in root.findall(NS + "Contents")]
        if not page:
            break
        keys.extend(key for key in page if key and not key.endswith("CHECKSUM"))
        if root.findtext(NS + "IsTruncated") == "true":
            marker = page[-1] or ""
        else:
            break
    return keys


def cmd_tree(prefix: str, depth: int = 1, _indent: int = 0) -> None:
    for child in list_prefixes(prefix):
        print("  " * _indent + child.rstrip("/").split("/")[-1] + "/")
        if depth > 1:
            cmd_tree(child, depth - 1, _indent + 1)


def cmd_range(prefixes: list[str]) -> None:
    for prefix in prefixes:
        keys = list_keys(prefix)
        if not keys:
            print(f"{prefix}: EMPTY")
            continue
        print(
            f"{prefix}: n={len(keys)} "
            f"first={keys[0].rsplit('/', 1)[-1]} last={keys[-1].rsplit('/', 1)[-1]}"
        )


def cmd_sample(key: str, head_rows: int = 3) -> None:
    with urllib.request.urlopen(f"{DOWNLOAD_BASE}/{key}", timeout=60) as response:
        payload = response.read()
    print(f"{key}  ({len(payload):,} bytes compressed)")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for name in archive.namelist():
            text = archive.read(name).decode("utf-8", errors="replace")
            lines = text.splitlines()
            print(f"-- {name}: {len(lines)} lines")
            for line in lines[:head_rows]:
                print(f"   {line}")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    command, args = argv[0], argv[1:]
    if command == "tree":
        cmd_tree(args[0], depth=int(args[1]) if len(args) > 1 else 1)
    elif command == "range":
        cmd_range(args)
    elif command == "sample":
        cmd_sample(args[0])
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
