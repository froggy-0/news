import { renderMailShell } from "../mail/render-mail-shell";
import { getMailTheme } from "../mail/theme";

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

  const footerHref = new URL(input.confirmUrl).origin;
  const html = renderMailShell(
    {
      eyebrow: "SOVEREIGN BRIEF",
      headline: "구독 확인이 필요합니다",
      support: "아래 버튼을 눌러 뉴스레터 구독을 완료해 주세요.",
      ctaLabel: "구독 확인하기",
      ctaHref: input.confirmUrl,
      fallbackUrl: input.confirmUrl,
      note: "본인이 요청하지 않았다면 이 메일은 무시해도 됩니다.",
      footerHref,
      footerLabel: "Open Brief",
    },
    getMailTheme(),
  );

  return { subject, text, html };
}
