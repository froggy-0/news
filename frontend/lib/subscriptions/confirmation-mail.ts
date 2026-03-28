export function buildConfirmationMail(input: {
  confirmUrl: string;
}): { subject: string; text: string; html: string } {
  const subject = "[SOVEREIGN BRIEF] 구독 확인이 필요합니다";
  const text = [
    "[SOVEREIGN BRIEF] 구독 확인이 필요합니다",
    "",
    "아래 링크를 눌러 구독을 완료해 주세요.",
    input.confirmUrl,
    "",
    "본인이 요청하지 않았다면 이 메일은 무시해도 됩니다.",
  ].join("\n");

  const html = [
    "<!doctype html>",
    '<html lang="ko"><body style="font-family:Arial,sans-serif;background:#0a0a0a;color:#e5e2e1;padding:32px;">',
    '<div style="max-width:560px;margin:0 auto;border:1px solid rgba(255,255,255,0.12);background:#131313;padding:28px;border-radius:12px;">',
    '<p style="font-size:12px;letter-spacing:0.18em;text-transform:uppercase;color:#02e600;">SOVEREIGN BRIEF</p>',
    '<h1 style="font-size:28px;line-height:1.2;margin:0 0 16px;">구독 확인이 필요합니다</h1>',
    '<p style="color:#c6c6c6;line-height:1.7;margin:0 0 24px;">아래 버튼을 눌러 뉴스레터 구독을 완료해 주세요.</p>',
    `<p style="margin:0 0 24px;"><a href="${input.confirmUrl}" style="display:inline-block;padding:14px 22px;border-radius:999px;background:#02e600;color:#081008;font-weight:700;text-decoration:none;">구독 확인하기</a></p>`,
    `<p style="color:#8f8f8f;line-height:1.7;word-break:break-all;margin:0 0 12px;">버튼이 열리지 않으면 아래 링크를 복사해 주세요.<br />${input.confirmUrl}</p>`,
    '<p style="color:#8f8f8f;line-height:1.7;margin:0;">본인이 요청하지 않았다면 이 메일은 무시해도 됩니다.</p>',
    "</div>",
    "</body></html>",
  ].join("");

  return { subject, text, html };
}
