#!/usr/bin/env python3
"""필수 인증정보 검증 스크립트.

Sentiment-Join 파이프라인 실행 전에 필요한 모든 크레덴셜을 검증합니다.
사용:
    python scripts/validate_credentials.py [--verbose]
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from morning_brief.r2_env import load_public_r2_env  # noqa: E402

COLOR_RESET = "\033[0m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED = "\033[91m"


@dataclass
class CredentialResult:
    name: str
    status: str  # "ok", "warning", "error"
    message: str
    details: str = ""


class CredentialValidator:
    """인증정보 검증 클래스."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results: list[CredentialResult] = []

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    def _test_r2(self) -> CredentialResult:
        """R2 크레덴셜 검증."""
        r2_env = load_public_r2_env()
        endpoint = r2_env.s3_endpoint
        access_key = r2_env.access_key_id
        secret_key = r2_env.secret_access_key
        bucket = r2_env.public_bucket
        base_url = r2_env.base_url

        missing = []
        if not endpoint:
            missing.append("R2_S3_ENDPOINT")
        if not access_key:
            missing.append("R2_ACCESS_KEY_ID")
        if not secret_key:
            missing.append("R2_SECRET_ACCESS_KEY")
        if not bucket:
            missing.append("R2_PUBLIC_BUCKET")
        if not base_url:
            missing.append("NEXT_PUBLIC_R2_BASE_URL")

        if missing:
            return CredentialResult(
                name="R2 (Cloudflare)",
                status="error",
                message=f"필수 환경변수 {len(missing)}개 누락",
                details=", ".join(missing),
            )

        # 기본 포맷 검증
        if not endpoint.startswith("https://"):
            return CredentialResult(
                name="R2 (Cloudflare)",
                status="error",
                message="R2_S3_ENDPOINT는 https://로 시작해야 함",
            )

        self._log("  ✓ R2 환경변수 5개 모두 설정됨")
        return CredentialResult(
            name="R2 (Cloudflare)",
            status="ok",
            message="설정됨 (5/5)",
            details=f"bucket={bucket}, endpoint={endpoint[:50]}...",
        )

    def _test_kis(self) -> CredentialResult:
        """KIS 크레덴셜 검증 (선택)."""
        app_key = os.getenv("KIS_APP_KEY", "").strip()
        app_secret = os.getenv("KIS_APP_SECRET", "").strip()

        if not app_key or not app_secret:
            return CredentialResult(
                name="KIS (한국투자)",
                status="warning",
                message="설정 안 됨 (yfinance로 fallback)",
                details="KIS_APP_KEY, KIS_APP_SECRET 권장",
            )

        # 기본 형식 검증
        if len(app_key) < 10 or len(app_secret) < 10:
            return CredentialResult(
                name="KIS (한국투자)",
                status="error",
                message="KIS 자격증명 형식 오류 (너무 짧음)",
            )

        self._log("  ✓ KIS 환경변수 2개 설정됨")
        return CredentialResult(
            name="KIS (한국투자)",
            status="ok",
            message="설정됨 (2/2)",
            details=f"app_key={app_key[:10]}***",
        )

    def _test_supabase(self) -> CredentialResult:
        """Supabase 크레덴셜 검증 (권장)."""
        url = os.getenv("SUPABASE_URL", "").strip()
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

        if not url or not key:
            return CredentialResult(
                name="Supabase (ETF)",
                status="warning",
                message="설정 안 됨 (ETF 데이터 NaN)",
                details="SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY 권장",
            )

        # 기본 형식 검증
        if not (url.endswith(".supabase.co") or url.endswith(".supabase.com")):
            return CredentialResult(
                name="Supabase (ETF)",
                status="error",
                message="SUPABASE_URL 형식 오류 (.supabase.co 또는 .supabase.com로 끝나야 함)",
            )

        if not key.startswith("eyJ"):  # JWT 토큰 시작
            return CredentialResult(
                name="Supabase (ETF)",
                status="warning",
                message="SUPABASE_SERVICE_ROLE_KEY가 JWT 형식으로 보이지 않음",
            )

        self._log("  ✓ Supabase 환경변수 2개 설정됨")
        return CredentialResult(
            name="Supabase (ETF)",
            status="ok",
            message="설정됨 (2/2)",
            details=f"url={url}",
        )

    def _test_binance(self) -> CredentialResult:
        """Binance API Key 검증 (선택)."""
        api_key = os.getenv("SENTIMENT_JOIN_BINANCE_KEY", "").strip()

        if not api_key:
            return CredentialResult(
                name="Binance (Futures)",
                status="warning",
                message="설정 안 됨 (공개 API 사용)",
                details="SENTIMENT_JOIN_BINANCE_KEY 선택",
            )

        # 기본 형식 검증
        if len(api_key) < 20:
            return CredentialResult(
                name="Binance (Futures)",
                status="error",
                message="Binance API Key 형식 오류 (너무 짧음)",
            )

        # API 테스트
        try:
            response = requests.get(
                "https://api.binance.com/api/v3/exchangeInfo",
                headers={"X-MBX-APIKEY": api_key},
                timeout=5,
            )
            if response.status_code == 200:
                self._log("  ✓ Binance API Key 유효함")
                return CredentialResult(
                    name="Binance (Futures)",
                    status="ok",
                    message="검증됨",
                    details=f"key={api_key[:10]}***",
                )
            elif response.status_code == 401:
                return CredentialResult(
                    name="Binance (Futures)",
                    status="error",
                    message="Binance API Key 인증 실패 (401)",
                )
            else:
                self._log(f"  ⚠ Binance API 응답: {response.status_code}")
                return CredentialResult(
                    name="Binance (Futures)",
                    status="warning",
                    message=f"Binance API 상태 이상 ({response.status_code})",
                )
        except requests.exceptions.RequestException as e:
            self._log(f"  ⚠ Binance API 연결 실패: {e}")
            return CredentialResult(
                name="Binance (Futures)",
                status="warning",
                message="API 연결 실패 (네트워크 이슈 가능)",
            )

    def _test_alpaca(self) -> CredentialResult:
        """Alpaca 크레덴셜 검증 (백필 스크립트용, 선택)."""
        key_id = os.getenv("ALPACA_API_KEY_ID", "").strip()
        key_secret = os.getenv("ALPACA_API_SECRET_KEY", "").strip()

        if not key_id or not key_secret:
            return CredentialResult(
                name="Alpaca (백필 뉴스)",
                status="warning",
                message="설정 안 됨 (CoinDesk만 사용)",
                details="ALPACA_API_KEY_ID, ALPACA_API_SECRET_KEY 선택",
            )

        if len(key_id) < 5 or len(key_secret) < 5:
            return CredentialResult(
                name="Alpaca (백필 뉴스)",
                status="error",
                message="Alpaca 자격증명 형식 오류",
            )

        self._log("  ✓ Alpaca 환경변수 2개 설정됨")
        return CredentialResult(
            name="Alpaca (백필 뉴스)",
            status="ok",
            message="설정됨 (2/2)",
            details=f"key_id={key_id[:5]}***",
        )

    def _test_lambda_arn(self) -> CredentialResult:
        """AWS Lambda ARN 검증 (선택, GitHub Actions 451 우회용)."""
        arn = os.getenv("FUTURES_LAMBDA_ARN", "").strip()

        if not arn:
            return CredentialResult(
                name="AWS Lambda (Futures)",
                status="warning",
                message="설정 안 됨 (Bybit fallback)",
                details="FUTURES_LAMBDA_ARN 선택 (GitHub Actions 451 우회용)",
            )

        # ARN 형식 검증
        if not arn.startswith("arn:aws:lambda:"):
            return CredentialResult(
                name="AWS Lambda (Futures)",
                status="error",
                message="FUTURES_LAMBDA_ARN 형식 오류 (arn:aws:lambda:로 시작해야 함)",
            )

        if "binance-futures" not in arn.lower():
            return CredentialResult(
                name="AWS Lambda (Futures)",
                status="warning",
                message="FUTURES_LAMBDA_ARN에 'binance-futures' 포함 권장",
            )

        self._log("  ✓ AWS Lambda ARN 형식 유효함")
        return CredentialResult(
            name="AWS Lambda (Futures)",
            status="ok",
            message="설정됨",
            details=f"arn={arn[:50]}...",
        )

    def validate_all(self) -> int:
        """모든 크레덴셜 검증."""
        print("\n" + "=" * 60)
        print("🔐 필수 인증정보 검증")
        print("=" * 60 + "\n")

        self.results = [
            self._test_r2(),
            self._test_kis(),
            self._test_supabase(),
            self._test_binance(),
            self._test_alpaca(),
            self._test_lambda_arn(),
        ]

        # 결과 출력
        ok_count = 0
        warning_count = 0
        error_count = 0

        for result in self.results:
            if result.status == "ok":
                color = COLOR_GREEN
                symbol = "✅"
                ok_count += 1
            elif result.status == "warning":
                color = COLOR_YELLOW
                symbol = "⚠️ "
                warning_count += 1
            else:  # error
                color = COLOR_RED
                symbol = "❌"
                error_count += 1

            print(f"{color}{symbol} {result.name:<25} {result.message:<30}{COLOR_RESET}")
            if result.details:
                print(f"   {result.details}\n")

        # 요약
        print("\n" + "-" * 60)
        print(
            f"{COLOR_GREEN}✅ 정상: {ok_count}{COLOR_RESET} | "
            + f"{COLOR_YELLOW}⚠️  경고: {warning_count}{COLOR_RESET} | "
            + f"{COLOR_RED}❌ 오류: {error_count}{COLOR_RESET}"
        )
        print("-" * 60 + "\n")

        # 상세 분석
        if error_count == 0:
            print("🎯 필수 R2 정보 설정 완료! Sentiment-Join 파이프라인 실행 가능합니다.\n")
            return 0
        else:
            print(f"🛑 오류 {error_count}개를 수정해야 합니다.\n")
            return 1


class BackfillCredentialValidator:
    """Backfill 스크립트용 인증정보 검증."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results: list[CredentialResult] = []

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    def _test_r2(self) -> CredentialResult:
        """R2 크레덴셜 검증 (백필 업로드용)."""
        r2_env = load_public_r2_env()
        endpoint = r2_env.s3_endpoint
        access_key = r2_env.access_key_id
        secret_key = r2_env.secret_access_key
        bucket = r2_env.public_bucket

        missing = []
        if not endpoint:
            missing.append("R2_S3_ENDPOINT")
        if not access_key:
            missing.append("R2_ACCESS_KEY_ID")
        if not secret_key:
            missing.append("R2_SECRET_ACCESS_KEY")
        if not bucket:
            missing.append("R2_PUBLIC_BUCKET")

        if missing:
            return CredentialResult(
                name="R2 (백필 업로드)",
                status="error",
                message=f"필수 환경변수 {len(missing)}개 누락",
                details=", ".join(missing),
            )

        self._log("  ✓ R2 환경변수 4개 모두 설정됨")
        return CredentialResult(
            name="R2 (백필 업로드)",
            status="ok",
            message="설정됨 (4/4)",
            details=f"bucket={bucket}",
        )

    def _test_alpaca(self) -> CredentialResult:
        """Alpaca 크레덴셜 검증 (선택)."""
        key_id = os.getenv("ALPACA_API_KEY_ID", "").strip()
        key_secret = os.getenv("ALPACA_API_SECRET_KEY", "").strip()

        if not key_id or not key_secret:
            return CredentialResult(
                name="Alpaca (뉴스)",
                status="warning",
                message="설정 안 됨 (CoinDesk만 사용)",
                details="ALPACA_API_KEY_ID, ALPACA_API_SECRET_KEY 선택",
            )

        if len(key_id) < 5 or len(key_secret) < 5:
            return CredentialResult(
                name="Alpaca (뉴스)",
                status="error",
                message="Alpaca 자격증명 형식 오류",
            )

        self._log("  ✓ Alpaca 환경변수 2개 설정됨")
        return CredentialResult(
            name="Alpaca (뉴스)",
            status="ok",
            message="설정됨 (2/2)",
            details=f"key_id={key_id[:5]}***",
        )

    def validate_all(self) -> int:
        """Backfill 크레덴셜 검증."""
        print("\n" + "=" * 60)
        print("🔐 Backfill 스크립트 인증정보 검증")
        print("=" * 60 + "\n")

        self.results = [
            self._test_r2(),
            self._test_alpaca(),
        ]

        ok_count = 0
        warning_count = 0
        error_count = 0

        for result in self.results:
            if result.status == "ok":
                color = COLOR_GREEN
                symbol = "✅"
                ok_count += 1
            elif result.status == "warning":
                color = COLOR_YELLOW
                symbol = "⚠️ "
                warning_count += 1
            else:
                color = COLOR_RED
                symbol = "❌"
                error_count += 1

            print(f"{color}{symbol} {result.name:<25} {result.message:<30}{COLOR_RESET}")
            if result.details:
                print(f"   {result.details}\n")

        print("\n" + "-" * 60)
        print(
            f"{COLOR_GREEN}✅ 정상: {ok_count}{COLOR_RESET} | "
            + f"{COLOR_YELLOW}⚠️  경고: {warning_count}{COLOR_RESET} | "
            + f"{COLOR_RED}❌ 오류: {error_count}{COLOR_RESET}"
        )
        print("-" * 60 + "\n")

        if error_count == 0:
            print("🎯 필수 R2 정보 설정 완료! Backfill 실행 가능합니다.\n")
            return 0
        else:
            print(f"🛑 오류 {error_count}개를 수정해야 합니다.\n")
            return 1


def main() -> int:
    mode = "sentiment-join"
    for arg in sys.argv[1:]:
        if arg in ("--backfill", "--sentiment-join"):
            mode = arg.lstrip("-")
            break

    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    if mode == "backfill":
        validator = BackfillCredentialValidator(verbose=verbose)
    else:
        validator = CredentialValidator(verbose=verbose)

    return validator.validate_all()


if __name__ == "__main__":
    sys.exit(main())
