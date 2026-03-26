# Fully Automated Dynamic Registry — Feature Design

## Overview

기존 `official_signal_registry.json` 정적 레지스트리를 Base Layer로 유지하면서, Grok API의 X Search Tool을 통해 매일 완전 자동으로 `dynamic_signal_registry.json`을 갱신하는 Fully Automated Dynamic Registry 시스템을 설계한다. 수동 검토·승인 단계는 없으며, 런타임에 Base + Dynamic을 merge하여 사용한다.

핵심 전략 세 가지:
1. **Base Layer 불변 보장** — Grok API 응답 품질과 무관하게 기존 핸들은 항상 유지
2. **그룹당 순차 API 호출** — xai_sdk `x_search` 도구는 `allowed_x_handles`가 tool 등록 시 고정되므로, 그룹별로 별도 API 요청 순차 실행 (`grok_official_signals.py` 패턴과 동일)
3. **Prompt Caching 극대화** — System Prompt 고정 + `x-grok-conv-id` gRPC metadata로 비용 최소화

## Glossary

- **Base Layer**: `official_signal_registry.json` — 정적으로 관리되는 핵심 신뢰 핸들 목록. 항상 fallback
- **Dynamic Layer**: Grok API 응답으로 생성된 그룹별 Top 10개 추천 핸들 목록. `dynamic_signal_registry.json`에 자동 저장
- **Runtime Merge**: 채널 데이터 수집 시 `official_signal_registry.json`(Base)과 `dynamic_signal_registry.json`(Dynamic)을 런타임에 병합. 별도의 merged 파일은 생성하지 않음
- **`allowed_x_handles`**: `x_search` 도구의 핸들 필터링 파라미터 (최대 10개 제한)
- **Sequential API Calls**: xai_sdk의 `x_search` 도구는 `allowed_x_handles` 파라미터가 tool 등록 시 고정되므로, 그룹별로 다른 handles를 사용하려면 그룹당 별도 API 요청이 필요하다. `grok_official_signals.py`의 그룹당 순차 호출 패턴과 동일.
- **Prompt Caching**: Grok API의 자동 캐싱 기능. messages prefix가 정확히 일치 시 Cached Input Tokens 요금 적용
- **`x-grok-conv-id`**: 동일 서버 라우팅을 보장하여 캐시 히트율을 높이는 식별자. xai_sdk에서는 gRPC metadata로 전달

## Architecture

### 파일 구조 (Option B: 파일 분리)

```
┌──────────────────────┐   ┌──────────────────────────┐
│     Base Layer       │   │      Dynamic Layer       │
│ (정적, 불변)         │   │ (매일 완전 자동 갱신)     │
│                      │   │                          │
│ official_signal_     │   │ dynamic_signal_          │
│ registry.json        │   │ registry.json            │
│                      │   │ ← Grok API 자동 저장     │
│                      │   │   (수동 승인 없음)        │
└──────────┬───────────┘   └───────────┬──────────────┘
           │                           │
           └──────────┬────────────────┘
                      ▼
           ┌──────────────────────┐
           │    Runtime Merge     │  ← 채널 데이터 수집 시 실행
           │  (Base 우선 적용)    │
           └──────────────────────┘
```

### Runtime Merge 규칙

1. Base Layer 핸들 → 무조건 포함 (최고 우선순위)
2. Dynamic Layer 신규 핸들 → Base에 없는 것만 추가. `x_verified: true`인 핸들만 진입 허용 (`list_verified_x_entities()` 필터 통과 필수)
   - `x_verified` 필드는 Base/Dynamic 구분 없이 동일하게 `True` 조건 적용. 별도 `dynamic_verified` 필드는 추가하지 않는다.
3. 그룹당 상한 `_GROK_MAX_HANDLES = 10` 적용. Dynamic 엔티티(`x_search_priority=0`)가 정렬 최우선이므로, Base+Dynamic 합계가 상한 초과 시 Base 하위 priority 항목이 슬라이스에서 탈락할 수 있음 (Requirements 3.5 참조)
4. **Dynamic 엔티티 `x_search_priority = 0` 고정** — Base 엔티티 최솟값보다 낮게 설정하여 기존 `sorted(key=x_search_priority ASC)[:12]` 로직 변경 없이 자동 상위 배치

### Runtime Merge 진입점 (Option B)

`official_signal_registry.py`에 `load_merged_registry()` 공통 레이어를 추가하지 않는다. 대신 각 진입점에서 직접 Dynamic 레지스트리를 읽어 merge한다:

- **`grouped_verified_x_entities()`**: 그룹별 `OfficialSignalEntity` 목록을 반환하는 함수. 내부에서 `dynamic_signal_registry.json`을 로드하여 Base에 merge 후 반환
- **`grouped_verified_x_handles()`**: 그룹별 핸들 문자열 목록을 반환하는 함수. 동일하게 `dynamic_signal_registry.json`을 로드하여 merge 후 반환

두 진입점이 각자 독립적으로 Dynamic 레지스트리를 읽는다. `dynamic_signal_registry.json` 파일 없을 경우 각 진입점이 Base만 반환 (fallback).

## Grok API 호출 설계

### 모델 및 파라미터

```python
{
    "model": "grok-4-1-fast-non-reasoning",  # alias: grok-4-1-fast-non-reasoning-latest
    "response_format": {"type": "json_object"},  # Structured Outputs 강제
    "messages": [
        {"role": "system", "content": FIXED_SYSTEM_PROMPT},  # 고정 — 캐싱 대상
        {"role": "user", "content": user_prompt_with_date},  # 날짜만 동적 변경
    ]
}
```

### gRPC Metadata (Prompt Caching 최적화)

xai_sdk(gRPC) 환경에서는 `Client()` 초기화 시 `metadata` 파라미터로 전달한다 (xai_sdk v1.10.0 이상):

```python
from xai_sdk import Client

client = Client(
    api_key=api_key,
    metadata=(("x-grok-conv-id", "registry-update-daily-2026"),),  # 고정 — 동일 서버 라우팅 보장
)
```

### x_search Tool — 그룹당 순차 API 호출 (xai_sdk v1.10.0+)

xai_sdk의 `x_search` 도구는 `allowed_x_handles` 파라미터가 tool 등록 시 고정된다. 따라서 그룹별로 다른 handles를 사용하려면 그룹당 별도 API 요청이 필요하며, 현재 `grok_official_signals.py`의 순차 호출 패턴과 동일하게 구현한다. `from:handle OR ...` OR 쿼리는 xAI 미지원으로 사용하지 않는다:

```python
# 그룹당 별도 API 요청을 순차 실행 — grok_official_signals.py 패턴과 동일
for group in search_groups:  # [CRYPTO_ETF_GROUP, AI_BIGTECH_GROUP, ...]
    handles = get_handles_for_group(group)  # 해당 그룹의 핸들 목록 (max 10)
    response = client.chat.completions.create(
        model="grok-4-1-fast-non-reasoning",
        tools=[x_search_tool(allowed_x_handles=handles)],
        messages=[...],
        response_format={"type": "json_object"},
    )
    # 응답 파싱 후 dynamic_signal_registry.json에 저장
```

### 그룹명 매핑 테이블

Grok API JSON 응답 키 ↔ 코드 그룹 상수 대응표 (`src/morning_brief/data/sources/grok_x_keyword.py` 기준):

| Grok 응답 키 | 코드 상수명 | 상수값 |
|--------------|-------------|--------|
| `"crypto"` | `CRYPTO_ETF_GROUP` | `"crypto_and_etf"` |
| `"ai_bigtech"` | `AI_BIGTECH_GROUP` | `"ai_bigtech_primary"` |
| `"macro_and_equity"` | `MACRO_EQUITY_GROUP` | `"macro_and_equity"` |
| `"btc_etf"` | `BTC_ETF_GROUP` | `"btc_etf_primary"` |

### 신뢰성 기준 및 JSON 출력 스키마

Grok 프롬프트에 다음 신뢰성 기준을 명시하여 추천 품질을 제어한다:

**필수 조건 (프롬프트에 명시)**:
- `x_verified: true` 공식 인증 계정만 추천. 비인증 계정은 추천 제외

**신뢰성 점수 계층 (높을수록 우선 추천)**:

| trust_score | 계정 유형 | 예시 |
|-------------|-----------|------|
| 5 | 기관/기업 공식 계정 | Fed, SEC, Apple IR, TSMC IR |
| 4 | 주요 금융/기술 미디어 공식 계정 | Bloomberg, Reuters, CNBC |
| 3 | 팔로워 기준 영향력 있는 전문가 | 애널리스트, 이코노미스트 |

**JSON 출력 스키마 (그룹별 핸들 목록)**:

```json
{
  "groups": {
    "crypto": [
      {
        "handle": "Saylor",
        "trust_score": 3,
        "rationale": "MicroStrategy CEO, 주요 BTC 보유 기관 대표"
      }
    ],
    "ai_bigtech": [ ... ]
  }
}
```

## 일 단위 업데이트 흐름

```
[매일 새벽 — 자동 업데이트]

1. 스케줄러 실행
        │
        ▼
2. Grok API 그룹당 순차 호출 (N그룹 = N회 API 요청)
   - grok-4-1-fast-non-reasoning
   - System Prompt (고정, 캐싱)
   - User Prompt (날짜 등 최소 동적 정보)
   - response_format: json_object
   - gRPC metadata: x-grok-conv-id=registry-update-daily-2026
   - 그룹별 allowed_x_handles 고정하여 순차 실행 (grok_official_signals.py 패턴)
        │
        ▼
3. 응답 파싱 및 신뢰성 검증
   - Grok JSON 파싱 → 그룹별 핸들 목록 추출
   - x_verified: true 필터 재확인 (list_verified_x_entities() 통과 여부)
   - trust_score 기준 정렬 (높은 순)
        │
        ▼
4. dynamic_signal_registry.json 자동 저장
   - x_search_priority = 0 으로 각 Dynamic 엔티티 설정
   - 수동 승인 없이 즉시 덮어쓰기
   - 저장 실패 시 기존 파일 유지 (안전)

[채널 데이터 수집 시 — Runtime Merge]

5. 채널 데이터 수집 로직 실행
   - official_signal_registry.json (Base) 로드
   - dynamic_signal_registry.json (Dynamic) 로드
     └─ 파일 없을 경우: Base만 사용 (fallback)
   - Runtime Merge 실행 (Base 우선 + 신규 추가 + 상한 적용)
```

## Prompt Caching 설계

### 캐시 히트율 극대화 원칙

| 조건 | 동작 |
|------|------|
| messages 앞부분(prefix) 일치 | 캐시 히트 → Cached Input 요금 ($0.20/M → $0.05/M) |
| x-grok-conv-id 동일 | 동일 서버 라우팅 → 히트율 대폭 증가 |
| messages 앞부분 수정/재정렬 | 캐시 miss |
| x-grok-conv-id 미설정 또는 변경 | 다른 서버 라우팅 → 히트율 저하 |

### messages 배열 구조

```
messages[0]: System Prompt (고정 — 매일 동일)
             - 역할 정의
             - 그룹 목록 및 설명
             - Few-shot 예시
             - JSON 출력 형식 명세
messages[1]: User Prompt (날짜만 변경)
             - "오늘 날짜: YYYY-MM-DD"
             - 추가 동적 컨텍스트 (최소화)
```

**캐싱이 깨지는 패턴 (금지)**:
- messages[0] (System Prompt) 내용 변경
- messages 순서 변경 또는 삭제
- x-grok-conv-id 값 변경

## 비용 추정

| 항목 | 설정 | 효과 |
|------|------|------|
| 모델 | grok-4-1-fast-non-reasoning | Input $0.20/M, Output $0.50/M |
| Prompt Caching | System Prompt 고정 + gRPC metadata x-grok-conv-id 고정 | Input $0.20/M → $0.05/M (히트 시) |
| Structured Outputs | response_format: json_object | 출력 토큰 최소화 + 파싱 안정성 |
| 호출 횟수 | 하루 1회 단일 호출 | 비용 예상: 수십 원 수준/일 |

## 위험 및 대응

| 위험 | 대응 방안 |
|------|-----------|
| Grok 추천 변동성 (추천 핸들이 자주 바뀜) | Base 우선 Merge 규칙 → 핵심 핸들은 항상 유지 |
| Tool 호출 비용 초과 | 하루 1회 단일 호출 제한 + Prompt Caching 강제 |
| 추천 품질 저하 (관련성 낮은 핸들 포함) | Few-shot 예시 추가 + Base 우선 Merge로 핵심 핸들 보호 |
| 그룹당 순차 API 호출 과다 | 그룹 수 사전 확정 + 하루 1회 실행 제한 |
| Grok API 장애 | Base Layer fallback → 기존 동작 유지 |
| `dynamic_signal_registry.json` 3일 이상 미갱신 | Base Layer fallback으로 정상 동작 보장. `official_x_lookback_hours` 기본값 48h(최대 72h)로 데이터 허용 기간 제어 |

## Correctness Properties

### Property 1: Base Layer 불변 보장

_For any_ Merged Registry 생성에서, Merge 함수는 Base Layer의 모든 핸들을 Merged Registry에 포함해야 한다 (SHALL). Grok 추천이 Base 핸들을 제외하거나 덮어쓰지 않아야 한다.

**Validates: Requirements 1.1, 1.3**

### Property 2: Grok API 장애 안전성

_For any_ Grok API 호출 실패 또는 응답 파싱 오류에서, 시스템은 Base Layer만으로 채널 데이터 수집을 정상적으로 수행해야 한다 (SHALL).

**Validates: Requirements 1.2, 6.1**

### Property 3: 비용 최적화 준수

_For any_ 일 단위 업데이트 실행에서, 시스템은 그룹당 1회씩 순차적으로 Grok API를 호출해야 하며 (N그룹 = N회), 각 호출마다 x-grok-conv-id 헤더 및 고정 System Prompt가 설정되어야 한다 (SHALL).

**Validates: Requirements 5.1**

### Property 4: Prompt Caching 구조 보장

_For any_ Grok API 호출에서, messages[0]은 고정 System Prompt이어야 하며 User Prompt는 날짜 등 최소 동적 정보만 포함한 messages[1]로 append되어야 한다 (SHALL). messages 순서를 변경·삭제·재정렬하지 않아야 한다.

**Validates: Requirements 5.2, 5.3, 5.4**

### Property 5: 그룹당 상한 적용 및 슬라이스 정책

_For any_ Merged Registry에서, 각 그룹의 최종 핸들 수는 `_GROK_MAX_HANDLES = 10` 상한이 적용된 `sorted(key=x_search_priority ASC)[:10]` 결과를 따른다 (SHALL). Dynamic 엔티티(`x_search_priority=0`)가 정렬 최우선이므로, Base+Dynamic 합계가 상한 초과 시 Base 하위 priority 항목이 탈락할 수 있으며 이를 허용한다 (Base Layer 전체 유지 미보장).

**Validates: Requirements 3.2, 3.5**

### Property 6: x_verified 필터 보장

_For any_ Dynamic Layer 엔티티에서, 시스템은 `x_verified: true`가 아닌 핸들을 `dynamic_signal_registry.json`에 저장하지 않아야 한다 (SHALL). Grok 프롬프트 단계(사전 차단)와 파이프라인 진입 단계(`list_verified_x_entities()`)에서 이중으로 검증된다.

**Validates: Requirements 2.5, 8.1**

### Property 7: Dynamic 엔티티 x_search_priority 보장

_For any_ Dynamic 엔티티에서, `x_search_priority` 값은 `0`으로 설정되어야 한다 (SHALL). 기존 `sorted(key=x_search_priority ASC)[:12]` 로직의 변경 없이 Dynamic 엔티티가 상위에 배치되어야 한다.

**Validates: Requirements 3.1**

### Property 8: 기존 데이터 수집 로직 보존

_For any_ 채널 데이터 수집 실행에서, 기존 수집 로직은 Runtime Merge 진입점 추가 외에 내부 로직(sort, slice 포함)은 그대로 유지되어야 한다 (SHALL). OR 쿼리 (`from:handle OR ...`)는 어떤 경우에도 사용하지 않아야 한다.

**Validates: Requirements 3.4, 4.1**

### Property 9: 신뢰성 스키마 보장

_For any_ Dynamic Layer Grok API 응답에서, 모든 추천 핸들 항목은 `trust_score` (정수 1~5) 및 `rationale` (문자열) 필드를 포함해야 한다 (SHALL). `trust_score < 3`인 항목은 Merged Registry에 포함되지 않아야 한다 (SHALL).

**Validates: Requirements 2.6, 2.7**
