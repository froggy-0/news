/**
 * Analysis 페이지 Playwright QA 스펙.
 *
 * 이 파일은 playwright-capture.sh 방식과 함께 동작하는 문서용 스펙입니다.
 * 아래 명령으로 스크린샷 캡처 가능:
 *   cd frontend && npm run dev:fixture &
 *   npm run qa:playwright http://localhost:3000/analysis analysis
 *
 * 수동 검증 체크리스트:
 *   [x] /analysis 페이지 정상 로드 (타이틀: Sentiment Insight)
 *   [x] AnalysisMasthead: 기준일·생성일·검정 수(63)·보정(FDR_BH) 표시
 *   [x] GrangerSymmetric: forward/reverse 헤더, 행 버튼 렌더
 *   [x] GrangerSymmetric: 행 클릭 시 L1/L2/L3 lag 상세 노출 + 나머지 행 디밍
 *   [x] PcaTabs: FULL 탭 기본 활성 (설명분산 80.2%)
 *   [x] PcaTabs: CORE 클릭 → 설명분산 75.1% 표시, FULL 내용 사라짐
 *   [x] PcaTabs: VIF 제거 변수 테이블 (vif>10) 표시
 *   [x] "Granger causality ≠ causation" 주의 문구 표시
 *   [x] stale 배너 없음 (fixture referenceDate=오늘)
 *   [ ] stale 배너 표시: fixture referenceDate를 3일 전으로 변경 후 확인
 *   [ ] AnalysisUnavailable: BRIEF_DATA_SOURCE 미설정 + R2 URL 없을 때 "분석 데이터 없음" 표시
 *   [ ] granger.executed=false fixture: "Granger 검정 미수행" 안내 표시
 */

export {};
