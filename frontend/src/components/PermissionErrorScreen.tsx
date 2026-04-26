export type ErrorKind =
  | "camera-blocked"
  | "location-blocked"
  | "location-unavailable";

interface Props {
  kind: ErrorKind;
  /** Only used for "location-unavailable"; the other two states use a deeplink anchor. */
  onRetry?: () => void;
}

/**
 * D-07 permission errors. Three states. Copy is verbatim from UI-SPEC §"Copywriting Contract".
 * `prefs:root=Safari` is a best-effort iOS deeplink — inert on most setups; the body text
 * already explains the manual path so a no-op doesn't break the user.
 */
const COPY = {
  "camera-blocked": {
    heading: "Camera blocked",
    body: "Open Settings → Safari → Camera and allow access for this site, then return and tap the red button again.",
    action: "Open Settings",
    actionHref: "prefs:root=Safari" as string | null,
  },
  "location-blocked": {
    heading: "Location blocked",
    body: "Newz groups clips by where they were recorded. Open Settings → Safari → Location and allow access, then return and tap the red button again.",
    action: "Open Settings",
    actionHref: "prefs:root=Safari" as string | null,
  },
  "location-unavailable": {
    heading: "Couldn't get your location",
    body: "Step outside or near a window and try again. Indoor GPS is unreliable.",
    action: "Try again",
    actionHref: null as string | null,
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
      {c.actionHref ? (
        <a
          href={c.actionHref}
          className="mt-6 inline-block px-6 h-14 leading-[3.5rem] rounded-full bg-gradient-to-r from-coral-light to-coral text-white font-semibold text-base"
        >
          {c.action}
        </a>
      ) : (
        <button
          type="button"
          onClick={onRetry}
          className="mt-6 inline-block px-6 h-14 rounded-full bg-gradient-to-r from-coral-light to-coral text-white font-semibold text-base"
        >
          {c.action}
        </button>
      )}
    </div>
  );
}
