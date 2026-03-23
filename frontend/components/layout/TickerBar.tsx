import type { TickerItem } from "@schema/brief.types";

export function TickerBar({ items }: { items: TickerItem[] }) {
  return (
    <section aria-label="시장 핵심 수치 티커">
      <div className="top-ticker-shell">
        <div className="ticker-marquee">
          {[false, true].map((hiddenDuplicate) => (
            <div key={String(hiddenDuplicate)} className="ticker-track" aria-hidden={hiddenDuplicate}>
              {items.map((item) => (
                <div key={`${hiddenDuplicate ? "dup" : "base"}-${item.symbol}`} className="ticker-pill">
                  <span className="ticker-symbol">{item.symbol}</span>
                  {item.value ? <span className="ticker-value numeric">{item.value}</span> : null}
                  {item.change || item.isCached ? (
                    <span className={`ticker-change numeric ${item.trend ? `is-${item.trend}` : ""}`}>
                      {item.change}
                      {item.isCached ? " · 기준값" : ""}
                    </span>
                  ) : null}
                  <span className="ticker-label">{item.label}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
