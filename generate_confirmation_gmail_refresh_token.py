from __future__ import annotations

import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

DEFAULT_SCOPES = ("https://www.googleapis.com/auth/gmail.send",)

# 로컬에서만 잠깐 채워 넣고 실행하세요. 실제 비밀값은 커밋하지 마세요.
CLIENT_ID = ""
CLIENT_SECRET = ""


def _read_value(env_name: str, inline_value: str, prompt_label: str) -> str:
    value = os.getenv(env_name, "").strip() or inline_value.strip()
    if value:
        return value

    try:
        return input(f"{prompt_label}: ").strip()
    except EOFError:
        return ""


def main() -> int:
    client_id = _read_value(
        "CONFIRMATION_GMAIL_CLIENT_ID",
        CLIENT_ID,
        "CONFIRMATION_GMAIL_CLIENT_ID",
    )
    client_secret = _read_value(
        "CONFIRMATION_GMAIL_CLIENT_SECRET",
        CLIENT_SECRET,
        "CONFIRMATION_GMAIL_CLIENT_SECRET",
    )

    if not client_id or not client_secret:
        print("ERROR: client id와 client secret이 필요합니다.", file=sys.stderr)
        return 1

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, list(DEFAULT_SCOPES))
    creds = flow.run_local_server(
        port=0,
        authorization_prompt_message="브라우저에서 Gmail 계정 승인을 완료해 주세요.",
        success_message="승인이 완료되었습니다. 터미널로 돌아가세요.",
        open_browser=True,
    )

    refresh_token = (creds.refresh_token or "").strip()
    if not refresh_token:
        print(
            "ERROR: refresh token이 비어 있습니다. 앱 권한 제거 후 다시 승인하거나 새 OAuth client를 사용해 주세요.",
            file=sys.stderr,
        )
        return 1

    print("\nCONFIRMATION_GMAIL_REFRESH_TOKEN")
    print(refresh_token)
    print("\n위 값을 GitHub Secret CONFIRMATION_GMAIL_REFRESH_TOKEN 에 등록하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
