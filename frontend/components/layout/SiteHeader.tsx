import { formatIssueDate, formatIssueTime } from "@/lib/format";

export function SiteHeader({
  generatedAt,
  variant = "home",
}: {
  generatedAt: string;
  variant?: "home" | "archive";
}) {
  const isArchive = variant === "archive";

  return (
    <>
      <nav className="top-nav-shell">
        <div className="top-nav-inner">
          <div className="top-brand-lockup">
            <div className="brand-mark">
              <span className="brand-mark-dot" />
            </div>
            <div className="space-y-1">
              <p className="nav-brand">SOVEREIGN BRIEF</p>
              <p className="nav-subtitle">미국 기술주 · 비트코인 시장 브리핑</p>
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
                <a className="nav-link" href="#news">
                  뉴스 플로우
                </a>
                <a className="nav-link" href="#market">
                  마켓 보드
                </a>
                <a className="nav-link" href="#btc">
                  BTC 데스크
                </a>
                <a className="nav-link" href="/archive">
                  발행 아카이브
                </a>
              </>
            )}
          </div>
          <div className="top-time-block">
            <p className="eyebrow">PUBLIC EDITION</p>
            <p className="numeric nav-time">{formatIssueTime(generatedAt)} KST</p>
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
            <p className="eyebrow">발행 시각</p>
            <p className="numeric hero-date">{formatIssueDate(generatedAt)}</p>
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
                아침 한 번으로
                <br />
                오늘 장의 확신을
              </>
            )}
          </h1>
          <p className="hero-support">
            {isArchive
              ? "홈의 실시간 스트림 대신, 발행 시점 기준으로 저장된 판단과 뉴스 흐름을 다시 확인할 수 있습니다."
              : "소버린 브리핑은 FRED·X 공식 시그널·ETF 흐름을 한국 시간 아침에 한 화면으로 큐레이션합니다. 남는 건 당신의 판단뿐."}
          </p>
          {!isArchive ? (
            <div className="hero-shortcuts lg:hidden">
              <a className="hero-shortcut-link" href="#brief">
                오늘의 판단
              </a>
              <a className="hero-shortcut-link" href="#news">
                뉴스 플로우
              </a>
              <a className="hero-shortcut-link" href="#market">
                마켓 보드
              </a>
              <a className="hero-shortcut-link" href="#btc">
                BTC 데스크
              </a>
            </div>
          ) : null}
        </div>
      </header>
    </>
  );
}
