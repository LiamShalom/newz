import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PrimingModal } from "../components/PrimingModal";
import { CameraView } from "../components/CameraView";
import { BottomTabBar } from "../components/BottomTabBar";
import { CameraFlipButton } from "../components/CameraFlipButton";
import { CameraUploadButton } from "../components/CameraUploadButton";
import { RecordButton } from "../components/RecordButton";
import { RetakeScreen } from "../components/RetakeScreen";
import { AddToHomeScreenHint } from "../components/AddToHomeScreenHint";
import {
  PermissionErrorScreen,
  type ErrorKind,
} from "../components/PermissionErrorScreen";
import { pickMimeType } from "../lib/mimeLadder";
import {
  getPositionWithTimeout,
  type PositionResult,
} from "../lib/getPositionWithTimeout";
import { postClip } from "../api";
import { enqueue } from "../uploadQueue";
import { setUploadStatus } from "../uploadStatusBus";

/**
 * Phase 1 capture loop state machine. Phases:
 *
 *   uninitialized -> acquiring -> ready -> recording -> retake
 *                                                    \-> retake -> gps-pending -> submitting -> nav("/")
 *                                                                              \-> error -> (retry edge)
 *
 * Phase 02 change (2026-04-29): dropped PrimingModal. The record button itself
 * is the gesture anchor — first tap fires getUserMedia + getCurrentPosition
 * synchronously in the same gesture frame, so both browser dialogs chain
 * back-to-back. Permissions settle before recording starts; the old
 * "location-blocked at post" iPhone-Safari dead-end is no longer reachable on
 * the happy path.
 *
 * Critical iOS Safari constraints (PITFALLS.md #3, #13):
 * - getUserMedia must be called inside the user-gesture stack frame. The
 *   record button onClick is that frame; getUserMedia and getCurrentPosition
 *   are both called synchronously inside it (no await between them).
 * - MIME ladder is consulted via pickMimeType(); when it returns undefined the
 *   constructor option is omitted entirely (CAP-10 / Pitfall #3).
 * - <video> elements all carry autoPlay + muted + playsInline; missing
 *   playsInline makes iOS open native fullscreen and break the UX.
 *
 * D-07 conflict resolution: GPS lookup BLOCKS submit. CAP-07 ("never blocks")
 * is overridden in Phase 1 — null-GPS clips are not accepted.
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
const MIN_RECORD_SEC = 5; // Marengo requires >=4s; 5 leaves a buffer for trim/encoding

// Cross-session flag: once both permissions are granted on this device/origin,
// skip the priming popup on every subsequent visit. Stored in localStorage so it
// survives tab close. The acquire() catch path below removes the flag on a
// getUserMedia failure, which covers the case where iOS revoked access between
// sessions — so a stale flag never traps the user.
const PERMS_GRANTED_KEY = "perms_granted";

export function Recorder() {
  const navigate = useNavigate();
  const [phase, setPhase] = useState<Phase>(() =>
    localStorage.getItem(PERMS_GRANTED_KEY) === "1"
      ? { kind: "acquiring", facing: "environment" }
      : { kind: "priming" },
  );
  const [progress, setProgress] = useState(0);

  // Refs for things React must not re-render against.
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // GPS sampled at record-tap. By the time min-record (5s) elapses the lookup
  // is normally settled, so submit feels instant. Permission was granted in
  // initializePermissions() so this read is dialog-free.
  const gpsPromiseRef = useRef<Promise<PositionResult> | null>(null);

  const cleanupStream = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  };
  const cleanupTimer = () => {
    if (tickRef.current) clearInterval(tickRef.current);
    tickRef.current = null;
  };

  /**
   * First-tap permission acquisition. Fired from the record button when phase
   * is "uninitialized". Both browser dialogs (camera/mic, then location) fire
   * synchronously inside this single gesture frame.
   *
   * Why synchronous (no await between getUserMedia and getCurrentPosition):
   * iOS Safari only honors permission dialogs within the user-gesture stack.
   * `await` introduces a microtask boundary — by the time it resolves, we may
   * be outside the gesture window and the second dialog gets blocked. So we
   * fire both promises synchronously, then await both in parallel.
   */
  const initializePermissions = () => {
    setPhase({ kind: "acquiring", facing: "environment" });

    // Both calls fire synchronously here — same gesture frame.
    const camPromise = navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: "environment",
        width: { ideal: 1920 },
        height: { ideal: 1080 },
        frameRate: { ideal: 30 },
      },
      audio: true,
    });
    const geoPromise = getPositionWithTimeout(10000);

    void Promise.allSettled([camPromise, geoPromise]).then(([camResult, geoResult]) => {
      if (camResult.status === "rejected") {
        setPhase({ kind: "error", error: "camera-blocked" });
        // If the location promise still resolves, it's harmless — we already
        // routed to the error screen.
        return;
      }
      if (geoResult.status === "rejected") {
        // getPositionWithTimeout never rejects (always resolves with a tagged
        // union). Defensive — treat as unavailable.
        cleanupStream();
        camResult.value.getTracks().forEach((t) => t.stop());
        setPhase({ kind: "error", error: "location-unavailable" });
        return;
      }

      const pos = geoResult.value;
      if (pos.kind === "denied") {
        camResult.value.getTracks().forEach((t) => t.stop());
        setPhase({ kind: "error", error: "location-blocked" });
        return;
      }
      if (pos.kind === "unavailable" || pos.kind === "timeout" || pos.kind === "unsupported") {
        camResult.value.getTracks().forEach((t) => t.stop());
        setPhase({ kind: "error", error: "location-unavailable" });
        return;
      }

      // Both granted — attach stream, transition to ready. User taps record
      // again to actually start recording.
      localStorage.setItem(PERMS_GRANTED_KEY, "1");
      cleanupStream();
      streamRef.current = camResult.value;
      setPhase({ kind: "ready", facing: "environment" });
    });
  };

  // Re-acquire camera (e.g. after retake or flip, or on mount when permissions
  // were already granted in this session). Granted permissions don't re-prompt,
  // so this is dialog-free on the warm path.
  const acquire = async (facing: "environment" | "user"): Promise<void> => {
    setPhase({ kind: "acquiring", facing });
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: facing,
          width: { ideal: 1920 },
          height: { ideal: 1080 },
          frameRate: { ideal: 30 },
        },
        audio: true,
      });
      cleanupStream();
      streamRef.current = stream;
      setPhase({ kind: "ready", facing });
    } catch {
      // Cached perms got revoked between sessions, or hardware error.
      // Clear the cache flag so the next visit re-shows priming.
      localStorage.removeItem(PERMS_GRANTED_KEY);
      setPhase({ kind: "error", error: "camera-blocked" });
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
    // Sample GPS now (no dialog — permission already granted at init).
    gpsPromiseRef.current = getPositionWithTimeout(5000);
    const startedAt = performance.now();
    setPhase({ kind: "recording", facing: phase.facing, startedAt });

    tickRef.current = setInterval(() => {
      const elapsed = (performance.now() - startedAt) / 1000;
      const p = Math.min(elapsed / RECORD_CAP_SEC, 1);
      setProgress(p);
      if (elapsed >= RECORD_CAP_SEC && recorder.state === "recording") {
        recorder.stop();
      }
    }, 100);
  };

  const stopRecording = () => {
    if (phase.kind !== "recording") return;
    const elapsed = (performance.now() - phase.startedAt) / 1000;
    if (elapsed < MIN_RECORD_SEC) return;
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

    const pos = await (gpsPromiseRef.current ?? getPositionWithTimeout(5000));
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

    // Capture upload args into local consts BEFORE navigate so the detached
    // closure doesn't read stale React state after this component unmounts.
    const blob = phase.blob;
    const mimeType = phase.mimeType;
    const filename = `clip.${mimeType.includes("mp4") ? "mp4" : "webm"}`;
    const ts = Date.now() / 1000;
    const lat = pos.lat;
    const lng = pos.lng;

    // Optimistic-navigate: surface uploading state on the bus, then navigate
    // immediately, then run the upload as a detached promise. The user sees
    // the feed in the same gesture frame; the bar at the top of the feed
    // shows progress (indeterminate) until success/error.
    setUploadStatus({ kind: "uploading" });
    navigate("/feed");

    void (async () => {
      try {
        await postClip({ blob, filename, lat, lng, ts });
        setUploadStatus({ kind: "idle" });
      } catch (err) {
        // Visibility for the silent-success class of bug (debug session
        // phone-upload-no-railway-logs): without this log, a misconfigured
        // VITE_API_BASE / down backend / CORS-block looks like success in the UI.
        console.error("[recorder] postClip failed; enqueuing locally:", err);
        try {
          // Network / 5xx — CAP-09 enqueue. 4xx would also land here;
          // uploadQueue.flush drops 4xx as permanent on the next visit, so
          // this is safe.
          await enqueue({ blob, mimeType, lat, lng, ts });
          setUploadStatus({
            kind: "error",
            message: "Upload queued — will retry",
          });
        } catch {
          setUploadStatus({ kind: "error", message: "Upload failed" });
        }
      }
    })();
  };

  // Kill stream/timer on unmount. Without this the iOS camera indicator stays
  // on after the user navigates away mid-recording (T-04-01).
  useEffect(() => {
    return () => {
      cleanupTimer();
      cleanupStream();
    };
  }, []);

  // Warm-path: when we initialize the phase as "acquiring" (because permissions
  // were already granted earlier in this session), kick off the camera fetch
  // automatically. This skips the priming popup on feed→camera navigations.
  useEffect(() => {
    if (phase.kind === "acquiring" && !streamRef.current) {
      void acquire(phase.facing);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Render —————————————————————————————————————————————

  if (phase.kind === "priming") {
    return <PrimingModal onContinue={initializePermissions} />;
  }

  if (phase.kind === "error") {
    // For permission-denied states, only a full page reload reliably picks up
    // a Settings change on iOS Safari — the in-page permissions cache lags.
    // For "location-unavailable" (transient GPS failure), an in-page retry
    // is fine and avoids tearing down the React tree.
    const onRetry =
      phase.error === "location-unavailable"
        ? () => initializePermissions()
        : () => window.location.reload();
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
  const onRecordTap = isRecording ? stopRecording : startRecording;

  return (
    <div className="fixed inset-0 bg-[#0A0A0A]" style={{ height: "100dvh" }}>
      <CameraView stream={streamRef.current} mirrored={facing === "user"} />
      {!isRecording && phase.kind === "ready" && (
        <>
          <CameraFlipButton
            facing={facing}
            onFlip={() => {
              void flipCamera();
            }}
          />
          <CameraUploadButton />
        </>
      )}
      {phase.kind === "ready" || phase.kind === "recording" ? (
        <RecordButton
          recording={isRecording}
          progress={progress}
          canStop={!isRecording || progress >= MIN_RECORD_SEC / RECORD_CAP_SEC}
          onTap={onRecordTap}
        />
      ) : null}
      <AddToHomeScreenHint dismiss={isRecording} />
      {!isRecording && <BottomTabBar />}
    </div>
  );
}
