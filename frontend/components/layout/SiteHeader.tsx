import { formatIssueDate, formatIssueTime } from "@/lib/format";

export function SiteHeader({
  generatedAt,
  variant = "home",
  showNews = true,
  showSignals = true,
}: {
  generatedAt: string;
  variant?: "home" | "archive";
  showNews?: boolean;
  showSignals?: boolean;
}) {
  const isArchive = variant === "archive";
  const issueDate = formatIssueDate(generatedAt);
  const issueTime = `${formatIssueTime(generatedAt)} KST`;

  return (
    <>
      <nav className="top-nav-shell">
        <div className="top-nav-inner">
          <div className="top-brand-lockup">
            <div className="space-y-1">
              <p className="nav-brand">SOVEREIGN BRIEF</p>
              <p className="nav-subtitle">해외 시장 뉴스 · 공식 시그널 브리프</p>
            </div>
          </div>
          <div className="hidden items-center gap-7 lg:flex">
            {isArchive ? (
              <>
                <a className="nav-link" href="/">
                  실시간 홈
                </a>
                <a className="nav-link" href="/archive">
                  발행 아카이브
                </a>
              </>
            ) : (
              <>
                <a className="nav-link" href="#brief">
                  오늘의 판단
                </a>
                <a className="nav-link" href="#map">
                  브리핑 지도
                </a>
                {showNews ? (
                  <a className="nav-link" href="#news">
                    핵심 뉴스
                  </a>
                ) : null}
                {showSignals ? (
                  <a className="nav-link" href="#signals">
                    공식 X 시그널
                  </a>
                ) : null}
                <a className="nav-link" href="/archive">
                  발행 아카이브
                </a>
              </>
            )}
          </div>
          <div className="top-time-block">
            <p className="numeric nav-time">{issueTime}</p>
          </div>
          <a className="hero-shortcut-link lg:hidden" href={isArchive ? "/" : "/archive"}>
            {isArchive ? "실시간 홈" : "발행 아카이브"}
          </a>
        </div>
      </nav>

      <header className="hero-shell">
        <div className="hero-meta-row">
          <div className="status-chip">
            <span className="status-dot" />
            {isArchive ? "아카이브 발행본" : "오늘 발행본"}
          </div>
          <div className="hero-date-block">
            <p className="eyebrow">발행일</p>
            <p className="numeric hero-date">{issueDate}</p>
          </div>
        </div>

        <div className="hero-copy">
          <p className="hero-kicker">
            {isArchive ? "저장된 발행본 아카이브" : "노이즈는 우리가, 판단은 당신이"}
          </p>
          <h1 className="display-headline">
            {isArchive ? (
              <>
                저장된 발행본을
                <br />
                날짜별로 다시 읽습니다
              </>
            ) : (
              <>
                주도권 있는 투자자를 위한
                <br />
                데이터 인텔리전스
              </>
            )}
          </h1>
          <p className="hero-support">
            {isArchive
              ? "홈의 실시간 스트림 대신, 발행 시점 기준으로 저장된 판단과 뉴스 흐름을 다시 확인할 수 있습니다."
              : "소버린 브리핑은 흩어진 영문 기사와 공식 시그널을 한국어 판단으로 압축해, 한국 시간 아침 한 화면에서 빠르게 읽게 합니다."}
          </p>
          {!isArchive ? (
            <div className="hero-shortcuts lg:hidden">
              <a className="hero-shortcut-link" href="#brief">
                오늘의 판단
              </a>
              <a className="hero-shortcut-link" href="#map">
                브리핑 지도
              </a>
              {showNews ? (
                <a className="hero-shortcut-link" href="#news">
                  핵심 뉴스
                </a>
              ) : null}
              {showSignals ? (
                <a className="hero-shortcut-link" href="#signals">
                  공식 X 시그널
                </a>
              ) : null}
            </div>
          ) : null}
        </div>
      </header>
    </>
  );
}
