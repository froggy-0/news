# Fully Automated Dynamic Registry — Feature Design

## Overview

기존 `official_signal_registry.json` 정적 레지스트리를 Base Layer로 유지하면서, Grok API의 X Search Tool을 통해 매일 완전 자동으로 `dynamic_signal_registry.json`을 갱신하는 Fully Automated Dynamic Registry 시스템을 설계한다. 수동 검토·승인 단계는 없으며, 런타임에 Base + Dynamic을 merge하여 사용한다.

핵심 전략 세 가지:
1. **Base Layer 불변 보장** — Grok API 응답 품질과 무관하게 기존 핸들은 항상 유지
2. **단일 호출 최적화** — 모든 그룹을 하나의 Grok API 요청으로 처리, 하루 1회 실행
3. **Prompt Caching 극대화** — System Prompt 고정 + `x-grok-conv-id` gRPC metadata로 비용 최소화

## Glossary

- **Base Layer**: `official_signal_registry.json` — 정적으로 관리되는 핵심 신뢰 핸들 목록. 항상 fallback
- **Dynamic Layer**: Grok API 응답으로 생성된 그룹별 Top 10개 추천 핸들 목록. `dynamic_signal_registry.json`에 자동 저장
- **Runtime Merge**: 채널 데이터 수집 시 `official_signal_registry.json`(Base)과 `dynamic_signal_registry.json`(Dynamic)을 런타임에 병합. 별도의 merged 파일은 생성하지 않음
- **`allowed_x_handles`**: `x_search` 도구의 핸들 필터링 파라미터 (최대 10개 제한)
- **Parallel Tool Calling**: 그룹별 독립 `x_search` 호출을 단일 API 요청 내에서 동시 실행하는 방식. OR 쿼리 미지원을 대체하여 커버리지 확대
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
2. Dynamic Layer 신규 핸들 → Base에 없는 것만 추가
3. 그룹당 상한 `_GROK_MAX_HANDLES = 10` 적용 (Base가 상한 초과 시 Base 전체 유지, 상한은 신규 추가에만 적용)

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

### x_search Tool + Parallel Tool Calling (xai_sdk v1.10.0+)

각 그룹마다 독립적인 `x_search` 호출을 **Parallel Tool Calling**으로 동시 실행한다. `from:handle OR ...` OR 쿼리는 xAI 미지원으로 사용하지 않는다:

```python
# 단일 API 요청 내에서 그룹별 x_search가 병렬 실행됨
# Grok 모델이 자동으로 각 그룹에 대해 x_search tool call을 병렬 발행

# 각 그룹별 x_search 파라미터 예시:
{
    "allowed_x_handles": ["handle1", "handle2", ..., "handle10"],  # max 10
    "query": "crypto bitcoin influential"
}
# → 모든 그룹(crypto, ai_bigtech, semicon, ...)에 대해 위 형태로 병렬 실행
```

## 일 단위 업데이트 흐름

```
[매일 새벽 — 자동 업데이트]

1. 스케줄러 실행
        │
        ▼
2. Grok API 단일 호출
   - grok-4-1-fast-non-reasoning
   - System Prompt (고정, 캐싱)
   - User Prompt (날짜 등 최소 동적 정보, 그룹별 요청 구분 기술)
   - response_format: json_object
   - gRPC metadata: x-grok-conv-id=registry-update-daily-2026
   - 그룹별 x_search Parallel Tool Calling 자동 실행
        │
        ▼
3. 응답 파싱
   - Grok JSON 파싱 → 그룹별 핸들 목록 추출
        │
        ▼
4. dynamic_signal_registry.json 자동 저장
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
| Parallel Tool Calling 과다 호출 | 그룹 수 사전 확정 + 하루 1회 단일 API 호출 제한 |
| Grok API 장애 | Base Layer fallback → 기존 동작 유지 |

## Correctness Properties

### Property 1: Base Layer 불변 보장

_For any_ Merged Registry 생성에서, Merge 함수는 Base Layer의 모든 핸들을 Merged Registry에 포함해야 한다 (SHALL). Grok 추천이 Base 핸들을 제외하거나 덮어쓰지 않아야 한다.

**Validates: Requirements 1.1, 1.3**

### Property 2: Grok API 장애 안전성

_For any_ Grok API 호출 실패 또는 응답 파싱 오류에서, 시스템은 Base Layer만으로 채널 데이터 수집을 정상적으로 수행해야 한다 (SHALL).

**Validates: Requirements 1.2, 6.1**

### Property 3: 비용 최적화 준수

_For any_ 일 단위 업데이트 실행에서, 시스템은 정확히 1회의 Grok API 호출만 수행해야 하며, x-grok-conv-id 헤더 및 고정 System Prompt가 설정되어야 한다 (SHALL).

**Validates: Requirements 2.4, 5.1**

### Property 4: Prompt Caching 구조 보장

_For any_ Grok API 호출에서, messages[0]은 고정 System Prompt이어야 하며 User Prompt는 날짜 등 최소 동적 정보만 포함한 messages[1]로 append되어야 한다 (SHALL). messages 순서를 변경·삭제·재정렬하지 않아야 한다.

**Validates: Requirements 5.2, 5.3, 5.4**

### Property 5: 그룹당 상한 적용

_For any_ Merged Registry에서, 각 그룹의 핸들 수는 `_GROK_MAX_HANDLES = 10` 상한을 초과하지 않아야 한다 (SHALL). 단, Base Layer가 상한을 초과하는 경우 Base Layer 전체를 유지한다.

**Validates: Requirements 3.2**

### Property 6: 기존 데이터 수집 로직 보존

_For any_ 채널 데이터 수집 실행에서, 기존 수집 로직은 Merged Registry 파일 경로만 변경되고 내부 로직은 그대로 유지되어야 한다 (SHALL). OR 쿼리 (`from:handle OR ...`)는 어떤 경우에도 사용하지 않아야 한다.

**Validates: Requirements 3.4, 4.1**
