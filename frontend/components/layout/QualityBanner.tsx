import { qualityLabel } from "@/lib/format";

export function QualityBanner({
  quality,
  notes,
}: {
  quality: "degraded" | "critical";
  notes: string[];
}) {
  return (
    <div className="rounded-[24px] border border-[var(--accent-gold)]/30 bg-[rgba(203,169,106,0.1)] px-5 py-4 text-sm leading-7 text-[var(--text-secondary)]">
      <p className="section-title mb-2 text-[var(--accent-gold)]">데이터 품질</p>
      <p className="font-semibold text-[var(--text-primary)]">{qualityLabel(quality)}</p>
      {notes.length > 0 ? (
        <ul className="mt-2 list-disc pl-5">
          {notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
