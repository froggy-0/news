import type { MailTheme } from "./theme";

export interface MailShellInput {
  eyebrow: string;
  headline: string;
  support: string;
  ctaLabel?: string;
  ctaHref?: string;
  fallbackUrl?: string;
  note?: string;
  footerHref?: string;
  footerLabel?: string;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function styleAttr(style: Record<string, string | undefined>): string {
  return Object.entries(style)
    .filter(([, value]) => Boolean(value))
    .map(([key, value]) => `${key}:${value}`)
    .join(";");
}

export function renderMailShell(input: MailShellInput, theme: MailTheme): string {
  const eyebrow = escapeHtml(input.eyebrow);
  const headline = escapeHtml(input.headline);
  const support = escapeHtml(input.support);
  const fallbackUrl = input.fallbackUrl ? escapeHtml(input.fallbackUrl) : "";
  const note = input.note ? escapeHtml(input.note) : "";
  const footerHref = input.footerHref ? escapeHtml(input.footerHref) : "";
  const footerLabel = input.footerLabel ? escapeHtml(input.footerLabel) : "";

  const bodyStyle = styleAttr({
    margin: "0",
    padding: "32px 16px",
    background: theme.colors.shellBg,
    color: theme.colors.textStrong,
    "font-family": theme.typography.bodySans,
  });
  const shellWrapStyle = styleAttr({
    width: "100%",
    background: theme.colors.shellBg,
  });
  const shellStyle = styleAttr({
    width: theme.layout.confirmationWidth,
    "max-width": theme.layout.confirmationWidth,
    margin: "0 auto",
    border: `1px solid ${theme.colors.border}`,
    background: theme.colors.shellBg,
  });
  const heroPanelStyle = styleAttr({
    padding: theme.spacing.shellY,
    background: theme.colors.panelBg,
  });
  const railStyle = styleAttr({
    "border-left": theme.mood.signalRail ? `3px solid ${theme.colors.accentGreen}` : undefined,
    padding: "0 0 0 18px",
  });
  const eyebrowStyle = styleAttr({
    margin: "0",
    color: theme.colors.accentGreen,
    "font-family": theme.typography.labelMono,
    "font-size": "10px",
    "font-weight": "700",
    "letter-spacing": "0.22em",
    "text-transform": "uppercase",
  });
  const headlineStyle = styleAttr({
    margin: "14px 0 0",
    color: theme.colors.textStrong,
    "font-family": theme.typography.displaySerif,
    "font-size": "30px",
    "font-style": "italic",
    "font-weight": "700",
    "letter-spacing": "-0.04em",
    "line-height": "1.12",
  });
  const supportStyle = styleAttr({
    margin: "12px 0 0",
    color: theme.colors.textBody,
    "font-family": theme.typography.bodySans,
    "font-size": "15px",
    "line-height": "1.84",
  });
  const ctaStyle = styleAttr({
    display: "inline-block",
    "min-height": theme.layout.ctaMinHeight,
    padding: theme.components.cta.padding,
    border: `1px solid ${theme.components.cta.accentBorder}`,
    "border-radius": theme.components.cta.radius,
    background: theme.components.cta.background,
    color: theme.components.cta.text,
    "font-family": theme.typography.bodySans,
    "font-size": "14px",
    "font-weight": "800",
    "line-height": "1.2",
    "text-decoration": "none",
  });
  const dividerStyle = styleAttr({
    margin: "18px 0 0",
    "border-top": `1px solid ${theme.colors.border}`,
  });
  const footerPanelStyle = styleAttr({
    padding: `18px ${theme.spacing.shellY} ${theme.spacing.shellY}`,
    background: theme.colors.panelBgStrong,
    "border-top": `1px solid ${theme.colors.border}`,
  });
  const mutedStyle = styleAttr({
    margin: "12px 0 0",
    color: theme.colors.textMuted,
    "font-family": theme.typography.bodySans,
    "font-size": "13px",
    "line-height": "1.78",
  });
  const footerLinkStyle = styleAttr({
    color: theme.colors.textMuted,
    "font-family": theme.typography.labelMono,
    "font-size": theme.components.footerLink.fontSize,
    "letter-spacing": theme.components.footerLink.letterSpacing,
    "text-transform": "uppercase",
    "text-decoration": "none",
  });

  const ctaHtml =
    input.ctaLabel && input.ctaHref
      ? `<p style="margin:18px 0 0;"><a class="cta-link" href="${escapeHtml(input.ctaHref)}" style="${ctaStyle}">${escapeHtml(input.ctaLabel)}</a></p>`
      : "";
  const fallbackHtml = fallbackUrl
    ? `<p style="${mutedStyle};word-break:break-all">버튼이 열리지 않으면 아래 링크를 복사해 주세요.<br>${fallbackUrl}</p>`
    : "";
  const noteHtml = note ? `<p style="${mutedStyle}">${note}</p>` : "";
  const footerLinkHtml =
    footerHref && footerLabel
      ? `<p style="margin:10px 0 0;"><a href="${footerHref}" style="${footerLinkStyle}">${footerLabel}</a></p>`
      : "";

  return [
    "<!doctype html>",
    `<html lang="ko"><body style="${bodyStyle}">`,
    `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="${shellWrapStyle}" data-mail-shell="quiet-signal">`,
    "<tr>",
    '<td align="center">',
    `<table role="presentation" width="${theme.layout.confirmationWidth}" cellpadding="0" cellspacing="0" border="0" style="${shellStyle}" data-mail-shell="quiet-signal">`,
    "<tr>",
    `<td style="${heroPanelStyle}" data-mail-rhythm="hero">`,
    `<div style="${railStyle}">`,
    `<p style="${eyebrowStyle}">${eyebrow}</p>`,
    `<h1 style="${headlineStyle}">${headline}</h1>`,
    `<p style="${supportStyle}">${support}</p>`,
    ctaHtml,
    fallbackHtml,
    noteHtml,
    `<div style="${dividerStyle}"></div>`,
    "</div>",
    "</td>",
    "</tr>",
    "<tr>",
    `<td style="${footerPanelStyle}" data-mail-rhythm="utility">`,
    `<p style="margin:0;color:${theme.colors.textMuted};font-family:${theme.typography.labelMono};font-size:${theme.components.footerLink.fontSize};letter-spacing:${theme.components.footerLink.letterSpacing};text-transform:uppercase;">SOVEREIGN BRIEF</p>`,
    `<p style="margin:8px 0 0;color:${theme.colors.textMuted};font-family:${theme.typography.bodySans};font-size:11px;line-height:1.8;">본 메일은 구독 확인 요청에 대한 transactional 안내입니다.</p>`,
    footerLinkHtml,
    "</td>",
    "</tr>",
    "</table>",
    "</td>",
    "</tr>",
    "</table>",
    "</body></html>",
  ].join("");
}
