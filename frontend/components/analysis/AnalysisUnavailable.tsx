export function AnalysisUnavailable({ reason }: { reason?: string }) {
  return (
    <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4 px-6 py-20">
      <p className="text-[1.8rem] font-bold text-[var(--smoke)]/50">
        Analysis Unavailable
      </p>
      <p className="max-w-sm text-center text-[0.9rem] leading-7 text-[var(--text-muted)]">
        Could not load the latest analysis artifact. Check back after the next pipeline run.
      </p>
      {reason && (
        <p className="mt-1 text-[0.75rem] tracking-[0.04em] text-[var(--taupe)]/45">
          {reason}
        </p>
      )}
    </div>
  );
}
