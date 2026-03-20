export async function GET() {
  const body = `# SOVEREIGN BRIEF

이 서비스는 미국 기술주와 비트코인 시장 흐름을 한국어 브리핑으로 제공합니다.

## 주요 경로
- /
- /archive
- /rss.xml

## 업데이트 주기
- KST 오전 8시 기준 공개 경험을 목표로 합니다.
- 실제 공개 시점은 파이프라인 완료와 데이터 게시 시점을 따릅니다.
`;

  return new Response(body, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
    },
  });
}
