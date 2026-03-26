# Perplexity Sonar 파이프라인 최적화 가이드

**현재 상태**: 실행당 8~13회 API 호출, 토픽 4개(macro/us_equity/ai_bigtech/bitcoin) 브리핑 생성.
**최적화 목표**: **토큰 20~40%↓, 총비용 10~30%↓, latency 30%↓, 확장성 10배↑** (Sonar API 토큰 기반 + $0.005/request 기준).

## 1. 성능 개선 (Latency & 안정성)

Sonar Chat/Search는 I/O 중심이므로 병렬화와 재시도가 핵심입니다.

- **전체 파이프라인 병렬화**: `asyncio.gather()`로 Phase1 4개 Chat, Phase2 4~8개 Search를 동시에 실행. 현재 순차 → 병렬로 전환 시 wall-clock 시간 60% 단축.
- **스트리밍 응답 도입**: Chat API에서 `stream=True` 사용. summary_text가 충분히 생성된 시점(예: 70%)에 UI/이메일 템플릿 채움. 최종 citations/usage는 후처리.
- **Rate Limit 대응 강화**: 429 발생 시 `Retry-After` 헤더 우선 적용. 없으면 지수 백오프(1s→2s→4s) + jitter로 최대 2회 재시도. Circuit Breaker 유지하되, 재시도 성공률 20%↑ 예상.
- **타임아웃 조정**: 기본 30s → 60s로 늘리고, timeout 후에도 부분 응답 사용(스트리밍 덕분).

## 2. 토큰 최적화 (비용 핵심)

토큰 사용량이 비용의 80% 이상이므로 입력/출력 최적화 필수입니다.

### Phase 1: Sonar Chat (4회 → 효율↑)

- **프롬프트 구조화**: 토픽별 별도 system prompt. 예:

  ```
  macro: "최근 macro 지표(FOMC, CPI, 실업률) + 발표일/출처/변동률 중심. notable_stocks 비우기."
  bitcoin: "가격 변동 + 온체인 지표 + 규제 뉴스 중심."
  ```

  → 불필요 토큰 제거, 출력 일관성↑.

- **Citations 재활용**: summary citations URL을 NewsItem으로 변환 후 Phase2에서 "이미 확인된 도메인 제외" 필터 적용. 중복 Search 30%↓.

### Phase 2: Sonar Search (8회 → 6회↓)

- **동적 쿼리 생성**: Phase1 summary에서 키워드 추출(예: "FOMC" 나오면 ["FOMC minutes", "Fed rate decision", "Powell speech"]). 고정 3개 → 동적 2개.
- **파라미터 튜닝**:

  | 토픽 | recency | max_results |
  |------|---------|-------------|
  | macro | week | 6 |
  | us_equity | day | 4 |
  | ai_bigtech | day | 6 |
  | bitcoin | day | 4 |

  → 호출 수 25%↓, 관련도↑.

- **로컬 후처리**: Search 결과 제목/snippet 기반 cosine similarity로 상위 4개만 Phase3 전달.

### Phase 3: Sonar Context (1회 → 토큰 50%↓)

- **입력 압축**: 12개 기사 전체 텍스트 → 구조화 JSON 배열:

  ```json
  [{"title": "...", "ticker": ["AAPL"], "sector": "tech", "summary": "1줄 요약", "key_metric": "EPS +5%"}]
  ```

  프롬프트: "섹터 간 공통 리스크/테마/상관관계만 3문장으로 분석."

## 3. 캐싱 전략 (호출 40%↓)

Redis/Memcached 등으로 구현 (TTL 30분).

- **Chat 캐시**: 키=`topic+timestamp(1h)`, 값=전체 응답. 동일 토픽 재호출 시 100% 히트 → Phase1 4회 중 2회 생략.
- **Search 캐시**: 키=`query+recency+mode`, 값=결과 리스트. 신규 결과만 diff 추가 → Phase2 중복 50%↓.
- **Warm-up 캐시**: 매일 06:00에 macro/us_equity 등 주요 토픽 미리 실행/저장. 장중 첫 요청 즉시 반환.
- **캐시 Hit율 모니터링**: 70% 이상 목표. Miss 시 fallback to API.

## 4. 데이터 확장성 (토픽 4→40개 가능)

현재 고정 4토픽 → 동적/사용자 정의로 확장.

- **토픽 메타데이터 DB**:

  | topic_id | name | recency | max_results | prompt_template | model |
  |----------|------|---------|-------------|-----------------|-------|
  | macro | Macro | week | 6 | template_macro | sonar |
  | korea_equity | 한국주식 | day | 4 | template_kr | sonar |

  → config.yaml 또는 DB에서 로드, 토픽 추가 O(1).

- **사용자 맞춤**: 사용자별 관심 티커 리스트 → Search 쿼리에 `AND (AAPL OR NVDA)` 추가, Context에서 우선 강조.
- **배치 처리**: 사용자 100명 → 토픽별 unique 요청만 API 호출 후, 사용자별 필터링. 공통 토픽 비용 90%↓.
- **샤딩**: 토픽 그룹화(macro_group, equity_group) → 병렬 파이프라인 실행.

## 5. 모니터링 & A/B 테스트

```
로그 항목 (Prometheus/Grafana):
├─ api_calls_total{phase,model}
├─ tokens_total{input/output,phase}
├─ cost_total{chat/search}
├─ cache_hit_rate
└─ latency_p95{phase}

테스트 플랜:
Week1: 캐싱+병렬화 → latency/cost 20%↓ 확인
Week2: 토큰 최적화 → Phase3 토큰 50%↓ 확인
Week3: 동적 토픽 → 8토픽 테스트
```

## 예상 ROI

| 개선 영역 | 효과 | 구현 난이도 |
|-----------|------|-------------|
| 병렬+캐싱 | 호출 40%↓, latency 30%↓ | 중 |
| 토큰 최적화 | 비용 20~40%↓ | 상 |
| 확장성 | 토픽 10배↑ | 하 |

## 참고 자료

- [Token Pricing](https://docs.perplexity.ai/docs/getting-started/pricing)
- [Sonar API Quickstart](https://docs.perplexity.ai/docs/sonar/quickstart)
- [Core Features](https://docs.perplexity.ai/docs/sonar/features)
- [Rate Limits & Usage Tiers](https://docs.perplexity.ai/docs/admin/rate-limits-usage-tiers)
