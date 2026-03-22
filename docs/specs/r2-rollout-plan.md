# 공개 R2 단계적 도입 계획

## 요약

- 1차는 빠르게 붙이는 것이 목적입니다.
  - 공개 R2에는 `index.json`과 `briefs/YYYY-MM-DD.json`만 올립니다.
  - 같은 날짜 재실행 시 공개 JSON은 덮어씁니다.
  - 홈은 `index.json`의 최신 날짜를 읽어 해당 날짜 브리프를 표시합니다.
- 2차는 공개 브리프를 시간별로 보존합니다.
  - 공개 R2 경로를 `briefs/YYYY-MM-DD/HHMM.json`으로 확장합니다.
  - `/archive/[date]`는 시간 목록 페이지가 되고, 상세는 `/archive/[date]/[time]`로 분리합니다.
- 공개 프론트는 계속 정적 export를 유지합니다.
  - 백엔드가 R2 업로드
  - 프론트가 R2 JSON을 빌드 시 읽음
  - `frontend/out`을 Pages에 배포

## 인터페이스와 저장소 기준

### 공개 R2 파일 구조

1차:

```text
index.json
briefs/2026-03-21.json
briefs/2026-03-20.json
```

2차:

```text
index.json
briefs/2026-03-21/0800.json
briefs/2026-03-21/1230.json
briefs/2026-03-20/0800.json
```

### 공개 JSON 계약

- 브리프 본문 계약은 계속 [docs/specs/r2-json-contract.md](/Users/giwon/code/news/docs/specs/r2-json-contract.md) 기준

1차 `index.json`:

```json
{
  "dates": ["2026-03-21", "2026-03-20"],
  "updatedAt": "2026-03-21T00:18:00Z"
}
```

2차 `index.json` 확장:

```json
{
  "updatedAt": "2026-03-21T12:30:00Z",
  "dates": ["2026-03-21", "2026-03-20"],
  "latest": {
    "date": "2026-03-21",
    "time": "1230",
    "path": "briefs/2026-03-21/1230.json",
    "generatedAt": "2026-03-21T12:30:00Z"
  },
  "entriesByDate": [
    {
      "date": "2026-03-21",
      "runs": [
        {
          "time": "1230",
          "generatedAt": "2026-03-21T12:30:00Z",
          "path": "briefs/2026-03-21/1230.json",
          "quality": "ok",
          "headline": "오늘은 관망 국면입니다."
        },
        {
          "time": "0800",
          "generatedAt": "2026-03-21T08:00:00Z",
          "path": "briefs/2026-03-21/0800.json",
          "quality": "degraded",
          "headline": "오늘은 리스크 주의 국면입니다."
        }
      ]
    }
  ]
}
```

### 프론트 라우트 기준

1차:
- `/`
- `/archive`
- `/archive/[date]`

2차:
- `/` → `index.latest` 또는 최신 run
- `/archive`
- `/archive/[date]` → 날짜 아래 시간 목록
- `/archive/[date]/[time]` → 실제 상세

## 구현 변경

### 1차: 날짜당 1개 공개 JSON

#### 백엔드
- 파이프라인 끝에서 공개 serializer를 추가합니다.
  - 입력: 최종 `packet`, 최종 `briefing`, 실행 시각
  - 출력: `BriefData`
- serializer는 이메일용 원시 packet이 아니라 공개 계약만 만듭니다.
- 업로드 단계는 파이프라인 내부에서 직접 처리합니다.
  1. `briefs/YYYY-MM-DD.json` 생성
  2. R2 업로드
  3. 공개 prefix listing
  4. `index.json` 재생성 후 업로드
- `outputs/brief_*.md` 저장은 그대로 유지합니다.
- 내부 산출물은 기존 `outputs/`와 observability에 계속 남깁니다.

#### 프론트
- [frontend/lib/r2.ts](/Users/giwon/code/news/frontend/lib/r2.ts) 에서 `briefs/latest.json` 의존성을 제거합니다.
- 홈은 `fetchIndex()` 후 가장 최신 날짜를 골라 `fetchBriefByDate(date)`를 호출합니다.
- `generate-static-assets.mjs`도 `index.json` 최신 날짜 기준으로 RSS를 만듭니다.
- fixtures는 `latest.json` 중심이 아니라 날짜별 파일 중심으로 유지합니다.

#### GitHub Actions / 배포
- 현재 `morning-brief.yml` 뒤에 공개 JSON 업로드 step을 추가합니다.
- `Morning Market Brief` 하나의 workflow 안에서 공개 JSON 업로드 뒤 Pages 배포까지 끝냅니다. `main`은 production, 그 외 브랜치는 preview로 배포합니다.
- 별도 `frontend-pages.yml`은 수집 없이 프론트만 다시 배포하는 수동 workflow로 남기고, 자동 연동은 사용하지 않습니다.
- `frontend-pages.yml`은 `ref`, `preview/production`, optional preview branch alias를 입력받아 현재 공개 R2 JSON 기준으로 `frontend/out`만 다시 배포합니다.
- 1차는 같은 날짜 재실행 시 공개 브리프를 덮어씁니다.

### 2차: 시간별 버전 보존

#### 백엔드
- 공개 경로를 `briefs/YYYY-MM-DD/HHMM.json`으로 확장합니다.
- `HHMM`은 KST 기준으로 고정합니다.
- 같은 날짜 재실행 시 새 파일을 추가합니다.
- `index.json`은 `latest`, `entriesByDate`를 포함하도록 확장합니다.
- listing 기반으로 `index.json`을 항상 재생성합니다. 별도 DB는 두지 않습니다.

#### 프론트
- `BriefIndex` 타입과 parser를 확장합니다.
- 홈은 `index.latest.path`를 읽습니다.
- `/archive/[date]`는 시간 목록 페이지로 바꿉니다.
- 새 상세 route `/archive/[date]/[time]`를 추가합니다.
- 정적 경로 생성도 `entriesByDate[].runs[]` 기준으로 바꿉니다.

#### 문서
- 2차에 들어갈 때 [docs/specs/r2-json-contract.md](/Users/giwon/code/news/docs/specs/r2-json-contract.md) 와 [docs/specs/design.md](/Users/giwon/code/news/docs/specs/design.md) 를 같이 갱신합니다.

## GitHub Actions secrets / vars 기준

### Secrets

다음 값은 GitHub Actions `Secrets`로 저장합니다.

- `CLOUDFLARE_API_TOKEN`
  - 용도: Cloudflare Pages direct upload
- `R2_ACCESS_KEY_ID`
  - 용도: S3-compatible R2 업로드
- `R2_SECRET_ACCESS_KEY`
  - 용도: S3-compatible R2 업로드

### Variables

다음 값은 GitHub Actions `Variables`로 저장하는 것을 기본값으로 합니다.

- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_PAGES_PROJECT_NAME`
- `R2_PUBLIC_BUCKET`
- `R2_S3_ENDPOINT`
- `NEXT_PUBLIC_R2_BASE_URL`

선택:
- `R2_INTERNAL_BUCKET`
  - 내부 산출물도 별도 bucket으로 분리할 때만 추가

### endpoint 처리 기준

`R2_S3_ENDPOINT`는 완성된 endpoint URL 전체를 variable로 저장합니다. 런타임에서 account id와 jurisdiction를 조합하지 않습니다.

기본값:
- 일반: `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`
- EU jurisdiction: `https://<ACCOUNT_ID>.eu.r2.cloudflarestorage.com`
- FedRAMP: `https://<ACCOUNT_ID>.fedramp.r2.cloudflarestorage.com`

이 방식을 쓰는 이유:
- workflow와 Python 코드가 단순해짐
- jurisdiction 분기 로직을 코드에 넣지 않아도 됨
- bucket 이동이나 정책 변경 시 variable만 바꾸면 됨

### 공개 base URL 기준

`NEXT_PUBLIC_R2_BASE_URL`은 프론트가 읽는 공개 버킷의 HTTP base URL입니다.

예:
- `https://pub-brief.example.com`
- 또는 public bucket 도메인 / custom domain

중요:
- `R2_S3_ENDPOINT`와 `NEXT_PUBLIC_R2_BASE_URL`은 같은 값일 필요가 없습니다.
- 업로드는 S3 endpoint
- 프론트 fetch는 public HTTP base URL
- 둘을 분리하는 것이 맞습니다

### boto3 / S3 client 기준

- `endpoint_url = R2_S3_ENDPOINT`
- `aws_access_key_id = R2_ACCESS_KEY_ID`
- `aws_secret_access_key = R2_SECRET_ACCESS_KEY`
- `region_name = "auto"`

## 테스트 계획

### 1차
- serializer test
  - `packet + briefing -> BriefData` 검증
  - [docs/specs/r2-json-contract.md](/Users/giwon/code/news/docs/specs/r2-json-contract.md) 기준 필수 심볼 포함 확인
- uploader test
  - `briefs/YYYY-MM-DD.json` 업로드
  - `index.json` 재생성
- frontend test
  - 홈이 `index.json` 최신 날짜를 사용
  - `/archive`, `/archive/[date]` 정적 build 유지
- build test
  - `npm run build`
  - `frontend/out` 정상 생성

### 2차
- index parser test
  - `latest`, `entriesByDate` 파싱
- backend listing/index generation test
  - 같은 날짜 다중 run 정렬 확인
- frontend route test
  - `/archive/[date]` 시간 목록
  - `/archive/[date]/[time]` 상세
  - 홈이 `latest.path` 기준 최신본 표시

## 가정과 기본값

- 1차는 빠른 연결이 우선이므로 공개 JSON은 날짜당 1개만 둡니다.
- 2차는 날짜 페이지를 유지하고 그 아래 시간 목록을 두는 구조로 확장합니다.
- 공개 R2와 내부 저장소는 분리합니다.
- Pages 배포는 direct upload 기준으로 잡고, `frontend/out`만 배포 대상으로 사용합니다.
- `CLOUDFLARE_ACCOUNT_ID`와 `R2_S3_ENDPOINT`는 기본적으로 GitHub Variables로 둡니다.
- endpoint는 코드에서 조합하지 않고 완성 URL을 variable로 저장합니다.
