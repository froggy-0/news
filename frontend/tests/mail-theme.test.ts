import test from "node:test";
import assert from "node:assert/strict";

import { getMailTheme, quietSignalTheme } from "../lib/mail/theme";

test("quiet signal theme exposes shared token contract", () => {
  const theme = getMailTheme();

  assert.equal(theme.name, "quiet-signal");
  assert.equal(theme.colors.shellBg, "#050505");
  assert.equal(theme.colors.accentCyan, "#00ffff");
  assert.equal(theme.colors.accentGreen, "#00ff66");
  assert.equal(theme.rhythm.hero, "signal-rail");
  assert.equal(theme.rhythm.narrative, "open-stack");
  assert.equal(theme.rhythm.data, "panel-split");
  assert.equal(theme.rhythm.utility, "compressed");
});

test("quiet signal theme export remains stable", () => {
  assert.deepEqual(quietSignalTheme, getMailTheme());
  assert.equal(typeof quietSignalTheme.typography.labelMono, "string");
  assert.equal(typeof quietSignalTheme.typography.bodySans, "string");
  assert.equal(typeof quietSignalTheme.typography.displaySerif, "string");
});
