import rawTheme from "@schema/mail/quiet-signal.tokens.json";

type MailThemeRecord = Record<string, string>;

export interface MailTheme {
  name: "quiet-signal";
  colors: MailThemeRecord;
  typography: MailThemeRecord;
  spacing: MailThemeRecord;
  layout: MailThemeRecord;
  rhythm: {
    hero: "signal-rail";
    narrative: "open-stack";
    data: "panel-split";
    utility: "compressed";
  };
  components: {
    pill: MailThemeRecord;
    badge: MailThemeRecord;
    cta: MailThemeRecord;
    footerLink: MailThemeRecord;
  };
  mood: {
    signalRail: boolean;
    panelDepth: boolean;
    subtleGlow: boolean;
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function assertStringRecord(value: unknown, key: string): MailThemeRecord {
  if (!isRecord(value)) {
    throw new Error(`Invalid mail theme: ${key} must be an object.`);
  }

  const entries = Object.entries(value);
  if (entries.length === 0) {
    throw new Error(`Invalid mail theme: ${key} must not be empty.`);
  }

  for (const [entryKey, entryValue] of entries) {
    if (typeof entryValue !== "string") {
      throw new Error(`Invalid mail theme: ${key}.${entryKey} must be a string.`);
    }
  }

  return value as MailThemeRecord;
}

function assertMailTheme(value: unknown): MailTheme {
  if (!isRecord(value)) {
    throw new Error("Invalid mail theme: theme payload must be an object.");
  }

  if (value.name !== "quiet-signal") {
    throw new Error("Invalid mail theme: name must be 'quiet-signal'.");
  }

  if (!isRecord(value.rhythm)) {
    throw new Error("Invalid mail theme: rhythm must be an object.");
  }

  if (!isRecord(value.components)) {
    throw new Error("Invalid mail theme: components must be an object.");
  }

  if (!isRecord(value.mood)) {
    throw new Error("Invalid mail theme: mood must be an object.");
  }

  const rhythm = value.rhythm;
  const mood = value.mood;

  if (
    rhythm.hero !== "signal-rail" ||
    rhythm.narrative !== "open-stack" ||
    rhythm.data !== "panel-split" ||
    rhythm.utility !== "compressed"
  ) {
    throw new Error("Invalid mail theme: rhythm keys must match Quiet Signal contract.");
  }

  if (
    typeof mood.signalRail !== "boolean" ||
    typeof mood.panelDepth !== "boolean" ||
    typeof mood.subtleGlow !== "boolean"
  ) {
    throw new Error("Invalid mail theme: mood values must be booleans.");
  }

  const theme = {
    name: value.name,
    colors: assertStringRecord(value.colors, "colors"),
    typography: assertStringRecord(value.typography, "typography"),
    spacing: assertStringRecord(value.spacing, "spacing"),
    layout: assertStringRecord(value.layout, "layout"),
    rhythm: {
      hero: "signal-rail",
      narrative: "open-stack",
      data: "panel-split",
      utility: "compressed",
    },
    components: {
      pill: assertStringRecord(value.components.pill, "components.pill"),
      badge: assertStringRecord(value.components.badge, "components.badge"),
      cta: assertStringRecord(value.components.cta, "components.cta"),
      footerLink: assertStringRecord(value.components.footerLink, "components.footerLink"),
    },
    mood: {
      signalRail: mood.signalRail,
      panelDepth: mood.panelDepth,
      subtleGlow: mood.subtleGlow,
    },
  } satisfies MailTheme;

  return theme;
}

export const quietSignalTheme = assertMailTheme(rawTheme);

export function getMailTheme(): MailTheme {
  return quietSignalTheme;
}
