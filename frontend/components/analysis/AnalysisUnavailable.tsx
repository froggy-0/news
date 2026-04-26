export function AnalysisUnavailable({ reason }: { reason?: string }) {
  return (
    <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4 px-6 py-20">
      <p
        className="text-[1.8rem] tracking-[-0.02em] text-white/40"
        style={{ fontFamily: "var(--font-instrument-serif)", fontStyle: "italic" }}
      >
        Analysis Unavailable
      </p>
      <p className="max-w-sm text-center text-[0.9rem] leading-7 text-[var(--text-muted)]">
        Could not load the latest analysis artifact. Check back after the next pipeline run.
      </p>
      {reason && (
        <p className="mt-1 font-mono text-[0.75rem] tracking-[0.04em] text-white/28">
          {reason}
        </p>
      )}
    </div>
  );
}
