# Requirements Document

## Introduction

현재 X 채널 레지스트리는 `official_signal_registry.json`에 정적으로 관리된다. 이 방식은 안정성은 높지만 AI/bigtech 편향, Apple·TSMC 등 커버리지 갭, 수동 관리 부담이라는 한계가 있다. Fully Automated Dynamic Registry는 기존 정적 레지스트리를 Base Layer로 유지하면서, Grok API의 X Search Tool을 활용해 매일 완전 자동으로 Dynamic Layer를 갱신한다. 수동 검토·승인 단계 없이 Grok 추천 결과가 즉시 적용되며, 목표는 안정성을 희생하지 않고 최신성·커버리지·운영 효율성을 동시에 확보하는 것이다.

## Functional Requirements

### Base Layer 유지

1.1 WHEN 시스템이 레지스트리를 사용할 때 THEN 기존 `official_signal_registry.json` 파일이 항상 fallback Base Layer로 유지되어야 한다

1.2 WHEN Grok API 호출이 실패하거나 응답이 유효하지 않을 때 THEN 시스템은 Base Layer만을 사용하여 기존과 동일하게 동작해야 한다

1.3 WHEN Merged Registry를 생성할 때 THEN Base Layer의 핸들은 무조건 포함되어야 하며, Grok 추천과 충돌 시 Base Layer 핸들이 우선되어야 한다

### Dynamic Layer (Grok API 기반 자동 업데이트)

2.1 WHEN 매일 새벽 스케줄러가 실행될 때 THEN 시스템은 하루 1회 Grok API를 호출하여 그룹별 Parallel Tool Calling으로 각 그룹의 Top 10개 influential handles를 추천받아야 한다

2.2 WHEN Grok API를 호출할 때 THEN 시스템은 `grok-4-1-fast-non-reasoning` (alias: `grok-4-1-fast-non-reasoning-latest`) 모델을 사용하고, `response_format: {"type": "json_object"}`로 Structured JSON 출력을 강제해야 한다

2.3 WHEN Grok API를 호출할 때 THEN 시스템은 단일 `x_search` 도구를 사용하며, 각 그룹별로 독립적인 `x_search` 호출을 **Parallel Tool Calling**으로 병렬 실행해야 한다. 그룹별 요청은 prompt 내에서 명확히 구분하여 기술한다

2.4 WHEN Grok API를 호출할 때 THEN 시스템은 모든 그룹을 하나의 API 요청으로 처리하여 하루 1회 단일 호출로 제한해야 한다

### Merged Registry 생성

3.1 WHEN Grok 추천 결과를 처리할 때 THEN 시스템은 Base 핸들을 우선 포함하고, Grok 추천 중 Base에 없는 신규·유용한 핸들만 추가해야 한다

3.2 WHEN Merged Registry를 생성할 때 THEN 커버리지 확대는 그룹별 Parallel Tool Calling으로 달성한다. 그룹당 핸들 수 상한은 `_GROK_MAX_HANDLES = 10` (현재 12)을 유지하며, 그룹 수를 늘리는 방식으로 전체 커버리지를 확대한다

3.3 WHEN Grok API 응답이 수신될 때 THEN 시스템은 수동 승인 없이 추천 결과를 자동으로 `dynamic_signal_registry.json`에 저장해야 한다. 채널 데이터 수집 로직은 런타임에 `official_signal_registry.json`(Base)과 `dynamic_signal_registry.json`(Dynamic)을 merge하여 사용한다

3.4 WHEN Merged Registry를 저장할 때 THEN 기존 채널 데이터 수집 로직은 최소한의 변경으로 유지되어야 한다

### 데이터 수집 쿼리 방식

4.1 WHEN 각 그룹에서 `x_search`로 데이터를 수집할 때 THEN 시스템은 그룹당 최대 10개의 핸들을 `allowed_x_handles` 파라미터로 전달해야 하며, 모든 그룹은 Parallel Tool Calling으로 동시에 실행되어야 한다. `from:handle OR ...` OR 쿼리 방식은 xAI에서 지원하지 않으므로 사용하지 않는다

### 비용 최적화

5.1 WHEN Grok API를 호출할 때 THEN 시스템은 Prompt Caching 히트율을 극대화하기 위해 System Prompt를 고정하고, xai_sdk `Client()` 초기화 시 `metadata=(("x-grok-conv-id", "registry-update-daily-2026"),)`를 전달하여 gRPC metadata로 설정해야 한다. xai_sdk v1.10.0 이상이 필요하다

5.2 WHEN System Prompt를 구성할 때 THEN 정적 내용(System Prompt, Few-shot 예시)을 `messages` 배열의 맨 앞에 배치하고, 날짜 등 동적 정보는 User Prompt 말미에만 추가해야 한다

5.3 WHEN messages 배열을 구성할 때 THEN 이전 메시지를 수정·삭제·재정렬하지 않아야 한다 (캐시 miss 방지)

5.4 WHEN User Prompt를 구성할 때 THEN 매 요청마다 변경되는 부분은 날짜와 최소한의 동적 정보만 포함해야 한다

## Non-Functional Requirements

### 안정성

6.1 WHEN Grok API에 장애가 발생하거나 추천 품질이 저하될 때 THEN 시스템은 Base Layer만으로 안전하게 운영되어야 한다 (Single Point of Failure 제거)

6.2 WHEN 시스템이 동작할 때 THEN 업데이트 주기는 매일 1회이며, 최대 2~3일 전 데이터까지 허용한다

### 운영 효율성

7.1 WHEN 레지스트리가 자동 업데이트될 때 THEN 수동 관리·검토·승인 단계 없이 시장 변화를 반영한 신규 influential 계정이 `dynamic_signal_registry.json`에 완전 자동으로 반영되어야 한다

### 커버리지 개선

8.1 WHEN Dynamic Layer가 핸들을 추천할 때 THEN AI/bigtech 편향을 완화해야 하며, Apple 공식 계정 및 TSMC proxy(`@mingchikuo` 등) 비인증 계정이 `x_search` 결과에 포함될 수 있도록 `x_verified` 필터를 적용하지 않아야 한다. Base Layer와 Dynamic Layer의 출처 구분은 **파일 분리(Option B)**로 확정한다: Grok 추천 결과는 `dynamic_signal_registry.json`에 자동 저장되고, 런타임에 `official_signal_registry.json`(Base)과 merge된다. 수동 승인은 없다

8.2 WHEN Dynamic Layer가 커버리지를 확대할 때 THEN 그룹별 Parallel Tool Calling으로 각 그룹을 독립적으로 호출하여 더 넓은 시그널 수집이 가능해야 한다. 그룹당 핸들 수 상한 `_GROK_MAX_HANDLES = 10`은 유지하며, 그룹 수 확대로 전체 커버리지를 늘린다

## Constraints

- xai_sdk: **v1.10.0 이상 필요** (gRPC metadata 지원). 단일 `x_search` 도구 제공. `allowed_x_handles` 최대 10개 (excluded_x_handles와 mutually exclusive)
- `from:handle OR ...` OR 쿼리 방식: xAI 미지원 — 사용 불가
- Parallel Tool Calling: 그룹별 독립 `x_search` 호출을 동시 실행하여 커버리지 확대
- 권장 모델: `grok-4-1-fast-non-reasoning` (alias: `grok-4-1-fast-non-reasoning-latest`) — Input $0.20/M, Output $0.50/M, Cached $0.05/M
- Context Window: 최대 2M tokens
- Structured Outputs: `response_format: {"type": "json_object"}` 지원
- Prompt Caching: Automatic (messages prefix 기반). gRPC metadata `metadata=(("x-grok-conv-id", "registry-update-daily-2026"),)` 로 동일 서버 라우팅 보장
