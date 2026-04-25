interface Props {
  recording: boolean;
  /** 0..1, ring fill amount over the 30s cap. */
  progress: number;
  /** false dims the button and blocks taps — used to enforce min recording length. */
  canStop?: boolean;
  onTap: () => void;
}

const RADIUS = 37;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/**
 * D-03 ring-fill record button. 80px outer, r=37, 6px stroke. Stop-glyph swap when recording.
 * Verbatim from PATTERNS.md lines 530-560.
 */
export function RecordButton({ recording, progress, canStop = true, onTap }: Props) {
  const blocked = recording && !canStop;
  return (
    <button
      type="button"
      onClick={onTap}
      disabled={blocked}
      aria-label={
        recording
          ? canStop
            ? "Stop recording"
            : "Recording — wait for minimum duration"
          : "Start recording"
      }
      className="absolute left-1/2 -translate-x-1/2 z-20"
      style={{
        bottom: "calc(16px + env(safe-area-inset-bottom))",
        opacity: blocked ? 0.5 : 1,
      }}
    >
      <svg width="80" height="80" viewBox="0 0 80 80">
        <circle
          cx="40"
          cy="40"
          r={RADIUS}
          fill="none"
          stroke="#262626"
          strokeWidth="6"
        />
        {recording && (
          <circle
            cx="40"
            cy="40"
            r={RADIUS}
            fill="none"
            stroke="#EF4444"
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={CIRCUMFERENCE * (1 - Math.max(0, Math.min(1, progress)))}
            transform="rotate(-90 40 40)"
            style={{ transition: "stroke-dashoffset 100ms linear" }}
          />
        )}
        {recording ? (
          <rect x="32" y="32" width="16" height="16" rx="2" fill="#EF4444" />
        ) : (
          <circle cx="40" cy="40" r="28" fill="#EF4444" />
        )}
      </svg>
    </button>
  );
}
