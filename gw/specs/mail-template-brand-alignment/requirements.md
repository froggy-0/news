# Requirements Document

## Introduction

현재 공개 프론트는 다크 배경, mono label, 강한 헤드라인, cyan/green 포인트를 사용하는 일관된 브랜드 톤을 갖고 있지만, newsletter HTML과 confirmation mail HTML은 각각 다른 시각 언어를 사용하고 있습니다. 이번 작업의 목적은 홈 hero 톤을 그대로 과장 복제하지 않고, 이메일에 맞는 절제된 형태로 번역해 웹과 메일이 하나의 채널처럼 느껴지게 만드는 것입니다. 범위는 메일의 시각 구조, 타이포 계층, 색상/강조 체계, 가독성, 공통 디자인 규칙 정렬이며, 메일 발송 로직과 본문 데이터 구성 규칙은 유지합니다.

## Glossary

**Front Tone**: 공개 프론트가 사용하는 브랜드 시각 언어. 다크 배경, cyan/green 포인트, mono label, 강한 헤드라인 계층을 포함한다.

**Home Hero Tone**: 홈 상단 hero가 전달하는 공격적이지만 선명한 브랜드 인상. 본 작업에서는 이를 이메일에 맞게 절제해 번역한다.

**Quiet Signal**: 홈 hero 톤을 이메일용으로 재해석한 메일 전용 aesthetic direction. 검은 배경, 얇은 signal line, cyan/green 이중 포인트, mono label, 절제된 serif emphasis를 사용하는 차분한 editorial-terminal 톤이다.

**Email-Safe Design**: 다양한 메일 클라이언트에서 깨지지 않도록 인라인 스타일, 제한된 레이아웃, 보수적인 타이포/배경 기법으로 구성한 디자인 방식.

**Newsletter Mail**: Python 파이프라인이 발송하는 장문 브리핑 메일.

**Confirmation Mail**: 구독 신청 직후 발송되는 확인 메일.

**Shared Mail Grammar**: newsletter와 confirmation mail이 공통으로 사용하는 색상, 레이블, 버튼, 여백, 헤더/푸터 규칙.

## Requirements

### Requirement 1: 메일 채널 공통 브랜드 문법 정렬

**User Story:**  
As a subscriber,  
I want newsletter와 confirmation mail이 같은 브랜드에서 온 메시지처럼 느껴지길 원한다,  
so that 웹과 이메일 경험이 하나의 채널로 인식된다.

#### Acceptance Criteria

1. WHEN newsletter mail과 confirmation mail이 렌더링될 때, THE mail templates SHALL share the same dark-base color system, accent hierarchy, label style, and footer grammar.
2. WHEN accent colors are used in mail templates, THE mail templates SHALL use green as signal/status emphasis and cyan as interaction/highlight emphasis.
3. WHEN mail layouts are updated, THE mail templates SHALL CONTINUE TO preserve email-safe HTML constraints instead of depending on web-only CSS capabilities.
4. IF a visual element from the web frontend cannot be translated safely to email, THEN THE mail templates SHALL use a simplified equivalent that preserves brand tone over exact visual duplication.
5. WHEN the mail channel aesthetic is implemented, THE mail templates SHALL follow a single named direction of `Quiet Signal` instead of mixing separate visual identities for newsletter and confirmation mail.

### Requirement 2: 홈 hero 톤의 이메일용 번역

**User Story:**  
As a reader,  
I want the email opening section to feel like the homepage hero in tone but calmer and more readable,  
so that the first screen feels branded without becoming visually overwhelming in email.

#### Acceptance Criteria

1. WHEN the newsletter header and hero are rendered, THE mail template SHALL translate the homepage hero tone into a quieter editorial-terminal presentation rather than a direct visual copy.
2. WHEN the newsletter opens, THE mail template SHALL present a clear first-screen hierarchy of brand label, briefing identity, current status signal, and top-line judgment.
3. WHEN headline emphasis is used in the newsletter hero, THE mail template SHALL limit oversized display treatment to the opening block only.
4. IF the homepage hero treatment would reduce scanability in email, THEN THE mail template SHALL reduce decorative intensity before reducing readability.
5. WHEN atmospheric framing is used in the opening block, THE mail template SHALL use no more than two email-safe mood cues selected from subtle glow, thin signal rail, and restrained panel depth.

### Requirement 3: newsletter 본문의 브랜드 정렬과 가독성 개선

**User Story:**  
As a newsletter reader,  
I want the body sections to feel consistent with the frontend’s information design,  
so that long-form market reading stays scannable and visually coherent.

#### Acceptance Criteria

1. WHEN newsletter sections are rendered, THE mail template SHALL differentiate hero, news, market, bitcoin, and footer sections with distinct hierarchy rather than repeating one flat section rhythm.
2. WHEN news items are rendered, THE mail template SHALL preserve a three-level reading hierarchy of source/meta, headline, and market meaning.
3. WHEN market and bitcoin sections are rendered, THE mail template SHALL group summary signals separately from detailed rows so that the section can be scanned before being read in depth.
4. WHEN the newsletter body is redesigned, THEN THE system SHALL CONTINUE TO preserve the existing data payload, unsubscribe link behavior, and section inclusion rules.
5. IF a section has no usable data, THEN THE mail template SHALL preserve the current fallback message behavior instead of collapsing the layout unpredictably.
6. WHEN section hierarchy is expressed in the newsletter body, THE mail template SHALL use different visual rhythms for hero, narrative reading blocks, and quantitative tables instead of styling all sections as uniform bordered blocks.

### Requirement 4: confirmation mail의 브랜드 통합

**User Story:**  
As a new subscriber,  
I want the confirmation mail to look like the same product family as the homepage and newsletter,  
so that the subscription flow feels trustworthy and consistent.

#### Acceptance Criteria

1. WHEN confirmation mail is rendered, THE mail template SHALL use the same shared mail grammar as the newsletter mail.
2. WHEN the confirmation CTA is rendered, THE mail template SHALL use the same accent system and tone family as the homepage subscription form while remaining email-safe.
3. WHEN confirmation mail is redesigned, THEN THE system SHALL CONTINUE TO preserve the existing subject, confirmation URL, success path, and fallback plain-text content contract.
4. IF confirmation mail must remain simpler than the newsletter mail, THEN THE mail template SHALL reduce section count without introducing a separate visual identity.
5. WHEN confirmation mail is simplified for transactional clarity, THE mail template SHALL still preserve the `Quiet Signal` opening hierarchy of brand label, concise headline, supporting copy, and primary CTA.

### Requirement 5: 이메일 가독성 및 접근성 기준

**User Story:**  
As a reader on desktop or mobile mail clients,  
I want the email to remain easy to scan and read,  
so that the branded design does not harm comprehension.

#### Acceptance Criteria

1. WHEN body copy is rendered in newsletter or confirmation mail, THE mail template SHALL avoid excessively small all-caps text for primary reading content.
2. WHEN metadata labels are rendered, THE mail template SHALL keep decorative mono styling limited to labels, pills, and secondary metadata.
3. WHEN the email is viewed on screens 600px wide or smaller, THE mail template SHALL preserve readable spacing, tap-safe CTA sizing, and a stable reading order.
4. IF decorative contrast or spacing choices compete with content legibility, THEN THE mail template SHALL prioritize reading comfort over stylistic intensity.
5. WHEN typography is assigned across the mail templates, THE mail template SHALL preserve the role split of mono for labels, restrained serif emphasis for select display moments, and sans-serif for body reading content.

### Requirement 6: 공통 구현 경계와 회귀 검증

**User Story:**  
As a maintainer,  
I want the mail design alignment to be implemented through a clear shared structure,  
so that future frontend or email changes do not reintroduce brand drift.

#### Acceptance Criteria

1. WHEN the redesign is implemented, THE mail rendering layer SHALL define a shared set of email-safe brand tokens or shared mail primitives used by both newsletter and confirmation mail.
2. WHEN newsletter and confirmation templates are updated, THE implementation SHALL minimize duplicated visual constants across independently maintained HTML strings and template fragments.
3. WHEN the redesign is complete, THE automated tests SHALL cover both newsletter and confirmation rendering contracts that are expected to remain unchanged.
4. WHEN the redesign is validated, THE review output SHALL identify any remaining intentional differences between web and email presentation rather than leaving them implicit.
5. WHEN the shared mail grammar is documented or reviewed, THE review output SHALL explicitly name which homepage hero traits were preserved, which were reduced, and which were intentionally omitted for email safety.
