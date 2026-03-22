import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="site-footer-shell">
      <div className="site-footer-grid">
        <div className="space-y-4">
          <div>
            <p className="section-title">SOVEREIGN BRIEF</p>
            <h2 className="site-footer-heading">한국장 오픈 전에 핵심 흐름을 읽는 공개 브리핑 데스크</h2>
          </div>
          <p className="site-footer-copy">
            장전 판단에 필요한 핵심 수치, 선별 뉴스, 공식 X 시그널, 비트코인과 ETF 흐름을 같은 지면에서 빠르게 훑도록 구성했습니다.
          </p>
        </div>

        <div className="site-footer-column">
          <p className="section-title">데이터 범위</p>
          <ul className="site-footer-list">
            <li>거시 · 미국 지수 · 주요 기술주 · 비트코인</li>
            <li>신뢰 뉴스 소스와 공식 X 시그널</li>
            <li>공식 ETF 보유 현황과 아카이브 발행본</li>
          </ul>
        </div>

        <div className="site-footer-column">
          <p className="section-title">운영 기준</p>
          <ul className="site-footer-list">
            <li>한국 시간 기준으로 발행하며 필요 시 재정리본을 갱신</li>
            <li>값이 없는 핵심 블록은 상태를 드러내고 유지</li>
            <li>추정성 강한 수치는 사용자 화면에서 최소화</li>
          </ul>
        </div>

        <div className="site-footer-column">
          <p className="section-title">바로가기</p>
          <div className="site-footer-links">
            <Link href="/archive">발행 아카이브</Link>
            <Link href="/privacy">운영 원칙</Link>
            <a href="/rss.xml">RSS 피드</a>
            <a href="/llms.txt">LLM 인덱스</a>
          </div>
        </div>
      </div>

      <div className="site-footer-meta">
        <p>시장 판단을 돕는 정보 브리핑이며 투자 권유가 아닙니다.</p>
        <p className="numeric">최신 공개판 · KST 기준</p>
      </div>
    </footer>
  );
}
