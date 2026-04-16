# Tasks → 리포트 완성 가능성 검토

> docs/tasks/ 하위 3개 문서의 수정 사항을 모두 적용한 뒤,
> 백필 + sentiment-join 재실행으로 report-draft.md가 완성되는지 검증합니다.

---

## 실행 순서와 리포트 빈칸 매핑

### Phase 1: 코드 수정 (tasks 3개 문서)

| 단계 | 태스크 문서 | 수정 항목 | 리포트 빈칸 해소 |
|---|---|---|---|
| 1-1 | pre-backfill §1 | Lag-1 적용 (news_sentiment_mean, fng_value) | §4 Granger 검정의 look-ahead bias 제거 |
| 1-2 | pre-backfill §2 | 백필 why_it_matters 통일 | §3 FinBERT 시계열 일관성 |
| 1-3 | pre-backfill §3 | 백필 batch_size 16으로 통일 | §3 FinBERT 재현성 |
| 2-1 | statistical-rigor §3 | **백필 JSON 구조 수정** (meta 래퍼 → flat) | **§2 품질 게이트 29일 제외 해소 → 180행 확보** |
| 2-2 | statistical-rigor §1 | ADF 대상에 predictor 추가 | §4.1 ADF 검정 완전성 |
| 2-3 | statistical-rigor §1 | ADF 비정상 시 Granger 경고 | §4 결과 해석 신뢰도 |
| 2-4 | statistical-rigor §4 | 다중 검정 보정 메타데이터 | §4.2 Granger 해석 엄밀성 |
| 2-5 | statistical-rigor §5 | 쌍별 effective_rows 기록 | §4.2 진단 정보 |
| 2-6 | statistical-rigor §7 | F-statistic 기록 | §4.2 효과 크기 |
| 3-1 | hybrid-index §1 | 0~100 스케일링 | §5 하이브리드 지수 해석 가능 |
| 3-2 | hybrid-index §2 | PC1 부호 안정성 | §5 시계열 연속성 |
| 3-3 | hybrid-index §3 | VIX 소스 추가 | §5 가이드라인 충족 |
| 3-4 | hybrid-index §4 | _hybrid_signal_label 중복 제거 | 유지보수 |

### Phase 2: 백필 실행

```bash
# 1. 백필 (CoinDesk + Alpaca → FinBERT → R2 업로드)
python -m scripts.backfill ...  # 180일+ 분량

# 2. sentiment-join 재실행
SENTIMENT_JOIN_LOOKBACK_DAYS=200 make sentiment-join
```

### Phase 3: 리포트 데이터 추출 & 빈칸 채우기

```bash
python scripts/extract_report_data.py
```

---

## 리포트 빈칸 해소 여부 (report-draft.md 섹션별)

| 리포트 섹션 | 현재 상태 | Phase 1+2 후 | 추가 작업 필요 |
|---|---|---|---|
| §1 데이터 수집 | ✅ 완성 | ✅ | — |
| §2 품질 게이트 / 이상치 | ⚠️ 1행, 0% | ✅ 180행+, 유의미한 비율 | — |
| §3 FinBERT 감성 분석 | ✅ 모델 구성 완성 | ✅ | — |
| §3.4 감성 점수 분포 | ⚠️ 단일 날짜 | ✅ 180일 시계열 분포 | 히스토그램/KDE 차트 생성 필요 |
| §4.1 ADF 검정 결과 | ❌ 빈 테이블 | ✅ 실제 값 채워짐 | — |
| §4.2 Granger P-value 테이블 | ❌ 빈 테이블 | ✅ 실제 값 채워짐 | — |
| §4.2 Granger P-value 차트 | ❌ 설계만 | ⚠️ **차트 생성 코드 없음** | 🔴 아래 참조 |
| §5 PCA hybrid_index | ❌ 미실행 | ✅ 실제 값 채워짐 | — |
| §7 시장 데이터 스냅샷 | ✅ 완성 | ✅ | — |
| §8 Parquet 마스터 테이블 | ⚠️ 1행 | ✅ 180행+ | — |
| §9 연구 한계 | ✅ 완성 | ✅ 일부 해소 | 한계 섹션 업데이트 |
| §10 향후 계획 | ✅ | ✅ 대부분 해소 | 잔여 항목 업데이트 |

---

## 🔴 tasks에 없는 누락 작업

### 1. 시각화 / 차트 생성 코드

tasks 3개 문서는 **파이프라인 코드 수정**만 다룹니다. 리포트에 필요한 차트를 실제로 그리는 코드가 없습니다.

필요한 차트:

| 차트 | 입력 | 현재 상태 |
|---|---|---|
| Granger P-value 시차별 선 그래프 | `granger_results` 메타데이터 | ❌ 코드 없음 |
| FinBERT 감성 점수 히스토그램/KDE | `news_sentiment_mean` 시계열 | ❌ 코드 없음 |
| hybrid_index 시계열 그래프 | `hybrid_index` 컬럼 | ❌ 코드 없음 |
| ADF 결과 요약 테이블 | `adf` 메타데이터 | `extract_report_data.py`에 텍스트 출력만 |
| VIF 진단 테이블 | `vif_diagnostics` 메타데이터 | 동일 |

`scripts/extract_report_data.py`는 텍스트 출력만 하고 차트를 생성하지 않습니다.

### 2. 리포트 자동 갱신

tasks 수정 → 백필 → sentiment-join 후, `report-draft.md`의 빈칸(TBD, —)을 실제 값으로 채우는 자동화가 없습니다. 수동으로 `extract_report_data.py` 출력을 복사해야 합니다.

### 3. 백필 실행 절차 문서

tasks에 코드 수정 방법은 있지만, 백필 실행 자체의 구체적 절차가 없습니다:
- CoinDesk/Alpaca API 키 설정
- 백필 대상 기간 지정
- R2 업로드 인증 설정
- 실행 명령어
- 예상 소요 시간

### 4. news_sentiment_mean → fng_value 직접 Granger 쌍

report-draft.md §4.2에서 "직접 인과성 검정이 필요하면 GRANGER_PAIRS에 추가 필요"라고 명시했지만, tasks 문서 어디에도 이 수정이 포함되어 있지 않습니다. 가이드라인의 "뉴스 감성 지표와 F&G Index 간의 Granger 인과성"을 직접 검정하려면 추가해야 합니다.

### 5. 리포트 §9 연구 한계 업데이트

tasks 수정 후 일부 한계가 해소되므로(Lag-1 적용, 다중 검정 보정 등), §9를 업데이트해야 합니다. 반대로 새로 생기는 한계도 있습니다(min-max 스케일링의 미래 데이터 범위 초과 가능성 등).

---

## 요약: 완성까지의 갭

```
현재 tasks 3개 문서
  ├── 파이프라인 코드 수정 13건 ✅ 충분
  ├── 백필 JSON 구조 수정 1건 ✅ 충분
  └── 통계 검정 개선 6건 ✅ 충분

누락된 작업
  ├── 🔴 시각화 차트 생성 (3종 이상)
  ├── 🔴 GRANGER_PAIRS에 (sentiment → fng_value) 추가
  ├── 🟡 백필 실행 절차 문서
  ├── 🟡 리포트 빈칸 자동 갱신 (또는 수동 절차)
  └── 🟡 리포트 §9 한계 섹션 업데이트
```

**tasks 코드 수정 + 백필 + sentiment-join 재실행**으로 데이터는 확보됩니다.
그러나 **차트 생성**과 **sentiment → fng_value 직접 Granger 쌍**이 없으면 리포트의 핵심 시각화와 가이드라인 요구사항이 빠집니다.
