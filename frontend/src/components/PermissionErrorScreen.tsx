export type ErrorKind =
  | "camera-blocked"
  | "location-blocked"
  | "location-unavailable";

interface Props {
  kind: ErrorKind;
  /** Re-attempt the permission request. iOS Safari may re-prompt if the user
   *  un-blocked in Settings between the deny and the retry tap. */
  onRetry: () => void;
}

/**
 * D-07 permission errors. Three states.
 *
 * Phase 02 (2026-04-29): the original `prefs:root=Safari` deeplink button was
 * removed — Apple killed that URL scheme on modern iOS, so the button silently
 * no-op'd. Body copy now carries the full manual path; the button is a plain
 * "Try again" that re-runs the permission flow in a fresh user gesture (which
 * may successfully re-prompt if the user toggled Settings in between).
 */
// iOS Safari note: even after a one-time grant, the platform default is "ask
// each session" — the only way to stop re-prompts is the Settings → Allow path
// below. We surface that explicitly so users don't bounce off a re-ask thinking
// the app is broken.
const IOS_PERSIST_HINT =
  "iOS asks every session unless you set this to Allow once.";

const COPY = {
  "camera-blocked": {
    heading: "Camera blocked",
    body: `${IOS_PERSIST_HINT} Settings → Apps → Safari → Camera → Allow.`,
  },
  "location-blocked": {
    heading: "Location blocked",
    body: `${IOS_PERSIST_HINT} Settings → Privacy & Security → Location Services on → scroll down → Safari Websites → While Using App.`,
  },
  "location-unavailable": {
    heading: "Couldn't get your location",
    body: "Step outside or near a window and try again. Indoor GPS is unreliable.",
  },
} as const;

export function PermissionErrorScreen({ kind, onRetry }: Props) {
  const c = COPY[kind];
  return (
    <div
      className="fixed inset-0 bg-[#0A0A0A] text-[#FAFAFA] flex flex-col items-center justify-center text-center px-6"
      style={{ minHeight: "100dvh" }}
    >
      <h1 className="text-2xl font-semibold leading-[1.2]">{c.heading}</h1>
      <p className="mt-4 max-w-sm text-base leading-[1.5] text-[#FAFAFA]">{c.body}</p>
      <button
        type="button"
        onClick={onRetry}
        className="no-blue-focus mt-6 inline-block px-8 h-12 rounded-full bg-gradient-to-r from-coral-light to-coral text-white font-semibold text-lg"
      >
        Try again
      </button>
    </div>
  );
}
