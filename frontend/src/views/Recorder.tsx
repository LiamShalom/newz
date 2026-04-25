import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PrimingModal } from "../components/PrimingModal";
import { CameraView } from "../components/CameraView";
import { CameraFlipButton } from "../components/CameraFlipButton";
import { RecordButton } from "../components/RecordButton";
import { RetakeScreen } from "../components/RetakeScreen";
import {
  PermissionErrorScreen,
  type ErrorKind,
} from "../components/PermissionErrorScreen";
import { pickMimeType } from "../lib/mimeLadder";
import { getPositionWithTimeout } from "../lib/getPositionWithTimeout";
import { postClip } from "../api";
import { enqueue } from "../uploadQueue";

/**
 * Phase 1 capture loop state machine. Eight phases:
 *
 *   priming -> acquiring -> ready -> recording -> retake
 *                                              \-> retake -> gps-pending -> submitting -> nav("/")
 *                                                                       \-> error -> (retry edge)
 *
 * Critical iOS Safari constraints (PITFALLS.md #3, #13):
 * - getUserMedia must be called inside the user-gesture stack frame. PrimingModal's
 *   onContinue runs synchronously from the click; the await on getUserMedia is the
 *   first microtask, which iOS still treats as inside the gesture window.
 * - MIME ladder is consulted via pickMimeType(); when it returns undefined the
 *   constructor option is omitted entirely (CAP-10 / Pitfall #3).
 * - <video> elements all carry autoPlay + muted + playsInline; missing playsInline
 *   makes iOS open native fullscreen and break the UX.
 *
 * D-07 conflict resolution: GPS lookup BLOCKS submit. CAP-07 ("never blocks") is
 * overridden in Phase 1 — null-GPS clips are not accepted.
 */

type Phase =
  | { kind: "priming" }
  | { kind: "acquiring"; facing: "environment" | "user" }
  | { kind: "ready"; facing: "environment" | "user" }
  | { kind: "recording"; facing: "environment" | "user"; startedAt: number }
  | { kind: "retake"; blob: Blob; mimeType: string }
  | { kind: "gps-pending"; blob: Blob; mimeType: string }
  | { kind: "submitting"; blob: Blob; mimeType: string }
  | { kind: "error"; error: ErrorKind };

const RECORD_CAP_SEC = 30; // CAP-05 hard cap

export function Recorder() {
  const navigate = useNavigate();
  const [phase, setPhase] = useState<Phase>({ kind: "priming" });
  const [progress, setProgress] = useState(0); // 0..1 for ring fill

  // Refs for things React must not re-render against.
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Cleanup helpers — called on every transition out of an active stream/recorder state
  // and on unmount. Without the stream cleanup, iOS keeps the camera indicator on after
  // the user navigates away (T-04-01).
  const cleanupStream = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  };
  const cleanupTimer = () => {
    if (tickRef.current) clearInterval(tickRef.current);
    tickRef.current = null;
  };

  // Acquire camera + audio (D-04: audio ON, rear default).
  const acquire = async (facing: "environment" | "user"): Promise<void> => {
    setPhase({ kind: "acquiring", facing });
    try {
      // STACK.md: getUserMedia must be called from the same gesture stack as the user tap.
      // PrimingModal's onContinue runs synchronously; this await is the first microtask
      // and iOS Safari accepts it inside the gesture window.
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: facing },
        audio: true,
      });
      cleanupStream();
      streamRef.current = stream;
      setPhase({ kind: "ready", facing });
    } catch (err) {
      const name = (err as Error & { name?: string })?.name;
      if (name === "NotAllowedError") {
        setPhase({ kind: "error", error: "camera-blocked" });
      } else {
        // NotFoundError, OverconstrainedError, etc. — same screen for Phase 1 simplicity.
        setPhase({ kind: "error", error: "camera-blocked" });
      }
    }
  };

  const flipCamera = async () => {
    if (phase.kind !== "ready") return;
    const next = phase.facing === "environment" ? "user" : "environment";
    await acquire(next);
  };

  const startRecording = () => {
    if (phase.kind !== "ready" || !streamRef.current) return;
    const mimeType = pickMimeType();
    // CAP-10: omit the option entirely when nothing matches (Safari is happier with no mimeType).
    const recorder = new MediaRecorder(
      streamRef.current,
      mimeType ? { mimeType } : {},
    );
    chunksRef.current = [];
    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size) chunksRef.current.push(e.data);
    };
    recorder.onstop = () => {
      cleanupTimer();
      const finalMime = recorder.mimeType || mimeType || "video/webm";
      const blob = new Blob(chunksRef.current, { type: finalMime });
      cleanupStream();
      setProgress(0);
      setPhase({ kind: "retake", blob, mimeType: finalMime });
    };
    recorderRef.current = recorder;
    recorder.start();
    const startedAt = performance.now();
    setPhase({ kind: "recording", facing: phase.facing, startedAt });

    tickRef.current = setInterval(() => {
      const elapsed = (performance.now() - startedAt) / 1000;
      const p = Math.min(elapsed / RECORD_CAP_SEC, 1);
      setProgress(p);
      // CAP-05: hard 30s cap. Recorder.stop() fires onstop -> retake transition.
      if (elapsed >= RECORD_CAP_SEC && recorder.state === "recording") {
        recorder.stop();
      }
    }, 100);
  };

  const stopRecording = () => {
    const r = recorderRef.current;
    if (r && r.state === "recording") r.stop();
  };

  const submitClip = async () => {
    if (phase.kind !== "retake") return;
    setPhase({
      kind: "gps-pending",
      blob: phase.blob,
      mimeType: phase.mimeType,
    });

    // D-07: GPS is BLOCKING. CAP-07 conflict resolved in favor of D-07.
    const pos = await getPositionWithTimeout(5000);
    if (pos.kind === "denied") {
      setPhase({ kind: "error", error: "location-blocked" });
      return;
    }
    if (
      pos.kind === "unavailable" ||
      pos.kind === "timeout" ||
      pos.kind === "unsupported"
    ) {
      setPhase({ kind: "error", error: "location-unavailable" });
      return;
    }

    setPhase({
      kind: "submitting",
      blob: phase.blob,
      mimeType: phase.mimeType,
    });
    const filename = `clip.${phase.mimeType.includes("mp4") ? "mp4" : "webm"}`;
    const ts = Date.now() / 1000;

    try {
      await postClip({
        blob: phase.blob,
        filename,
        lat: pos.lat,
        lng: pos.lng,
        ts,
      });
      navigate("/");
    } catch {
      // Network / 5xx — CAP-09 enqueue. 4xx would also land here; uploadQueue.flush
      // drops 4xx as permanent on the next visit, so this is safe.
      await enqueue({
        blob: phase.blob,
        mimeType: phase.mimeType,
        lat: pos.lat,
        lng: pos.lng,
        ts,
      });
      navigate("/"); // feed will show prior clips; queue retries on next visit
    }
  };

  // After priming continue, kick off acquire (D-04 rear default).
  const onPrimingDone = () => {
    void acquire("environment");
  };

  // Kill stream/timer on unmount. Without this the iOS camera indicator stays on
  // after the user navigates away mid-recording (T-04-01).
  useEffect(() => {
    return () => {
      cleanupTimer();
      cleanupStream();
    };
  }, []);

  // Render —————————————————————————————————————————————

  if (phase.kind === "priming") {
    return <PrimingModal onContinue={onPrimingDone} />;
  }

  if (phase.kind === "error") {
    const onRetry =
      phase.error === "location-unavailable"
        ? () => {
            void acquire("environment");
          }
        : undefined;
    return <PermissionErrorScreen kind={phase.error} onRetry={onRetry} />;
  }

  if (
    phase.kind === "retake" ||
    phase.kind === "gps-pending" ||
    phase.kind === "submitting"
  ) {
    return (
      <RetakeScreen
        blob={phase.blob}
        submitting={phase.kind !== "retake"}
        onRetake={() => {
          void acquire("environment");
        }}
        onSubmit={() => {
          void submitClip();
        }}
      />
    );
  }

  // acquiring | ready | recording — all share the camera viewport
  const facing =
    phase.kind === "acquiring" ||
    phase.kind === "ready" ||
    phase.kind === "recording"
      ? phase.facing
      : "environment";
  const isRecording = phase.kind === "recording";

  return (
    <div className="fixed inset-0 bg-[#0A0A0A]" style={{ height: "100dvh" }}>
      <CameraView stream={streamRef.current} />
      {!isRecording && phase.kind === "ready" && (
        <CameraFlipButton
          facing={facing}
          onFlip={() => {
            void flipCamera();
          }}
        />
      )}
      <RecordButton
        recording={isRecording}
        progress={progress}
        onTap={isRecording ? stopRecording : startRecording}
      />
    </div>
  );
}
