# Hybrid Dynamic Registry — 운영 가이드

## 아키텍처 개요

```
┌──────────────────────────┐   ┌──────────────────────────┐
│       Base Layer         │   │      Dynamic Layer       │
│  official_signal_        │   │  dynamic_signal_         │
│  registry.json           │   │  registry.json           │
│  (정적, 수동 관리)        │   │  (매일 02:00 자동 갱신)  │
└────────────┬─────────────┘   └────────────┬─────────────┘
             │                              │
             └──────────────┬───────────────┘
                            ▼
               ┌────────────────────────┐
               │     Runtime Merge      │
               │  grouped_verified_     │
               │  x_entities() 내부     │
               └────────────────────────┘
                            │
                            ▼
               채널 데이터 수집 (grok_x_keyword, grok_official_signals)
```

### 핵심 원칙

| 원칙 | 설명 |
|------|------|
| **Base Layer 불변** | `official_signal_registry.json`은 수동 관리. Grok 실패와 무관하게 항상 사용 |
| **Dynamic Layer 자동** | 매일 02:00 Grok API 호출 → `dynamic_signal_registry.json` 덮어쓰기 |
| **Runtime Merge** | 채널 데이터 수집 시 두 파일을 런타임에 병합. 별도 merged 파일 없음 |
| **Fallback 안전** | `dynamic_signal_registry.json` 없거나 Grok 장애 시 Base Layer만 사용 |

---

## 파일 위치

```
src/morning_brief/data/registry/
├── official_signal_registry.json     # Base Layer (Git 관리)
└── dynamic_signal_registry.json      # Dynamic Layer (자동 생성, Git 무시 권장)
```

---

## 자동 갱신 흐름

### 매일 02:00 실행 순서

```
1. scheduler.py: _run_dynamic_registry_update(api_key) 실행
2. dynamic_registry_updater.update_dynamic_registry()
   ├── 그룹별 순차 Grok API 호출 (4그룹 = 4회)
   │   ├── crypto_and_etf
   │   ├── ai_bigtech_primary
   │   ├── macro_and_equity
   │   └── btc_etf_primary
   ├── 각 그룹: trust_score >= 3 + x_verified=true 필터링
   ├── Base에 없는 신규 핸들만 추출 (그룹당 최대 10개)
   └── dynamic_signal_registry.json 저장 + cache_clear()
```

### 갱신 로그 확인

성공 시:
```
INFO Dynamic registry 자동 갱신 시작 (2026-03-26)
INFO Dynamic registry Grok API 호출 완료 group=crypto_and_etf cached_input_tokens=1234
INFO Dynamic registry 그룹 처리: group=crypto_and_etf raw=10 validated=8 new=3
INFO dynamic_signal_registry.json 저장 완료: 15개 엔티티
INFO Dynamic registry 갱신 완료
```

실패 시 (Base Layer fallback):
```
WARNING Grok API 실패 (group=ai_bigtech_primary) — Base Layer fallback: ...
WARNING Dynamic registry 갱신 실패 — Base Layer fallback으로 운영 계속
```

---

## Cached Input Tokens 비용 모니터링

### 로그에서 확인

`dynamic_registry_updater.py`의 `_extract_usage()` 함수가 각 Grok 호출의 `cached_input_tokens`를 INFO 레벨로 기록한다:

```
INFO Dynamic registry Grok API 호출 완료 group=crypto_and_etf cached_input_tokens=1800
```

### Prompt Caching 히트율 최적화 요소

| 요소 | 값 | 역할 |
|------|-----|------|
| `x-grok-conv-id` gRPC metadata | `registry-update-daily-2026` (고정) | 동일 서버 라우팅 보장 |
| `FIXED_SYSTEM_PROMPT` | 고정 (날짜 미포함) | 캐시 prefix 일치 |
| User Prompt | 날짜만 변경 | 캐시 miss 최소화 |

`cached_input_tokens > 0` 이면 Prompt Caching 히트. 첫 날 이후 비용이 Input $0.20/M → $0.05/M으로 감소한다.

---

## dynamic_signal_registry.json 갱신 실패 시 확인 방법

### 상황 1: 파일이 없는 경우

`load_dynamic_signal_registry()`가 빈 리스트를 반환한다. 로그에서 확인:

```bash
# 파일 존재 여부 확인
ls -la src/morning_brief/data/registry/dynamic_signal_registry.json
```

`dynamic_signal_registry.json` 없으면 Base Layer만 사용 — **정상 동작**, 브리핑 계속 발행.

### 상황 2: 파일이 오래된 경우 (3일 이상)

Base Layer fallback으로 계속 동작. `official_x_lookback_hours` 기본값 48h (최대 72h)으로 데이터 허용 범위 내.

수동 갱신 실행:

```bash
PYTHONPATH=src python -c "
from morning_brief.data.sources.dynamic_registry_updater import update_dynamic_registry
import os
result = update_dynamic_registry(api_key=os.environ['GROK_API_KEY'])
print('Success:', result)
"
```

### 상황 3: 파일 내용 검증

```bash
PYTHONPATH=src python -c "
import json
from pathlib import Path

path = Path('src/morning_brief/data/registry/dynamic_signal_registry.json')
if not path.exists():
    print('파일 없음 — Base Layer fallback 운영 중')
else:
    data = json.loads(path.read_text())
    print(f'엔티티 수: {len(data)}')
    from collections import Counter
    groups = Counter(e['x_search_group'] for e in data)
    for g, n in groups.items():
        print(f'  {g}: {n}개')
    # x_verified 확인
    unverified = [e for e in data if not e.get('x_verified')]
    print(f'x_verified=false 항목: {len(unverified)} (0이어야 정상)')
"
```

---

## Runtime Merge 동작 확인

```bash
PYTHONPATH=src python -c "
from morning_brief.data import official_signal_registry as r
r.load_official_signal_registry.cache_clear()
r.load_dynamic_signal_registry.cache_clear()

handles = r.grouped_verified_x_handles()
for group, hs in handles.items():
    dynamic = [h for h in hs if True]  # simplified
    print(f'{group}: {len(hs)}개 — {hs[:3]}...')

entities = r.grouped_verified_x_entities()
for group, es in entities.items():
    dynamic = [e for e in es if e.get('x_search_priority') == 0]
    print(f'{group}: Dynamic {len(dynamic)}개 / 전체 {len(es)}개')
"
```

Dynamic 엔티티(`x_search_priority=0`)가 각 그룹의 앞에 배치된다.

---

## 스케줄러 설정

`scheduler.py`의 `run_daily()` 내에서 자동 등록:

```python
scheduler.add_job(
    func=partial(_run_dynamic_registry_update, api_key=settings.grok_api_key),
    trigger="cron",
    hour=2, minute=0,
    id="dynamic_registry_update",
    coalesce=True,     # 중복 실행 방지
    max_instances=1,
)
```

- `coalesce=True`: 스케줄러가 중단됐다가 재시작해도 밀린 실행이 한 번만 실행
- `max_instances=1`: 동시 중복 실행 방지
- `GROK_API_KEY` 미설정 시 잡 등록 건너뜀

---

## Dynamic 엔티티 스키마

| 필드 | 타입 | 값 | 설명 |
|------|------|----|------|
| `handle` | str | X 핸들 (`@` 제외) | 동적 |
| `x_search_group` | str | 그룹 상수값 | `crypto_and_etf`, `ai_bigtech_primary`, `macro_and_equity`, `btc_etf_primary` |
| `x_search_priority` | int | `0` 고정 | Base 최솟값(1)보다 낮아 정렬 최우선 |
| `trust_score` | int | 3~5 | Grok 신뢰성 점수 (< 3 저장 금지) |
| `rationale` | str | 추천 근거 | Grok 생성 |
| `x_verified` | bool | `true` 고정 | 비인증 계정 저장 금지 |

---

## 위험 및 대응

| 상황 | 영향 | 대응 |
|------|------|------|
| Grok API 완전 장애 | Dynamic Layer 갱신 중단 | Base Layer fallback 자동 전환, 브리핑 정상 발행 |
| `dynamic_signal_registry.json` 3일 미갱신 | 최신성 저하 | Base Layer fallback, `official_x_lookback_hours` 범위 내 정상 |
| trust_score < 3 핸들 추천 | 낮은 품질 핸들 포함 위험 | 저장 단계에서 자동 필터링 |
| x_verified=false 핸들 | 비인증 계정 포함 위험 | 저장 단계 + Runtime Merge 이중 차단 |
| Base 하위 priority 핸들 탈락 | 기존 일부 핸들 누락 | 설계 의도 (Dynamic 우선, Requirements 3.5) |
