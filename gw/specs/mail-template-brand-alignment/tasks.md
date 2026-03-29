# Implementation Plan: mail-template-brand-alignment

## Overview

구현은 `공통 Quiet Signal 토큰 계약 수립 -> newsletter opening shell 재설계 -> newsletter body 리듬 재구성 -> checkpoint -> confirmation shared shell 적용 -> 접근성/반응형 보강 -> review output 정리 -> 최종 checkpoint` 순서로 진행합니다. 먼저 Python/Jinja와 TypeScript가 같은 메일 토큰을 읽도록 경계를 세운 뒤, newsletter와 confirmation을 각각 그 공통 문법에 맞춰 재구성합니다.

핵심 전략은 메일 발송 로직과 데이터 계약은 유지하고, HTML 구조와 공통 디자인 자산만 재설계하는 것입니다. 각 단계는 requirements와 design의 책임 경계를 그대로 따르며, 테스트는 구현 직후 바로 붙여서 visual drift가 데이터 회귀로 번지지 않게 막습니다.

완료 시각: 2026-03-30 00:02 KST

## Tasks

- [x] 1. Quiet Signal 공통 토큰 계약과 로더 경계를 추가한다
  - [x] 1.1 메일 채널 공통 토큰 manifest를 추가한다
    - 수정 파일:
      - `schema/mail/quiet-signal.tokens.json` (new)
    - 작업 내용:
      - `Quiet Signal` 이름, 색상, typography 역할, spacing, rhythm, component token을 JSON manifest로 정의한다.
      - dark base, cyan/green 역할 분리, thin signal rail, restrained panel depth가 토큰에 직접 드러나게 구성한다.
      - email-safe inline style에 바로 넣을 수 있는 값만 저장하고 CSS variable, animation, blur 전제 값은 넣지 않는다.
      - `subtleGlow`는 공통 문법에서 제외한 상태로 문서 설계와 동일하게 유지한다.
    - _Requirements: 1.1, 1.2, 1.5, 2.5, 5.5, 6.1_
  - [x] 1.2 frontend와 Python이 같은 토큰을 읽도록 helper를 추가한다
    - 수정 파일:
      - `frontend/lib/mail/theme.ts` (new)
      - `src/morning_brief/emailer.py`
    - 작업 내용:
      - TypeScript에서 `@schema` alias로 JSON을 import하고 typed `MailTheme` helper를 제공한다.
      - Python에서 같은 JSON 파일을 읽어 `mail_theme`를 Jinja context에 넣는 loader를 추가한다.
      - 토큰 로딩 실패 시 silent fallback 없이 명시적으로 실패하도록 경계를 둔다.
      - 기존 `render_briefing_email_html()` / `render_briefing_email_text()` public signature는 유지한다.
    - _Requirements: 1.3, 1.4, 6.1, 6.2_

- [x] 2. 공통 토큰 계약에 대한 cross-runtime 테스트를 추가한다
  - [x] 2.1 Python에서 토큰 계약을 검증하는 테스트를 추가한다
    - 작업 내용:
      - token manifest 필수 키와 값이 newsletter render에 필요한 최소 계약을 만족하는지 검증한다.
      - JSON 누락 또는 schema 불일치가 실패로 드러나는지 확인한다.
    - **Property 1: shared mail theme manifest는 Python render가 요구하는 필수 키를 항상 포함한다**
    - 테스트 파일 후보: `tests/test_mail_theme_contract.py`
    - **Validates: Requirements 1.3, 6.1, 6.2**
  - [x] 2.2 TypeScript에서 같은 토큰 계약을 검증하는 테스트를 추가한다
    - 작업 내용:
      - frontend가 읽는 manifest가 same key set을 유지하는지 검증한다.
      - `MailTheme` helper가 accent, typography, CTA 관련 필수 속성을 노출하는지 확인한다.
    - **Property 2: frontend mail theme helper는 newsletter와 confirmation이 공유하는 semantic token을 항상 제공한다**
    - 테스트 파일 후보: `frontend/tests/mail-theme.test.ts`
    - **Validates: Requirements 1.1, 1.2, 6.1, 6.2**

- [x] 3. newsletter opening shell을 Quiet Signal 기준으로 재설계한다
  - [x] 3.1 base shell과 macro 계층을 토큰 기반으로 재작성한다
    - 수정 파일:
      - `src/morning_brief/templates/email_base.html.j2`
      - `src/morning_brief/templates/email_macros.html.j2`
      - `src/morning_brief/emailer.py`
    - 작업 내용:
      - base shell의 하드코딩 색상, border, text class를 `mail_theme` 기반으로 교체한다.
      - macro를 `eyebrow`, `signal_pill`, `delta_badge`, `section_label`, `utility_link`, `cta_button` 중심의 semantic 계층으로 정리한다.
      - mobile breakpoint 600px 규칙을 유지하되 spacing과 tap target 기준을 새 토큰에 맞춘다.
      - legacy hardcoded badge/pill 색상과 typography 상수를 macro 내부에서 제거한다.
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 5.2, 5.3, 6.2_
  - [x] 3.2 header와 hero를 Quiet Signal opening hierarchy로 재구성한다
    - 수정 파일:
      - `src/morning_brief/templates/email_header.html.j2`
      - `src/morning_brief/templates/email_hero.html.j2`
    - 작업 내용:
      - opening hierarchy를 `brand label -> briefing identity -> status pill -> top-line judgment -> snapshot strip` 순서로 정리한다.
      - `JudgmentBlock` 계열의 thin signal rail을 email-safe하게 옮기고, serif emphasis는 opening block에만 제한한다.
      - hero의 과도한 장식성을 줄이고, panel depth는 얕은 border/background 차이만으로 표현한다.
      - snapshot strip는 quantitative summary 역할을 유지하되 opening block과 시각적으로 분리한다.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 5.1, 5.2, 5.5_

- [x] 4. newsletter opening 재설계에 대한 렌더링 테스트를 갱신한다
  - [x] 4.1 partial/base rendering 테스트를 opening hierarchy 기준으로 갱신한다
    - 작업 내용:
      - `email_base.html.j2`, `email_header.html.j2`, `email_hero.html.j2`의 렌더링 결과에 Quiet Signal marker가 반영되는지 검증한다.
      - `lang="ko"`, `role="presentation"`, 금지 기능(no pseudo-element, no inline svg) 계약이 유지되는지 확인한다.
      - label/body/display typography 역할이 opening block에서 올바르게 분리되는지 문자열 단위로 검증한다.
    - 테스트 파일:
      - `tests/test_email_partials_rendering.py`
      - `tests/test_email_v2_rendering.py`
    - _Requirements: 1.3, 2.1, 2.2, 2.3, 5.1, 5.2, 5.3, 5.5_
  - [x] 4.2 email context integration 테스트를 opening 계약 기준으로 보강한다
    - 작업 내용:
      - `_build_email_context_v2()`가 `mail_theme`를 항상 제공하는지 검증한다.
      - 기존 header signal, snapshot badge, hero 텍스트 조립 규칙이 redesign 후에도 유지되는지 확인한다.
    - **Property 3: newsletter opening redesign 이후에도 hero 데이터 조립 계약은 유지된다**
    - 테스트 파일:
      - `tests/test_email_context_v2_integration.py`
    - **Validates: Requirements 2.2, 3.4, 6.3**

- [x] 5. Checkpoint - 공통 토큰과 newsletter opening 경로를 검증한다
  - [x] 5.1 좁은 범위 Python/frontend 테스트를 먼저 실행한다
    - `uv run pytest tests/test_mail_theme_contract.py tests/test_email_partials_rendering.py tests/test_email_v2_rendering.py tests/test_email_context_v2_integration.py`
    - `cd frontend && node --test --import tsx ./tests/mail-theme.test.ts`
    - 결과를 checkpoint에 기록한다.
    - _Requirements: 6.3_
  - [x] 5.2 관련 파일만 대상으로 lint와 타입 검증을 실행한다
    - `ruff check src/morning_brief/emailer.py tests/test_mail_theme_contract.py tests/test_email_partials_rendering.py tests/test_email_v2_rendering.py tests/test_email_context_v2_integration.py`
    - `cd frontend && npx tsc --noEmit`
    - _Requirements: 1.3, 6.2, 6.3_

- [x] 6. newsletter body와 utility sections를 Quiet Signal 리듬으로 재구성한다
  - [x] 6.1 narrative sections를 open-stack rhythm으로 바꾼다
    - 수정 파일:
      - `src/morning_brief/templates/email_news.html.j2`
    - 작업 내용:
      - 뉴스 블록을 uniform bordered box 반복에서 `meta -> headline -> body -> market meaning` 구조로 재배치한다.
      - source/meta는 mono label 계층으로, headline/body는 sans reading 계층으로, market meaning은 supportive signal 계층으로 분리한다.
      - fallback message는 기존 문구와 inclusion 규칙을 그대로 유지한다.
    - _Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 5.1, 5.2_
  - [x] 6.2 quantitative sections를 panel-split rhythm으로 바꾼다
    - 수정 파일:
      - `src/morning_brief/templates/email_market.html.j2`
      - `src/morning_brief/templates/email_btc.html.j2`
      - `src/morning_brief/templates/email_sector.html.j2`
      - `src/morning_brief/templates/email_calendar.html.j2`
    - 작업 내용:
      - summary strip와 detailed rows를 시각적으로 분리해 먼저 스캔하고 다음에 읽을 수 있게 정리한다.
      - market, bitcoin, sector, calendar가 같은 quantitative grammar를 공유하게 맞춘다.
      - 기존 데이터 payload, 표 순서, fallback 행태는 그대로 유지한다.
    - _Requirements: 3.1, 3.3, 3.4, 3.5, 3.6, 5.2_
  - [x] 6.3 footer와 utility grammar를 공통 문법으로 정리한다
    - 수정 파일:
      - `src/morning_brief/templates/email_footer.html.j2`
    - 작업 내용:
      - footer label, utility link, muted legal copy를 confirmation과 공유 가능한 톤으로 축소 정리한다.
      - unsubscribe, github/source, disclaimer 계약은 그대로 유지한다.
      - mono 과용을 줄이고 secondary metadata 역할에만 남긴다.
    - _Requirements: 1.1, 1.2, 3.1, 5.1, 5.2, 5.5_

- [x] 7. newsletter body 재설계에 대한 회귀 테스트를 추가한다
  - [x] 7.1 newsletter partial/base 테스트를 body hierarchy 기준으로 갱신한다
    - 작업 내용:
      - hero, narrative, data, utility 네 가지 리듬 marker가 각 section에 반영되는지 검증한다.
      - 뉴스의 `source/meta -> headline -> market meaning` 구조와 market/bitcoin의 summary-first 구조를 문자열 단위로 검증한다.
      - fallback section은 여전히 예측 가능한 상태 문구를 출력하는지 확인한다.
    - 테스트 파일:
      - `tests/test_email_partials_rendering.py`
      - `tests/test_email_v2_rendering.py`
    - _Requirements: 3.1, 3.2, 3.3, 3.5, 3.6, 6.3_
  - [x] 7.2 property 기반 회귀 테스트를 Quiet Signal body 계약에 맞게 보강한다
    - 작업 내용:
      - arbitrary packet 조합에서도 section inclusion, source listing, unsubscribe URL, fallback messages가 유지되는지 검증한다.
      - redesign이 visual marker만 바꾸고 데이터 semantic order는 바꾸지 않았는지 확인한다.
    - **Property 4: newsletter body redesign은 section inclusion과 data ordering 계약을 변경하지 않는다**
    - 테스트 파일:
      - `tests/test_pbt_email_redesign.py`
    - **Validates: Requirements 3.4, 3.5, 6.3**

- [x] 8. confirmation mail에 shared shell을 적용한다
  - [x] 8.1 confirmation 전용 shared shell renderer를 추가한다
    - 수정 파일:
      - `frontend/lib/mail/render-mail-shell.ts` (new)
      - `frontend/lib/mail/theme.ts`
    - 작업 내용:
      - `eyebrow -> concise headline -> support copy -> primary CTA -> fallback URL -> muted note -> utility footer` 구조를 렌더링하는 helper를 추가한다.
      - helper는 newsletter와 같은 Quiet Signal token을 사용하되 transaction 목적에 맞게 section 수를 최소화한다.
      - utility footer와 CTA tone을 newsletter와 같은 semantic grammar로 맞춘다.
    - _Requirements: 1.1, 1.2, 1.5, 4.1, 4.2, 4.4, 4.5, 6.2_
  - [x] 8.2 `buildConfirmationMail()` HTML을 shared shell 기반으로 교체한다
    - 수정 파일:
      - `frontend/lib/subscriptions/confirmation-mail.ts`
    - 작업 내용:
      - subject/text/confirmUrl/fallback plain-text 계약은 그대로 유지한다.
      - 기존 generic card HTML을 제거하고 `renderMailShell()` 기반 HTML로 교체한다.
      - opening block에서만 restrained serif emphasis를 허용하고, CTA는 홈 구독 폼과 같은 high-contrast 느낌으로 유지한다.
      - raw link fallback과 muted note를 utility grammar에 맞춰 배치한다.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.5_

- [x] 9. confirmation mail 회귀 테스트를 추가한다
  - [x] 9.1 confirmation HTML rendering 테스트를 새로 추가한다
    - 작업 내용:
      - subject/text/confirmUrl 보존 여부를 검증한다.
      - Quiet Signal shell marker, CTA/footer grammar, fallback URL 노출이 올바른지 검증한다.
      - confirmation이 newsletter보다 단순하지만 separate identity는 아닌지 문자열 단위로 확인한다.
    - 테스트 파일:
      - `frontend/tests/confirmation-mail.test.ts` (new)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 6.3_
  - [x] 9.2 subscription flow 회귀 테스트를 유지한다
    - 작업 내용:
      - confirmation HTML 변경이 request/confirm 플로우에 영향을 주지 않는지 검증한다.
      - pending 상태, token 생성, confirm success/failure 계약이 그대로 유지되는지 확인한다.
    - **Property 5: confirmation mail visual redesign 이후에도 subscription 상태 전이와 confirm URL 계약은 유지된다**
    - 테스트 파일:
      - `frontend/tests/subscription-service.test.ts`
      - 필요 시 `frontend/tests/subscriptions-api.test.ts`
    - **Validates: Requirements 4.3, 6.3**

- [x] 10. Checkpoint - newsletter/confirmation 전체 렌더 경로를 검증한다
  - [x] 10.1 Python과 frontend 테스트를 함께 실행한다
    - `uv run pytest tests/test_mail_theme_contract.py tests/test_email_partials_rendering.py tests/test_email_v2_rendering.py tests/test_email_context_v2_integration.py tests/test_pbt_email_redesign.py`
    - `cd frontend && node --test --import tsx ./tests/mail-theme.test.ts ./tests/confirmation-mail.test.ts ./tests/subscription-service.test.ts`
    - 필요 시 `cd frontend && node --test --import tsx ./tests/subscriptions-api.test.ts`를 함께 실행한다.
    - _Requirements: 6.3_
  - [x] 10.2 confirmation/newsletter 공통 토큰 사용 여부를 코드 레벨에서 확인한다
    - `rg -n "quiet-signal|mail_theme|renderMailShell|accentCyan|accentGreen" src frontend schema`
    - newsletter와 confirmation이 동일 token manifest를 참조하는지 확인한다.
    - _Requirements: 1.1, 1.2, 6.1, 6.2_

- [x] 11. 접근성, 모바일 가독성, 의도적 차이를 마무리한다
  - [x] 11.1 모바일/가독성 조정을 final polish한다
    - 수정 파일 후보:
      - `src/morning_brief/templates/email_base.html.j2`
      - `src/morning_brief/templates/email_header.html.j2`
      - `src/morning_brief/templates/email_hero.html.j2`
      - `frontend/lib/mail/render-mail-shell.ts`
      - `frontend/lib/subscriptions/confirmation-mail.ts`
    - 작업 내용:
      - 600px 이하에서 spacing, tap target, reading order가 깨지지 않도록 final spacing/font-size를 조정한다.
      - all-caps/mono 텍스트가 primary reading content에 들어가지 않도록 다시 정리한다.
      - decorative intensity가 읽기를 방해하면 signal rail과 panel depth만 남기고 더 줄인다.
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_
  - [x] 11.2 preserved/reduced/omitted hero traits를 산출물로 정리한다
    - 작업 내용:
      - 구현 완료 시 review output 또는 completion notes에 preserved/reduced/omitted 목록을 기록한다.
      - 웹과 메일 사이의 intentional difference를 암묵적으로 남기지 않고 명시한다.
      - 설계 문서와 실제 구현이 이 목록과 일치하는지 확인한다.
    - _Requirements: 6.4, 6.5 (review output tracking)_

- [x] 12. 최종 검증과 문서 정합성 점검을 수행한다
  - [x] 12.1 저장소 기본 검증 순서를 가능한 좁은 범위부터 실행한다
    - `uv run pytest tests/test_mail_theme_contract.py tests/test_email_partials_rendering.py tests/test_email_v2_rendering.py tests/test_email_context_v2_integration.py tests/test_pbt_email_redesign.py`
    - `cd frontend && npm run lint`
    - `cd frontend && npm run test`
    - 필요 시 마지막에 `make lint`, `make test`, `make typecheck`
    - 실패 시 formatter/lint/test/typecheck 중 어느 단계에서 깨졌는지 먼저 기록한다.
    - _Requirements: 6.3_
  - [x] 12.2 requirements / design / tasks 정합성을 최종 확인한다
    - 작업 내용:
      - 구현 범위가 `requirements.md`, `design.md`와 어긋나지 않는지 다시 확인한다.
      - tasks 완료 상태를 실제 실행 결과에 맞게 체크한다.
      - 남은 intentional difference나 follow-up이 있으면 completion note에 분리 기록한다.
    - _Requirements: 6.4, 6.5 (final alignment review)_

## Completion Notes

- preserved:
  - dark base, cyan/green 역할 분리, mono label, signal rail, transactional CTA, footer utility grammar를 newsletter와 confirmation에 공통 적용했다.
- reduced:
  - 홈 hero의 과한 스케일, 장식 대비, glow/noise/scanline 계열 분위기 요소는 메일에서 얕은 panel depth와 restrained serif emphasis로 축소했다.
- omitted:
  - motion, backdrop blur, 웹 전용 폰트 의존, scanline/noise texture는 email-safe 제약 때문에 넣지 않았다.
- verification:
  - 좁은 범위 Python/frontend 테스트, `PYTHON=.venv/bin/python make lint`, `PYTHON=.venv/bin/python make test`, `PYTHON=.venv/bin/python make typecheck`, `frontend npm run lint`, `frontend npm run test`까지 통과했다.
  - 기본 `make test`와 `make typecheck`는 시스템 `python3` 환경에 패키지가 없어 실패했지만, 실제 프로젝트 `.venv` 기준 전체 검증은 통과했다.
