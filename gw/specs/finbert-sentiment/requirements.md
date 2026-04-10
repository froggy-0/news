# Requirements Document

## Introduction

현재 파이프라인의 뉴스/시그널 감성 정보는 Grok LLM이 추출한 이산 문자열(`bullish/bearish/neutral`)이거나 아예 부재한다. 이 상태로는 Granger 인과성 검정, ADF 검정 등 수치형 시계열을 전제하는 통계 분석이 불가능하다. ProsusAI/finbert 모델을 도입하여 뉴스 헤드라인과 X 시그널 텍스트를 -1.0 ~ 1.0 범위의 연속 감성 점수로 변환하고, 이를 파이프라인 출력과 프론트엔드 데이터 계약에 반영한다.

## Model Selection: ProsusAI/finbert

### 후보 모델 비교

| 기준        | ProsusAI/finbert                              | yiyanghkust/finbert-tone                    |
| ----------- | --------------------------------------------- | ------------------------------------------- |
| 월간 DL     | ~490만                                        | ~100만                                      |
| 학습 데이터 | Financial PhraseBank — **뉴스 헤드라인/문장** | 4.9B 토큰 — 10-K, 어닝콜, 애널리스트 리포트 |
| 클래스      | positive / negative / neutral (3-class)       | positive / negative / neutral (3-class)     |
| 성능        | F1 ~0.87 (Financial PhraseBank)               | 금융 공시 톤 분류 최강                      |
| 모델 크기   | ~110M (BERT-base)                             | ~110M (BERT-base)                           |

### 한국어 모델 검토 결과

| 모델                             | 클래스                | 한계                                                 |
| -------------------------------- | --------------------- | ---------------------------------------------------- |
| snunlp/KR-FinBert-SC             | **2-class** (pos/neg) | neutral 없음 — 금융 뉴스 대부분이 중립인데 분류 불가 |
| DataWizardd/finbert-sentiment-ko | 3-class               | 학습 데이터 200건, 테스트 42건 — 프로덕션 불가       |

### 선정 근거: ProsusAI/finbert

1. **입력 데이터가 뉴스 헤드라인/소셜 포스트** — `rawTitle`(`"US 10Y Yield Rises Amid Mideast Tensions"`)과 `rawContent`(`"Stock futures decline with S&P 500 down 0.16%..."`)가 Financial PhraseBank의 뉴스 문장 스타일과 일치. finbert-tone의 10-K/어닝콜 문체(`"Revenue increased 12% driven by strong demand"`)와는 도메인 불일치.
2. **원문이 영문** — `rawTitle`, `rawContent`가 전부 영어. 한국어(`title`, `content`)는 LLM 번역본이라 번역 품질 변동이 감성 점수에 노이즈로 전이됨.
3. **한국어 3-class 모델 부재** — 신뢰할 만한 한국어 금융 감성 모델이 사실상 없음.
4. **커뮤니티/에코시스템** — ONNX 최적화 버전(Xenova/finbert), 89개 파인튠 변형 존재. 향후 경량화·Edge 추론 확장 용이.

## Glossary

- **FinBERT**: ProsusAI가 금융 텍스트에 fine-tune한 BERT 모델. positive/negative/neutral 3클래스 확률을 출력
- **sentiment_score**: `P(positive) - P(negative)`로 계산한 -1.0 ~ 1.0 범위의 연속 감성 점수
- **sentiment_label**: sentiment_score 기반으로 매핑한 이산 라벨 (`bullish/bearish/neutral`)
- **sentiment_confidence**: `max(P(positive), P(negative), P(neutral))` — 모델의 판정 확신도를 나타내는 0.0 ~ 1.0 범위의 스칼라. score가 동일한 0.0이라도 confidence가 높으면 "확실한 중립", 낮으면 "극성이 갈린 불확실 상태"로 구분 가능

## Raw Text Audit: 영문 원본 보존 현황

파이프라인에서 수집되는 영문 텍스트가 번역 단계(`public_site.py:_apply_public_translation()`)에서 한국어로 덮어씌워지며 원본이 소실되는 필드를 추적한 결과:

### 현재 보존되는 영문 (2개)

| 최종 JSON 필드 | 원본                       | 보존 방식                                                 |
| -------------- | -------------------------- | --------------------------------------------------------- |
| `rawTitle`     | `NewsItem.title`           | `public_site.py:1206` — 번역 전 영문을 `rawTitle`에 저장  |
| `rawContent`   | `XSignal.headline+summary` | `public_site.py:1142` — `_contains_korean()` 체크 후 보존 |

### 현재 버려지는 영문 (FinBERT 입력으로 가치 높음)

| 원본 필드                         | 수집 소스                     | 내용 예시              | 최종 JSON                             | 손실 지점                                                 |
| --------------------------------- | ----------------------------- | ---------------------- | ------------------------------------- | --------------------------------------------------------- |
| `NewsItem.summary`                | Perplexity Search, Grok Web/X | 영문 스니펫 1~3문장    | `summaryKo` (한국어만)                | `public_site.py:1342-1345` — 번역만, 원문 미저장          |
| `NewsItem.why_it_matters`         | Grok X/Official, Perplexity   | 영문 시장 해석 1~2문장 | `interpretation` (한국어만)           | `public_site.py:1188-1197` — 한국어 우선, 영문 fallback만 |
| `TopicSummary.summary_text`       | Perplexity Sonar              | 영문 2~4문단 분석      | `topicSummaries[].summary` (한국어만) | `public_site.py:800-803,1325-1328`                        |
| `TopicSummary.market_implication` | Perplexity Sonar              | 영문 시장 영향 1문장   | `summary`에 병합 후 번역              | 동일                                                      |
| `SonarContext.key_narrative`      | Perplexity Sonar              | 교차 분석 핵심 서사    | 최종 JSON에 미포함                    | 완전 소실                                                 |
| `SonarContext.analyses[]`         | Perplexity Sonar              | 섹터 교차 분석         | 최종 JSON에 미포함                    | 완전 소실                                                 |

### FinBERT 입력량 비교

| 시나리오                       | 영문 텍스트 건수 | 텍스트 풍부도                             |
| ------------------------------ | ---------------- | ----------------------------------------- |
| 현재 (rawTitle + rawContent만) | ~20건            | 헤드라인 1줄 + 시그널 2~3문장             |
| 영문 원본 보존 후              | ~50건+           | 헤드라인 + 스니펫 + 시장 해석 + 토픽 분석 |

## Requirements

### Requirement 1: FinBERT 추론 모듈

**카테고리:** 데이터 수집/입력

**User Story:**
As a 파이프라인 운영자,
I want 영문 금융 텍스트를 FinBERT에 배치 추론하여 연속 감성 점수를 얻고 싶다,
so that 뉴스와 시그널의 감성을 수치형 시계열로 활용할 수 있다.

#### Acceptance Criteria

1. WHEN 1개 이상의 영문 텍스트 리스트가 입력되면, THE `finbert_sentiment` 모듈 SHALL ProsusAI/finbert 모델을 사용하여 각 텍스트에 대해 `sentiment_score` (float, -1.0 ~ 1.0)를 반환한다.
2. WHEN `sentiment_score >= 0.3`이면 `sentiment_label`은 `"bullish"`, `<= -0.3`이면 `"bearish"`, 그 외는 `"neutral"`로 THE 모듈 SHALL 매핑한다.
3. WHEN 빈 문자열 또는 None이 입력되면, THE 모듈 SHALL `sentiment_score = None`, `sentiment_label = None`, `sentiment_confidence = None`을 반환한다. 빈 입력은 "관측 없음"이며 "중립"과 구분해야 한다 (시계열 분석에서 missing data와 neutral은 다른 의미).
4. WHEN 모델 로딩 또는 추론 중 예외가 발생하면, THE 모듈 SHALL 경고 로그를 남기고 모든 항목에 대해 `sentiment_score = None`, `sentiment_label = None`을 반환한다 (파이프라인 중단 금지).
5. WHEN 60건 이하의 텍스트가 입력되면, THE 모듈 SHALL CPU 환경에서 15초 이내에 추론을 완료한다.
6. WHEN 각 텍스트에 대해 추론이 완료되면, THE 모듈 SHALL `sentiment_confidence` (float, 0.0 ~ 1.0, `max(P(positive), P(negative), P(neutral))`)를 함께 반환한다. 이 값은 동일한 `sentiment_score`를 가진 항목 간 판정 확신도를 구분하는 데 사용된다.

---

### Requirement 2: 데이터 모델 확장

**카테고리:** 데이터 모델/구조

**User Story:**
As a 데이터 분석가,
I want 뉴스와 X 시그널에 수치형 감성 점수가 포함되어 있길 원한다,
so that 시계열 분석과 통계 모델의 입력으로 사용할 수 있다.

#### Acceptance Criteria

1. WHEN `NewsItem`이 생성되면, THE 모델 SHALL `sentiment_score: float | None` (기본값 `None`), `sentiment_label: str` (기본값 `""`), `sentiment_confidence: float | None` (기본값 `None`) 필드를 포함한다.
2. WHEN `XSignal`이 생성되면, THE 모델 SHALL `sentiment_score: float | None` (기본값 `None`)과 `sentiment_confidence: float | None` (기본값 `None`) 필드를 포함한다. 기존 `sentiment` 문자열 필드는 유지한다.
3. WHEN `NewsPacketItem`이 직렬화되면, THE TypedDict SHALL `sentiment_score: float | None`과 `sentiment_confidence: float | None` 필드를 포함한다.
4. WHEN 프론트엔드 스키마(`brief.types.ts`)가 업데이트되면, THE `XSignal` 인터페이스 SHALL `sentimentScore: number | null`, `sentimentConfidence: number | null`, `sentimentLabel: 'bullish' | 'bearish' | 'neutral' | null` 필드를, THE `NewsItem` 인터페이스 SHALL 동일한 3개 필드를 포함한다. 라벨은 **서버(`public_site.py`)에서 임계값 기반으로 계산**하여 JSON에 포함한다. 프론트엔드는 라벨을 표시만 하고 재계산하지 않는다 (임계값 변경 시 서버-클라이언트 불일치 방지).
5. WHEN `XSignal.sentiment`(기존 문자열)과 `NewsItem.sentiment_label`(신규 문자열)의 관계를 문서화할 때, THE 데이터 계약 SHALL `XSignal.sentiment ≡ NewsItem.sentiment_label` 매핑을 명시한다. 두 필드는 동일한 의미(`bullish/bearish/neutral`)이나, 기존 호환성을 위해 필드명을 통일하지 않는다.

---

### Requirement 3: 파이프라인 통합

**카테고리:** 비즈니스 로직

**User Story:**
As a 파이프라인 운영자,
I want 뉴스 수집 완료 후 자동으로 FinBERT 감성 점수가 부여되길 원한다,
so that 수동 개입 없이 모든 브리핑에 수치형 감성 데이터가 포함된다.

#### Acceptance Criteria

1. WHEN `build_news_packet()`이 뉴스를 반환한 직후 (`pipeline.py`의 뉴스 수집 단계 완료 시점, 브리핑 생성 및 번역 단계 이전), THE 파이프라인 SHALL FinBERT 배치 추론을 실행하여 각 `NewsItem`의 **영문 원본** 텍스트(`title`, `summary`, `why_it_matters` 중 비어있지 않은 것을 결합)에 `sentiment_score`와 `sentiment_confidence`를 부여한다. 번역된 한국어 텍스트는 FinBERT 입력으로 사용하지 않는다. 이 시점에 계산하여 브리핑 생성 프롬프트에서도 감성 정보를 활용할 수 있도록 한다. 단, `summary`와 `why_it_matters`의 영문 원본은 Phase A(Req 6) 구현 후에야 최종 JSON에 보존되므로, **Phase A 완료 전에는 `title`(영문 원본)만으로 FinBERT를 실행한다**. FinBERT 추론 자체는 `pipeline.py` 내부에서 번역 전 영문 필드에 직접 접근하므로 영문 원본 사용은 보장된다.
2. WHEN `x_signals`가 수집된 직후 (동일하게 `pipeline.py` 내, 브리핑 생성 이전), THE 파이프라인 SHALL 각 `XSignal`의 **영문 원본** 텍스트(`headline`, `summary`, `why_it_matters` 중 비어있지 않은 것을 결합)에 FinBERT `sentiment_score`와 `sentiment_confidence`를 부여한다.
3. WHEN FinBERT 추론이 실패(Req 1.4)하면, THE 파이프라인 SHALL 기존 동작을 그대로 유지하며 `sentiment_score = None`, `sentiment_confidence = None`인 상태로 진행한다.
4. WHEN 최종 JSON이 생성될 때, THE `public_site.py` SHALL 각 뉴스와 X 시그널 항목에 `sentimentScore`와 `sentimentConfidence` 필드를 포함하여 출력한다.

---

### Requirement 4: 의존성 및 환경

**카테고리:** 설정/환경

**User Story:**
As a CI/CD 파이프라인,
I want FinBERT 관련 의존성이 선택적(optional)으로 관리되길 원한다,
so that 모델이 필요하지 않은 환경(프론트엔드 빌드, 경량 테스트)에서 불필요한 설치를 피할 수 있다.

#### Acceptance Criteria

1. WHEN `transformers`와 `torch`가 설치되지 않은 환경에서 파이프라인이 실행되면, THE 모듈 SHALL 경고 로그를 1회 출력하고 모든 항목의 `sentiment_score`를 `None`으로 설정한다 (ImportError 방지).
2. WHEN ML 의존성을 추가할 때, THE 프로젝트 SHALL `requirements-ml.txt`를 별도로 생성하여 `transformers>=5.0.0`과 `torch>=2.4.0`을 관리한다. `requirements.txt`에는 포함하지 않는다 (torch ~2GB 설치 방지). transformers 5.x는 torch ≥ 2.4를 요구하므로 하한을 맞춘다. Python 3.11 호환성(CI 기준)은 양쪽 모두 충족(≥3.10).
3. WHEN 첫 추론 호출 시, THE 모듈 SHALL 모델을 lazy-load하여 파이프라인 시작 시간에 영향을 최소화한다.

---

### Requirement 5: 기존 동작 보존

**카테고리:** 오류 처리/복원

**User Story:**
As a 기존 브리핑 구독자,
I want FinBERT 도입이 기존 브리핑 품질이나 배송에 영향을 주지 않길 원한다,
so that 안정적으로 서비스를 이용할 수 있다.

#### Acceptance Criteria

1. WHEN FinBERT가 비활성 상태여도, THE 파이프라인 SHALL 기존과 동일한 뉴스 수집, 브리핑 생성, 이메일 발송을 수행한다.
2. WHEN `XSignal`의 기존 `sentiment` 문자열 필드가 사용되는 곳(프론트엔드 렌더링, 브리핑 생성 프롬프트)에서, THE 시스템 SHALL CONTINUE TO 기존 `sentiment` 문자열 기반 동작을 유지한다.
3. WHEN `sentiment_score`가 `None`인 항목이 최종 JSON에 포함되면, THE 프론트엔드 SHALL `sentimentScore` 필드를 `null`로 출력하고 기존 UI 렌더링에 영향을 주지 않는다.

---

### Requirement 6: 영문 원본 텍스트 보존

**카테고리:** 데이터 모델/구조

**User Story:**
As a 데이터 분석가,
I want 뉴스와 토픽 요약의 영문 원본이 최종 JSON에 보존되길 원한다,
so that FinBERT 감성 분석과 향후 영문 기반 통계 분석에 풍부한 입력을 제공할 수 있다.

#### Acceptance Criteria

1. WHEN `NewsItem.summary`(영문)가 번역될 때, THE `public_site.py` SHALL 번역된 `summaryKo`와 함께 원본 영문을 `rawSummary` 필드로 최종 JSON에 보존한다.
2. WHEN `NewsItem.why_it_matters`(영문)가 번역될 때, THE `public_site.py` SHALL 번역된 `interpretation`과 함께 원본 영문을 `rawInterpretation` 필드로 최종 JSON에 보존한다.
3. WHEN `TopicSummary.summary_text` 또는 `market_implication`(영문)이 번역될 때, THE `public_site.py` SHALL 번역된 `summary`와 함께 원본 영문을 `rawSummary` 필드로 최종 JSON에 보존한다.
4. WHEN 프론트엔드 스키마(`brief.types.ts`)가 업데이트되면, THE `NewsItem` 인터페이스 SHALL `rawSummary: string | null`과 `rawInterpretation: string | null` 필드를, THE `TopicSummary` 인터페이스 SHALL `rawSummary: string | null` 필드를 포함한다.
5. WHEN 영문 원본이 이미 한국어인 경우(`_contains_korean()` 판정), THE 시스템 SHALL 해당 `raw*` 필드를 `null`로 설정한다.

> **범위 제외 1:** `SonarContext.key_narrative`와 `SonarContext.analyses[]`는 최종 JSON에 포함되지 않는 중간 데이터로, 이번 범위에서 의도적으로 제외한다. 향후 별도 요구사항으로 다룬다.

> **범위 제외 2:** `TopicSummary`에는 FinBERT 감성 분석을 적용하지 않는다. TopicSummary는 LLM이 생성한 2~4문단 집계 분석문으로, FinBERT의 학습 도메인(뉴스 헤드라인/문장)과 불일치한다. TopicSummary 수준의 감성 정보가 필요하면 해당 토픽에 속한 개별 뉴스의 `sentimentScore` 평균(bottom-up 집계)을 사용한다.

---

### Requirement 7: 텍스트 결합 및 배치 전략

**카테고리:** 비즈니스 로직

**User Story:**
As a 파이프라인 운영자,
I want 뉴스/시그널의 여러 영문 필드가 일관된 규칙으로 결합·배치 추론되길 원한다,
so that BERT 토큰 제한을 초과하지 않으면서 최대한 풍부한 입력으로 감성 점수를 얻을 수 있다.

#### Acceptance Criteria

1. WHEN `NewsItem`의 감성 점수를 산출할 때, THE 모듈 SHALL `title`(최대 64토큰), `summary`(최대 224토큰), `why_it_matters`(최대 224토큰) 중 비어있지 않은 필드를 공백으로 결합하고, 총합 **512토큰 이내로 truncate**한 뒤 단일 추론한다. 필드별 상한은 감성 판단에 유용한 `why_it_matters`가 truncation으로 소실되지 않도록 보장한다.
2. WHEN `XSignal`의 감성 점수를 산출할 때, THE 모듈 SHALL `headline`(최대 64토큰), `summary`(최대 224토큰), `why_it_matters`(최대 224토큰) 중 비어있지 않은 필드를 동일 규칙으로 결합·truncate한다.
3. WHEN 배치 추론 시, THE 모듈 SHALL `batch_size`(기본값 16, 환경변수 `FINBERT_BATCH_SIZE`로 오버라이드 가능) 단위로 모델에 입력을 전달한다. 전체 건수가 `batch_size`를 초과하면 순차 배치로 처리한다 (CPU 환경 OOM 방어).
4. WHEN 전체 추론 대상이 **120건을 초과**하면, THE 모듈 SHALL WARNING 로그를 남기고 다음 우선순위로 120건을 선정한다: (1) `sourceTier` 오름차순 (tier 1 우선), (2) 카테고리별 비례 할당 (특정 카테고리 쏠림 방지), (3) XSignal은 전체의 20%(최대 24건)를 별도 슬롯으로 보장. 선정되지 않은 항목은 `sentiment_score = None`으로 설정한다.

---

### Requirement 8: 관측성 (Observability)

**카테고리:** 출력/리포트

**User Story:**
As a 파이프라인 운영자,
I want FinBERT 추론 결과와 성능 지표가 구조화 로그에 기록되길 원한다,
so that 감성 분석 단계의 정상 동작과 성능을 운영 중 확인할 수 있다.

#### Acceptance Criteria

1. WHEN FinBERT 배치 추론이 완료되면, THE 모듈 SHALL `observability.py`를 통해 추론 건수, 소요 시간(ms), 점수 분포(평균, 최솟값, 최댓값)를 INFO 로그로 기록한다.
2. WHEN FinBERT가 비활성(의존성 미설치) 또는 실패 상태이면, THE 모듈 SHALL WARNING 로그를 **1회만** 출력한다 (Req 4.1과 일치).
3. WHEN 최종 JSON `meta` 섹션이 생성될 때, THE `public_site.py` SHALL `sentimentStatus: "ok" | "skipped" | "failed"` 필드를 포함한다.

---

### Requirement 9: 감성 임계값 설정

**카테고리:** 설정/환경

**User Story:**
As a 데이터 분석가,
I want 감성 라벨 매핑 임계값을 설정으로 조정할 수 있길 원한다,
so that 실제 데이터 분포에 맞춰 bullish/bearish 분류 기준을 최적화할 수 있다.

#### Acceptance Criteria

1. WHEN `config.py`에 `FINBERT_BULLISH_THRESHOLD`(기본값 `0.3`)과 `FINBERT_BEARISH_THRESHOLD`(기본값 `-0.3`)가 정의되면, THE 모듈 SHALL 해당 값을 라벨 매핑 기준으로 사용한다.
2. WHEN 환경변수 `FINBERT_BULLISH_THRESHOLD` 또는 `FINBERT_BEARISH_THRESHOLD`가 설정되면, THE `config.py` SHALL 해당 값으로 기본값을 오버라이드한다.
3. WHEN Phase C 검증 시, THE 개발팀 SHALL 최근 7일 이상의 실제 파이프라인 데이터로 score 분포를 시각화하고, 기본 임계값(±0.3)이 모델 argmax 라벨과의 일치율 ≥ 80%를 달성하는지 확인한다. 미달 시 임계값을 조정하고 조정 근거를 문서화한다.

---

### Requirement 10: Rollback 및 Feature Flag

**카테고리:** 설정/환경

**User Story:**
As a 파이프라인 운영자,
I want FinBERT 감성 분석을 설정 한 줄로 비활성화할 수 있길 원한다,
so that 문제 발생 시 파이프라인 코드 변경 없이 즉시 롤백할 수 있다.

#### Acceptance Criteria

1. WHEN 환경변수 `FINBERT_ENABLED`가 `false`(기본값 `true`)이면, THE 파이프라인 SHALL FinBERT 추론을 건너뛰고 모든 항목의 `sentiment_score`를 `None`으로 설정한다.
2. WHEN `FINBERT_ENABLED=false`이면, THE 파이프라인 SHALL `transformers`/`torch` 모듈을 import하지 않는다.

---

### Requirement 11: 모델 아티팩트 관리

**카테고리:** 설정/환경

**User Story:**
As a CI/CD 파이프라인,
I want FinBERT 모델 아티팩트의 저장 경로와 다운로드 전략이 명확하길 원한다,
so that 배포 환경에서 예측 가능하게 모델을 관리할 수 있다.

#### Acceptance Criteria

1. WHEN 환경변수 `FINBERT_MODEL_PATH`가 설정되면, THE 모듈 SHALL 해당 로컬 경로에서 모델을 로드한다 (HuggingFace Hub 다운로드 생략).
2. WHEN `FINBERT_MODEL_PATH`가 미설정이면, THE 모듈 SHALL HuggingFace 기본 캐시(`~/.cache/huggingface/`)에서 모델을 다운로드/로드한다.
3. WHEN 모델 다운로드가 네트워크 오류로 실패하면, THE 모듈 SHALL Req 1.4와 동일하게 경고 로그 후 `sentiment_score = None`으로 처리한다.
4. WHEN HuggingFace Hub에서 모델을 다운로드할 때, THE 모듈 SHALL 특정 commit hash(`revision` 파라미터)로 모델 버전을 고정한다. 시계열 연속성을 보장하기 위해 모델 가중치가 변경되지 않도록 하며, 사용 중인 commit hash는 `config.py`의 `FINBERT_MODEL_REVISION`으로 관리한다.
5. WHEN 모델 버전을 업데이트할 때, THE 개발팀 SHALL 기존 데이터 샘플(최소 50건)로 score drift를 검증하고, 평균 절대 편차가 0.05 이상이면 변경 사유와 영향을 문서화한다.

---

### Requirement 12: 구현 순서 및 Phase 정의

**카테고리:** 비즈니스 로직

**User Story:**
As a 개발팀,
I want 기능 구현이 독립 배포 가능한 Phase로 분리되길 원한다,
so that 각 Phase를 점진적으로 검증하고 롤백할 수 있다.

#### Acceptance Criteria

1. **Phase A (영문 보존)**: Req 6 SHALL FinBERT 코드 없이 독립적으로 구현·배포 가능하다. 이 Phase만으로 `rawSummary`, `rawInterpretation` 필드가 최종 JSON에 포함된다.
2. **Phase B (FinBERT 통합)**: Req 1, 2, 3, 4, 7, 8, 9, 10, 11, 13 SHALL Phase A 완료 후 구현한다. Phase A의 보존된 영문 필드를 FinBERT 입력으로 활용한다.
3. **Phase C (검증 및 품질)**: Req 5, 14 SHALL Phase B 완료 후 통합 테스트로 검증한다. 기존 브리핑 출력과의 diff가 `sentimentScore`, `sentimentConfidence`, `raw*`, 집계 필드 추가만으로 제한됨을 확인한다. 모델 품질 검증(Req 14)을 병행하여 감성 점수의 합리성을 확인한다.

---

### Requirement 13: 일별 감성 집계 지표

**카테고리:** 출력/리포트

**User Story:**
As a 데이터 분석가,
I want 일별 브리핑에 뉴스·시그널 감성의 집계 지표가 포함되길 원한다,
so that 일별 시계열 분석(Granger 인과성, ADF 검정 등)의 입력으로 즉시 사용할 수 있다.

#### Acceptance Criteria

1. WHEN 최종 JSON `meta` 섹션이 생성될 때, THE `public_site.py` SHALL 뉴스와 X시그널을 **분리 집계**하여 다음 필드를 포함한다:
    - `newsSentiment` 객체:
        - `mean` (float | null): NewsItem `sentimentScore`의 산술 평균
        - `median` (float | null): NewsItem `sentimentScore`의 중앙값
        - `std` (float | null): NewsItem `sentimentScore`의 표준편차 (시장 의견 분열도)
        - `bullishRatio` (float | null): NewsItem 중 `sentiment_label = "bullish"` 비율 (0.0 ~ 1.0)
        - `bearishRatio` (float | null): NewsItem 중 `sentiment_label = "bearish"` 비율 (0.0 ~ 1.0)
        - `count` (int): 유효 항목 수
    - `signalSentiment` 객체: XSignal에 대해 동일 구조 (`mean`, `median`, `std`, `bullishRatio`, `bearishRatio`, `count`)
      뉴스(편집된 기사)와 X시그널(소셜 포스트)은 텍스트 특성이 다르므로 분리 집계가 원칙이다. 합산 지표는 별도로 제공하지 않으며, 필요 시 분석 단계에서 가중 합산한다.
2. WHEN 집계 대상 중 `sentimentScore`가 `null`인 항목이 있으면, THE 집계 SHALL 해당 항목을 제외하고 나머지로 계산한다. 유효 항목이 0건이면 해당 집계 객체의 모든 필드를 `null`로 설정한다 (`count`는 `0`).
3. WHEN 카테고리별(`macro`, `bigtech`, `bitcoin`, `us-stocks`) **뉴스**가 2건 이상이면, THE `public_site.py` SHALL `sentimentByCategory` 객체에 카테고리별 `mean`과 `count`를 포함한다. XSignal은 `category` 필드가 없으므로 카테고리별 집계에서 제외한다.
4. WHEN 프론트엔드 스키마(`brief.types.ts`)가 업데이트되면, THE `BriefMeta` 인터페이스 SHALL 다음 타입을 포함한다:
    ```typescript
    newsSentiment: SentimentAggregate | null;
    signalSentiment: SentimentAggregate | null;
    sentimentByCategory: Record<string, { mean: number; count: number }> | null;
    ```
    여기서 `SentimentAggregate = { mean: number | null; median: number | null; std: number | null; bullishRatio: number | null; bearishRatio: number | null; count: number }`.

---

### Requirement 14: 모델 품질 검증

**카테고리:** 테스트/검증

**User Story:**
As a 데이터 분석가,
I want FinBERT 감성 점수가 실제 파이프라인 데이터에서 합리적인 결과를 내는지 검증하고 싶다,
so that 감성 점수를 신뢰하고 통계 분석에 사용할 수 있다.

#### Acceptance Criteria

1. WHEN Phase C 검증 시, THE 개발팀 SHALL 최근 7일 이상의 실제 브리핑 데이터로 FinBERT를 실행하고, 기존 `XSignal.sentiment`(Grok 라벨)과 FinBERT `sentiment_label`의 일치율이 **≥ 55%** 인지 확인한다 (sanity check — 두 모델이 완전히 다른 판정을 내리지 않음을 검증).
2. WHEN Phase C 검증 시, THE 개발팀 SHALL 명백한 부정 키워드(`crash`, `plunge`, `recession`, `default`)를 포함한 텍스트 5건 이상이 `sentiment_score < 0`으로 분류되는지 spot check한다.
3. WHEN Phase C 검증 시, THE 개발팀 SHALL score 분포의 skewness 절대값이 **1.5 이하**인지 확인한다 (한쪽으로 극단적 편향 없음). 초과 시 입력 데이터 편향 또는 모델 문제를 조사하고 결과를 문서화한다.
4. WHEN Phase C 검증 결과가 AC 1~3 중 하나라도 실패하면, THE 개발팀 SHALL 원인 분석 후 임계값 조정(Req 9), 입력 전략 수정(Req 7), 또는 모델 재선정을 검토하고 결과를 문서화한다. Phase C 통과 전까지 `FINBERT_ENABLED`는 `false`로 유지한다.
