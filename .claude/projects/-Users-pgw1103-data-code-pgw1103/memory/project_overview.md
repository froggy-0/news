---
name: project_overview
description: Morning Market Brief 프로젝트 — 미국 기술주+BTC 시장 브리핑 자동 생성/발송 파이프라인
type: project
---

## Morning Market Brief (US Tech + BTC)

매일 08:00 KST에 미국 기술주 + 비트코인 중심 시장 브리핑을 자동 생성하여 이메일로 발송하는 Python 파이프라인.

**핵심 흐름**: 시장 데이터 수집 → 뉴스 수집 → OpenAI 브리핑 생성(+검수) → Gmail 발송

**LLM 역할 분리**:
- Perplexity: 뉴스 수집 + BTC ETF structured response
- Grok: 공식 X 실시간 시그널
- OpenAI: 브리핑 생성 및 검수

**시장 데이터 소스**: FRED(거시) → Stooq(가격) → yfinance(폴백), CoinGecko(BTC)

**뉴스 소스**: Perplexity Search(메인) → legacy fallback(RSS, NewsAPI)

**실행**: `python3 main.py once` / GitHub Actions 매일 자동

**Why:** 개인 투자 의사결정을 위한 아침 시장 요약 자동화
**How to apply:** 수집 신뢰성, 데이터 품질, LLM provider 역할 고정 원칙을 항상 존중
