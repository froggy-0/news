from __future__ import annotations

import argparse
from pathlib import Path
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

DEFAULT_SCOPES = ("https://www.googleapis.com/auth/gmail.send",)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Gmail OAuth token.json from credentials.json"
    )
    parser.add_argument(
        "--credentials",
        default="credentials.json",
        help="Path to OAuth client credentials JSON (default: credentials.json)",
    )
    parser.add_argument(
        "--token",
        default="token.json",
        help="Output path for generated token file (default: token.json)",
    )
    parser.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        help="OAuth scope. Repeat for multiple scopes. Default is gmail.send only.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    credentials_path = Path(args.credentials).resolve()
    token_path = Path(args.token).resolve()
    scopes = args.scopes or list(DEFAULT_SCOPES)

    if not credentials_path.exists():
        print(f"ERROR: credentials file not found: {credentials_path}", file=sys.stderr)
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), scopes)
    creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")

    print(f"Created Gmail token: {token_path}")
    print(f"Scopes: {', '.join(scopes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
