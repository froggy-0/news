# 이메일 `핵심 뉴스` 잘림 원인 분석

기준 자료:
- 실제 발송 본문: `/Users/giwon/code/news/docs/email.log`
- GitHub Actions 로그: `/Users/giwon/code/news/docs/pipeline.log`
- 코드 기준:
  - `/Users/giwon/code/news/src/morning_brief/briefing.py`
  - `/Users/giwon/code/news/src/morning_brief/brief_formatting.py`
  - `/Users/giwon/code/news/src/morning_brief/emailer.py`
  - `/Users/giwon/code/news/src/morning_brief/config.py`

## 결론

이번 `핵심 뉴스` 잘림은 **이메일 템플릿이나 Gmail 렌더링 단계에서 잘린 것이 아니라**,  
**OpenAI가 생성한 브리핑 원문 Section 4-2(핵심 뉴스 5선)가 이미 중간에서 끊긴 상태로 저장되었고**,  
이 잘린 원문이 이메일로 그대로 렌더링된 문제다.

판정을 분리하면 아래와 같다.

1. 직접 원인:
   - 브리핑 생성/재작성 결과의 `Section 4-2`가 중간에서 잘렸다.
   - 이메일은 이 잘린 `Section 4-2`를 그대로 파싱해 보냈다.

2. 구조적 원인:
   - 현재 프롬프트는 `Section 0~6` 전체와 `핵심 뉴스 5선(뉴스당 5~8문장)`까지 요구한다.
   - 반면 OpenAI 생성/재작성 호출은 `max_output_tokens=2300`으로 제한돼 있다.
   - 이 조합 때문에 **출력 토큰 예산 부족으로 응답이 중간에 끊겼을 가능성이 매우 높다.**

3. 관측성 한계:
   - 현재 코드는 `response.status`나 `incomplete_details`를 기록하지 않는다.
   - 따라서 이번 로그만으로 `max_output_tokens` 초과를 100% 단정할 수는 없지만,
     **생성 단계 출력 잘림이 먼저 발생했다는 점은 확정**이고,
     그 잘림의 가장 유력한 원인은 **출력 토큰 상한**이다.

## 증거

### 1. 실제 메일 본문이 `핵심 뉴스` ④에서 끊겨 있다

`/Users/giwon/code/news/docs/email.log`에는 아래처럼 ④ 뉴스 헤드라인이 중간에서 끝난다.

- `④ Grayscale, SEC 해석 언급으로 암호자산 규제 명확성 부`

그 직후 바로 `■ BTC & 크립토` 섹션으로 넘어간다.  
즉, 메일 본문 안에서 `핵심 뉴스` 블록의 나머지 줄들이 비어 있는 상태다.

이건 Gmail이 메일 뒤쪽을 전체적으로 잘라낸 모습과 다르다.  
메일 맨 아래 `시장 지표`, 푸터, 구독 해지 문구는 정상적으로 남아 있기 때문이다.

## 2. 파이프라인 로그가 이메일 발송 전에 이미 `Section 4-2` 잘림을 감지했다

`/Users/giwon/code/news/docs/pipeline.log`에는 이메일 발송 전에 아래 경고가 있다.

- `2026-03-19 09:12:04`  
  `Section 4-2 (핵심 뉴스 5선)가 중간에 잘려있고 ①~⑤ 항목이 완성되지 않음.`
- `2026-03-19 09:12:50`  
  `재작성 뒤에도 보완점이 남아 있어요: 섹션 4-2가 5개 뉴스 요건에서 중간에 잘려 있음—④ 항목이 불완전합니다.`

즉, **이메일 렌더링 이전 단계에서 이미 브리핑 원문이 잘려 있었다.**

## 3. 이메일러는 잘린 원문을 그대로 렌더링할 뿐, 본문을 별도로 자르지 않는다

이메일 발송 경로는 다음과 같다.

- `/Users/giwon/code/news/src/morning_brief/emailer.py:1444`
  - HTML/텍스트 메일 본문을 생성
- `/Users/giwon/code/news/src/morning_brief/templates/email_v2.txt.j2:22-31`
  - `news_items`를 순회하며 그대로 출력
- `/Users/giwon/code/news/src/morning_brief/brief_formatting.py:409-459`
  - `Section 4-2` 텍스트를 `parse_news_items()`로 파싱

여기서 중요한 점:

- `parse_news_items()`는 뉴스 블록을 잘라서 요약하지 않는다.
- `email_v2.txt.j2`도 각 뉴스 항목을 그대로 출력한다.
- 별도의 문자 수 제한, 줄 수 제한, 본문 절단 로직은 확인되지 않았다.

즉, **이메일 템플릿이 뉴스를 자른 것이 아니라, 입력으로 받은 뉴스 블록이 이미 잘린 상태였다.**

## 4. 현재 생성 호출은 출력 상한 2300 토큰이다

`/Users/giwon/code/news/src/morning_brief/config.py:124-128`

- `OPENAI_MAX_OUTPUT_TOKENS`
- 기본값 `2300`

`/Users/giwon/code/news/src/morning_brief/briefing.py:833-840`

- 브리핑 생성 호출에 `max_output_tokens=settings.openai_max_output_tokens`

같은 상한은 재작성 루프에도 그대로 적용된다.

`/Users/giwon/code/news/src/morning_brief/brief_review.py:246-251`

- 재작성 응답도 `max_output_tokens=settings.openai_max_output_tokens`

## 5. 그런데 프롬프트가 요구하는 출력 길이는 현재 상한보다 훨씬 크다

`/Users/giwon/code/news/src/morning_brief/prompts/brief_input.j2`와  
`/Users/giwon/code/news/src/morning_brief/prompts/brief_instructions.j2`는 아래를 동시에 요구한다.

- Section 0~6 전체
- Section 4-2 핵심 뉴스 5선
- 뉴스당:
  - 한국어 헤드라인
  - 5~8문장 서술 단락
  - 원문 링크
  - 핵심 한줄
- Section 4-3 섹터/자산 영향 매핑
- Section 5-1~5-3 추가 설명
- Section 6 이벤트 캘린더

즉, **요구 출력량이 매우 큰데 생성/재작성 모두 2300 토큰 상한을 갖고 있다.**

이 조합은 `Section 4-2`처럼 중간 이후 섹션이 잘릴 가능성을 높인다.

## 왜 "토큰 제한"이라고 보나

이번 건을 "이메일 버그"가 아니라 "생성 단계 truncation"으로 보는 이유는 명확하다.

- 메일 본문이 뉴스 ④에서 끊긴 상태로 저장돼 있다.
- 파이프라인 로그가 이메일 발송 전에 이미 `Section 4-2` 잘림을 감지했다.
- 이메일 템플릿에는 해당 블록을 자르는 로직이 없다.

여기서 한 단계 더 들어가면, 왜 생성 단계가 잘렸는지의 가장 유력한 설명은 `max_output_tokens=2300`이다.

다만 현재 로그에는 아래 정보가 없다.

- `response.status`
- `response.incomplete_details`
- `finish_reason`

따라서 **"출력 토큰 상한 도달"을 직접 증명하는 로그는 현재 남아 있지 않다.**
하지만 코드 구조와 프롬프트 요구량을 보면, **토큰 제한이 실질적인 근본 원인일 가능성이 매우 높다.**

## 이번 건에서 제외할 수 있는 원인

### 1. Gmail/메일 클라이언트가 임의로 본문을 잘랐다

아니다.

- 메일 뒤쪽 `BTC & 크립토`, `시장 지표`, 푸터는 정상적으로 남아 있다.
- 메일 전체가 뒤에서 잘린 게 아니라, `핵심 뉴스` 블록 내부만 불완전하다.

### 2. 텍스트 템플릿이 뉴스 항목 수를 제한해서 ④ 이후를 버렸다

아니다.

- 텍스트 템플릿은 `news_items`를 순회 출력만 한다.
- 별도 길이 절단 로직은 없다.

### 3. 이메일 단계에서 HTML -> 텍스트 변환 중 잘렸다

가능성 낮음.

- 현재 메일은 plain text 파트와 HTML 파트를 각각 생성해 첨부한다.
- plain text 템플릿 자체가 이미 `news_items` 기반으로 렌더링된다.

## 코드상 2차 문제

생성 단계 truncation이 발생해도 현재 코드는 이를 충분히 막지 못한다.

### 1. 불완전 응답 감지가 약하다

`/Users/giwon/code/news/src/morning_brief/briefing.py:841-844`

- `response.output_text`만 비어 있지 않으면 계속 진행한다.
- `incomplete` 여부를 보지 않는다.

### 2. 부분 fallback이 "부분적으로 잘린 섹션"을 복구하지 못한다

`/Users/giwon/code/news/src/morning_brief/briefing.py:244-284`

- `_fallback_if_incomplete()`는 **비어 있는 섹션**만 fallback으로 채운다.
- 섹션이 존재하지만 내부 뉴스 ④가 반쯤 잘린 경우는 그대로 남을 수 있다.

이번 로그에서도 실제로:

- `brief_review_failed`는 `section_4_2` 불완전을 잡았고
- 최종 partial fallback은 `section_6`만 채웠다
- 결과적으로 잘린 `section_4_2`는 메일까지 전달됐다

## 최종 판정

### 확정된 사실

- 메일에서 `핵심 뉴스`가 잘린 직접 원인은 **브리핑 원문 Section 4-2가 생성 단계에서 이미 잘린 상태였기 때문**이다.
- **이메일 템플릿/Gmail 렌더링 버그는 직접 원인이 아니다.**

### 가장 유력한 근본 원인

- 현재 프롬프트가 요구하는 출력량 대비
- `OPENAI_MAX_OUTPUT_TOKENS=2300`이 낮고
- 코드가 `incomplete` 응답을 감지/차단하지 않기 때문에

**생성 또는 재작성 단계에서 출력 토큰 예산 부족으로 truncation이 발생했을 가능성이 가장 높다.**

### 남은 관측성 공백

현재 로그만으로는 아래를 직접 확인할 수 없다.

- 이번 응답이 실제로 `max_output_tokens` 때문에 멈췄는지
- 아니면 모델이 구조를 지키지 못한 채 임의 중단했는지

이건 `response.status`, `incomplete_details`, `finish_reason`를 로그에 남기지 않기 때문이다.

## 한 줄 요약

이번 이슈는 **메일에서 잘린 것이 아니라, OpenAI가 만든 Section 4-2가 이미 잘린 상태였고 그 잘린 결과가 이메일로 전달된 문제**다.  
그리고 그 잘림의 가장 유력한 근본 원인은 **과도한 출력 계약 대비 낮은 `max_output_tokens(2300)`와 incomplete 응답 미감지**다.
