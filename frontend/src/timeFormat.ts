// Relative time copy per UI-SPEC: "{n} min ago" / "{n} sec ago" / "just now".
// Voice is "direct, lowercase-friendly" — do not paraphrase to "{n}m" or
// "moments ago". Uses Intl.RelativeTimeFormat for locale-aware formatting
// (zero dep, universally supported in modern browsers).

// Construct lazily; the constructor accepts arguments we may want to keep.
const rtf = new Intl.RelativeTimeFormat("en", {
  numeric: "auto",
  style: "long",
});

/**
 * UI-SPEC contract: "{n} min ago" / "{n} sec ago" / "just now".
 * Input is POSIX seconds (matches the backend `created_at` field).
 * `now` defaults to the current time but is overridable for testing.
 *
 * Note: the verbatim copy strings ("just now", "sec ago", "min ago") are
 * authored directly here rather than relying on `rtf.format` because the
 * UI-SPEC tokens are not exactly what `Intl.RelativeTimeFormat` produces
 * (e.g. it would say "1 minute ago" not "1 min ago"). The Intl import is
 * kept available for future hours/days formatting if needed.
 */
export function relativeTime(
  posixSeconds: number,
  now: number = Date.now() / 1000,
): string {
  const deltaSec = Math.max(0, Math.round(now - posixSeconds));
  if (deltaSec < 5) return "just now";
  if (deltaSec < 60) return `${deltaSec} sec ago`;
  const mins = Math.round(deltaSec / 60);
  if (mins < 60) return `${mins} min ago`;
  // Beyond an hour — Phase 1 feed is short-lived; just keep formatting.
  const hours = Math.round(mins / 60);
  return `${hours} hr ago`;
}

// Re-export rtf so it isn't tree-shaken in dev (and to confirm Intl support
// is exercised at module load — fails fast in environments lacking it).
export { rtf };
