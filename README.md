# Morning Market Brief (US Tech + BTC)

매일 오전 08:00(KST)에 미국 기술주 + 비트코인 중심 `Morning Market Brief`를 생성하고 이메일로 전송하는 단일 Python 프로젝트입니다.

## 기능
- 밤사이 시장 데이터 수집
  - 거시: 미국 국채금리, 달러 인덱스, VIX
  - 증시: S&P500, NASDAQ, SOXX
  - AI/빅테크: NVDA, MSFT, AAPL, AMZN, GOOGL, META, AMD, TSM, ASML, AVGO
  - 비트코인: BTC 현물, 주요 BTC ETF, 시장 심리(Fear & Greed)
- 우선 소스 기반 뉴스 수집
  - Reuters, Bloomberg, WSJ, FT, CNBC, CoinDesk 우선
- LLM 기반 한국어 브리핑 생성
  - 고정 포맷
  - 해석 중심
  - 3~5개 핵심 뉴스 반영
- Gmail API 이메일 발송
- 스케줄 실행(매일 08:00 KST)

## 프로젝트 구조
- `main.py`: 실행 엔트리포인트
- `src/morning_brief/config.py`: 환경설정 로더
- `src/morning_brief/data/market.py`: 시장 데이터 수집
- `src/morning_brief/data/news.py`: 뉴스 수집
- `src/morning_brief/briefing.py`: LLM 브리핑 생성
- `src/morning_brief/emailer.py`: Gmail 발송
- `src/morning_brief/pipeline.py`: 전체 파이프라인
- `src/morning_brief/scheduler.py`: 일일 스케줄러

## 1) 설치
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) 환경변수
```bash
cp .env.example .env
```

`.env` 필수 항목:
- `OPENAI_API_KEY`
- `GMAIL_SENDER`
- `GMAIL_RECIPIENT`
- `GMAIL_CREDENTIALS_FILE` (`credentials.json` 경로)

선택 항목:
- `NEWSAPI_KEY` (없으면 RSS 폴백)
- `SEND_EMAIL=false` (로컬 테스트용)

## 3) Gmail API 준비
1. Google Cloud Console에서 Gmail API 활성화
2. OAuth Client ID(Desktop App) 생성
3. OAuth JSON 다운로드 후 `credentials.json`으로 저장
4. 첫 실행 시 브라우저 인증 완료하면 `token.json` 자동 생성

## 4) 실행
즉시 1회 실행:
```bash
python main.py once
```

스케줄 실행(매일 08:00 KST):
```bash
python main.py schedule
```

## 5) 출력
- 최종 브리핑만 생성
- 파일 저장: `outputs/brief_YYYYMMDD.md`
- 이메일 제목: `Morning Market Brief | YYYY-MM-DD`

## 운영 메모
- 초기 버전은 비용 최소화를 위해 단일 프로세스 기반으로 동작합니다.
- 장기 운영 시 `systemd`, `pm2`, Docker restart policy 등으로 `python main.py schedule` 프로세스 상시 실행을 권장합니다.
