import test from "node:test";
import assert from "node:assert/strict";

import { buildConfirmationMail } from "../lib/subscriptions/confirmation-mail";

test("confirmation mail keeps contract while using Quiet Signal shell", () => {
  const confirmUrl = "https://brief.example.com/subscribe/confirm?token=test-token";
  const mail = buildConfirmationMail({ confirmUrl });

  assert.equal(mail.subject, "[SOVEREIGN BRIEF] 구독 확인이 필요합니다");
  assert.match(mail.text, /구독 확인이 필요합니다/);
  assert.match(mail.text, /subscribe\/confirm\?token=test-token/);
  assert.match(mail.html, /data-mail-shell="quiet-signal"/);
  assert.match(mail.html, /data-mail-rhythm="hero"/);
  assert.match(mail.html, /data-mail-rhythm="utility"/);
  assert.match(mail.html, /SOVEREIGN BRIEF/);
  assert.match(mail.html, /구독 확인하기/);
  assert.match(mail.html, /transactional 안내/);
  assert.match(mail.html, /href="https:\/\/brief\.example\.com"/);
});

test("confirmation mail exposes fallback URL without losing HTML escaping", () => {
  const confirmUrl = "https://brief.example.com/subscribe/confirm?token=test-token&source=email";
  const mail = buildConfirmationMail({ confirmUrl });

  assert.match(mail.html, /https:\/\/brief\.example\.com\/subscribe\/confirm\?token=test-token&amp;source=email/);
  assert.match(mail.html, /href="https:\/\/brief\.example\.com"/);
  assert.doesNotMatch(mail.html, /<script/i);
});
