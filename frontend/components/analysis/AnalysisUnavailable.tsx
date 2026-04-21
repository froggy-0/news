export function AnalysisUnavailable({ reason }: { reason?: string }) {
  return (
    <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4 px-6 py-20">
      <p
        className="text-[1.8rem] tracking-[-0.02em] text-white/40"
        style={{ fontFamily: "var(--font-instrument-serif)", fontStyle: "italic" }}
      >
        분석 데이터 없음
      </p>
      <p className="max-w-sm text-center text-[0.9rem] leading-7 text-[var(--text-muted)]">
        최신 분석 아티팩트를 불러오지 못했습니다. 파이프라인이 실행된 후 다시 확인해 주세요.
      </p>
      {reason && (
        <p className="mt-1 font-mono text-[0.75rem] tracking-[0.04em] text-white/28">
          {reason}
        </p>
      )}
    </div>
  );
}
