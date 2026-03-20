import type { TickerItem } from "@schema/brief.types";

export function TickerBar({ items }: { items: TickerItem[] }) {
  const loopItems = [...items, ...items];

  return (
    <section aria-label="시장 핵심 수치 티커">
      <div className="top-ticker-shell hidden md:block">
        <div className="ticker-marquee">
          {loopItems.map((item, index) => (
            <div key={`${item.symbol}-${index}`} className="ticker-pill">
              <span className="ticker-symbol">{item.symbol}</span>
              <span className="ticker-value numeric">{item.value ?? "확인 중"}</span>
              <span className={`ticker-change numeric ${item.trend ? `is-${item.trend}` : ""}`}>
                {item.change ?? "상태 확인 중"}
                {item.isCached ? " · CACHED" : ""}
              </span>
              <span className="ticker-label">{item.label}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="ticker-static-shell md:hidden">
        <div className="ticker-static-grid">
          {items.map((item) => (
            <div key={item.symbol} className="ticker-static-pill">
              <div className="ticker-static-row">
                <span className="ticker-symbol">{item.symbol}</span>
                <span className={`ticker-change numeric ${item.trend ? `is-${item.trend}` : ""}`}>
                  {item.change ?? "확인 중"}
                </span>
              </div>
              <p className="ticker-static-value numeric">{item.value ?? "확인 중"}</p>
              <p className="ticker-static-label">{item.label}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
