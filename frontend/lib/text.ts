const HANGUL_RE = /[가-힣]/;

export function containsKorean(text: string | null | undefined): boolean {
  return Boolean(text && HANGUL_RE.test(text));
}

// LLM이 "없음" 같은 무의미 플레이스홀더를 반환하는 경우 null로 처리
const MEANINGLESS_KO = new Set(["없음", "해당없음", "없음.", "없음,", "N/A", "n/a", "null"]);

export function filterMeaningless(s: string | null | undefined): string | null {
  const t = s?.trim();
  if (!t || MEANINGLESS_KO.has(t)) return null;
  return t;
}
