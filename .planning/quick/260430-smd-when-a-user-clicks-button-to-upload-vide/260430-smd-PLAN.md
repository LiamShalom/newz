---
quick_id: 260430-smd
type: quick
mode: quick
scope: frontend
phase: quick-260430-smd
plan: 01
wave: 1
depends_on: []
files_modified:
  - frontend/src/uploadStatusBus.ts
  - frontend/src/uploadStatusBus.test.ts
  - frontend/src/components/UploadProgressBar.tsx
  - frontend/src/views/Feed.tsx
  - frontend/src/views/Recorder.tsx
  - frontend/src/components/CameraUploadButton.tsx
autonomous: false
requirements:
  - QUICK-260430-smd
must_haves:
  truths:
    - "Tapping Post on RetakeScreen navigates to /feed in the same tick (no awaiting postClip before navigate)"
    - "Tapping the file in CameraUploadButton navigates to /feed in the same tick after the file is picked (no awaiting postClip)"
    - "An indeterminate animated progress bar is visible at the top of the feed (under the Masthead) the moment the user lands while an upload is in flight"
    - "The progress bar disappears when the upload completes successfully"
    - "If the upload fails (network/5xx → enqueue, or other error), the progress bar swaps to a brief error state before disappearing or being dismissed — no silent vanish"
    - "No usernames, no per-user state, no display names appear in the bar — anonymous-by-default tone preserved"
    - "Bar is touch-friendly + safe-area-aware where it touches a screen edge (sits below the masthead, no top edge bleed)"
  artifacts:
    - path: "frontend/src/uploadStatusBus.ts"
      provides: "Module-level pub-sub for upload status (idle | uploading | error). useUploadStatus hook + setUploadStatus setter. Mirrors muteBus.ts pattern."
      exports: ["useUploadStatus", "setUploadStatus", "getUploadStatus", "subscribeToUploadStatus"]
    - path: "frontend/src/components/UploadProgressBar.tsx"
      provides: "Thin animated bar that mounts in Feed.tsx, reads useUploadStatus(), shows indeterminate shimmer while 'uploading' and an error swap (with dismiss) on 'error'."
    - path: "frontend/src/uploadStatusBus.test.ts"
      provides: "Vitest unit test asserting set→subscribe→read flow + idle reset behavior."
  key_links:
    - from: "frontend/src/views/Recorder.tsx (submitClip)"
      to: "frontend/src/uploadStatusBus.ts"
      via: "setUploadStatus('uploading') BEFORE navigate; setUploadStatus('idle') on success / 'error' on catch — fire-and-forget after navigate"
      pattern: "setUploadStatus\\((\"|')uploading"
    - from: "frontend/src/components/CameraUploadButton.tsx (onPick)"
      to: "frontend/src/uploadStatusBus.ts"
      via: "setUploadStatus('uploading') BEFORE navigate; setUploadStatus('idle')/('error') after detached fetch resolves"
      pattern: "setUploadStatus\\((\"|')uploading"
    - from: "frontend/src/views/Feed.tsx"
      to: "frontend/src/components/UploadProgressBar.tsx"
      via: "Mount under <Masthead /> so the bar is visible above feed content immediately on /feed render"
      pattern: "<UploadProgressBar"
---

<objective>
The recording screen currently blocks the user during the `/clips` POST round-trip (1–2s of perceived dead time before `navigate("/feed")`). Decouple navigation from upload: navigate to the feed in the same gesture frame, kick off the upload as a detached promise, and surface upload progress + failure on the feed via a thin top-of-feed bar.

Purpose: kill perceived latency on the post-clip handoff — the funding-pitch surface that gets clicked first when a stranger picks up the phone. Anonymity-by-default tone preserved (no usernames, no per-user state).

Output: a tiny pub-sub module mirroring the existing `muteBus.ts`/`commentsBus.ts` pattern, a new `UploadProgressBar` component mounted under `<Masthead />` on the feed, and edits to both upload entry points (`Recorder.submitClip` + `CameraUploadButton.onPick`) so they fire setUploadStatus → navigate → detached upload promise.
</objective>

<execution_context>
This is a /gsd-quick task. Single PLAN.md → execute → commit → SUMMARY.md. No multi-phase workflow.

Branch convention: working on current branch (`liam/bug-fixes`) is fine for a frontend-only quick. Do NOT branch unless the user is mid-feature elsewhere — `git status` says we're clean save for an untracked debug note.

@.planning/PROJECT.md
@./CLAUDE.md
</execution_context>

<context>
@frontend/src/views/Recorder.tsx
@frontend/src/views/Feed.tsx
@frontend/src/components/RetakeScreen.tsx
@frontend/src/components/CameraUploadButton.tsx
@frontend/src/components/Masthead.tsx
@frontend/src/muteBus.ts
@frontend/src/commentsBus.ts
@frontend/src/uploadQueue.ts
@frontend/src/api.ts

<interfaces>
<!-- Project-canonical pub-sub pattern. New uploadStatusBus.ts must mirror this shape. -->

From frontend/src/muteBus.ts:
```ts
const TARGET = new EventTarget();
const TYPE = "mute_changed";
let muted = true;
export function getMuted(): boolean { return muted; }
export function setMuted(next: boolean): void {
  if (muted === next) return;
  muted = next;
  TARGET.dispatchEvent(new CustomEvent(TYPE));
}
export function subscribeToMute(listener: () => void): () => void {
  TARGET.addEventListener(TYPE, listener);
  return () => TARGET.removeEventListener(TYPE, listener);
}
export function useMuted(): [boolean, (next: boolean) => void] {
  const [value, setValue] = useState<boolean>(muted);
  useEffect(() => subscribeToMute(() => setValue(muted)), []);
  return [value, setMuted];
}
```

From frontend/src/api.ts (postClip — DO NOT change contract):
```ts
export async function postClip(args: {
  blob: Blob; filename: string; lat: number; lng: number; ts: number;
}): Promise<IngestResponse>;
```

From frontend/src/uploadQueue.ts (already handles offline/5xx fallback):
```ts
export async function enqueue(item: {
  blob: Blob; mimeType: string; lat: number; lng: number; ts: number;
}): Promise<void>;
```

Recorder.submitClip currently does (Recorder.tsx:226-281):
```ts
// ...gps resolve → setPhase("submitting")...
try {
  await postClip({ ... });
  navigate("/feed");
} catch (err) {
  await enqueue({ ... });
  navigate("/feed");
}
```
The await on postClip is what we're killing. Navigate must fire BEFORE the upload starts.

CameraUploadButton.onPick currently does (CameraUploadButton.tsx:19-43): same shape — gps → postClip → enqueue on catch → navigate. Same refactor pattern applies.

Masthead is `sticky top-0 z-30` (Masthead.tsx:7) and 96px tall. UploadProgressBar mounts as a sibling INSIDE the Masthead's sticky container (or just below) so it pins under the wordmark while the feed scrolls.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add uploadStatusBus pub-sub + unit test</name>
  <files>frontend/src/uploadStatusBus.ts, frontend/src/uploadStatusBus.test.ts</files>
  <action>
Create `frontend/src/uploadStatusBus.ts` mirroring the muteBus.ts shape exactly. Module-level state is a tagged union: `type UploadStatus = { kind: "idle" } | { kind: "uploading" } | { kind: "error"; message: string }`. Initial state `{ kind: "idle" }`.

Exports (all required — Feed and the two upload sites import from here):
- `getUploadStatus(): UploadStatus`
- `setUploadStatus(next: UploadStatus): void` — early-return on identity-equal kind+message; dispatch `CustomEvent("upload_status_changed")` otherwise
- `subscribeToUploadStatus(listener: () => void): () => void`
- `useUploadStatus(): UploadStatus` — React hook; useState seeded from getUploadStatus(), useEffect subscribes once, unsubscribes on unmount. (Read-only hook — setter is module-level since callers are outside React tree, e.g. Recorder's detached promise.)

Also export the `UploadStatus` type.

Rationale for pattern choice: muteBus.ts and commentsBus.ts already use this exact shape — reusing it avoids introducing a state library (Context/Zustand/Jotai) for a single boolean+message. CLAUDE.md "no new deps unless absolutely required" applies.

Create `frontend/src/uploadStatusBus.test.ts` with Vitest covering:
- starts as `{ kind: "idle" }`
- `setUploadStatus({ kind: "uploading" })` → subscribers fired exactly once, `getUploadStatus()` returns uploading
- setting same kind twice → only one dispatch (test by counting subscriber calls)
- `setUploadStatus({ kind: "error", message: "..." })` → fires; `setUploadStatus({ kind: "idle" })` resets
- `subscribeToUploadStatus` returns an unsubscribe that actually unsubscribes

Use plain Vitest `it/expect` — match the existing test style (see `frontend/src/api.test.ts` and `pickMaxRatioIndex.test.ts`). No need for @testing-library/react in this test (pure module).
  </action>
  <verify>
    <automated>cd /Users/liamshalom/Hacktech/frontend &amp;&amp; pnpm test -- uploadStatusBus</automated>
  </verify>
  <done>
- `uploadStatusBus.ts` exports `useUploadStatus`, `setUploadStatus`, `getUploadStatus`, `subscribeToUploadStatus`, `UploadStatus`
- `uploadStatusBus.test.ts` passes all assertions
- `pnpm tsc -b` (or vite build) passes — no type errors
  </done>
</task>

<task type="auto">
  <name>Task 2: Create UploadProgressBar component + mount in Feed</name>
  <files>frontend/src/components/UploadProgressBar.tsx, frontend/src/views/Feed.tsx</files>
  <action>
Create `frontend/src/components/UploadProgressBar.tsx`:
- Reads `useUploadStatus()` from `../uploadStatusBus`
- Renders nothing when `status.kind === "idle"`
- When `status.kind === "uploading"`: render a 3px-tall full-width bar with an indeterminate animated shimmer using Tailwind 4. Use a CSS keyframe animation for a translating gradient (e.g. a slim highlight sliding L→R across a coral/coral-light track to match `CameraUploadButton`'s coral palette). Define the keyframe inline in `frontend/src/index.css` if Tailwind 4's arbitrary keyframes don't cover it — DO NOT add a config file. Acceptable shortcut: a single `@keyframes upload-shimmer` block in `index.css` plus a `className="animate-[upload-shimmer_1.4s_linear_infinite]"`-style usage. Indeterminate is fine; backend doesn't expose progress and the constraints explicitly allow this.
- When `status.kind === "error"`: render the same bar height in a red/error tone with a brief inline message (`status.message` truncated, no usernames, no PII) and a dismiss "X" button on the right that calls `setUploadStatus({ kind: "idle" })`. Auto-dismiss after 6s via `setTimeout` cleared on unmount/state change.
- Bar is positioned via the parent (sticky context inherited from Masthead). The component itself returns a `<div role="status" aria-live="polite">` with the bar. `aria-busy={status.kind === "uploading"}`.
- Touch-friendly: dismiss button is min 44×44 hit area (per iOS HIG), even though the visible bar is 3px — use Tailwind padding to expand the hit target (`p-2 -m-2` style trick) without bloating layout.
- NO usernames, NO display names — bar messages stay event-shaped ("Upload failed" / "Network error" — never "your upload" or anything user-attributed).

Edit `frontend/src/views/Feed.tsx`:
- Import `UploadProgressBar`
- Mount it directly inside the existing fragment, immediately AFTER `<Masthead />` and BEFORE the loaded/empty/FeedShell branch. This places it visually just under the wordmark.
- Wrap Masthead + bar in a `<div className="sticky top-0 z-30">` ONLY if the bar must scroll-pin with the header. Simpler: leave Masthead's existing `sticky top-0 z-30` and put `<UploadProgressBar />` as a sibling that is also `sticky top-[96px] z-30` (Masthead is 96px tall — see Masthead.tsx:8). Pick the simpler sibling approach unless it visually breaks; document the choice in the SUMMARY.

iOS Safari note: Masthead does not currently use `env(safe-area-inset-top)` — bar inherits the same posture. No top-edge safe-area work needed.
  </action>
  <verify>
    <automated>cd /Users/liamshalom/Hacktech/frontend &amp;&amp; pnpm tsc -b</automated>
  </verify>
  <done>
- `UploadProgressBar.tsx` exists, exports default or named `UploadProgressBar`
- Renders null on idle, shimmering bar on uploading, error swap with dismiss on error
- `Feed.tsx` mounts `<UploadProgressBar />` directly under `<Masthead />`
- TypeScript build is clean
- Bar visually inspectable: in `pnpm dev`, manually call `setUploadStatus({ kind: "uploading" })` from the browser console (after exposing it via `window` in a temp dev-only line, or trigger via the next task) and confirm the bar appears under the wordmark
  </done>
</task>

<task type="auto">
  <name>Task 3: Decouple navigation from upload in both upload entry points</name>
  <files>frontend/src/views/Recorder.tsx, frontend/src/components/CameraUploadButton.tsx</files>
  <action>
**Recorder.tsx — `submitClip` (currently lines 226-281):**

After GPS resolution succeeds (and BEFORE the postClip await), do all of the following synchronously in this order:
1. `setUploadStatus({ kind: "uploading" })` — import from `../uploadStatusBus`
2. `navigate("/feed")` — fire navigate IMMEDIATELY, before the upload starts
3. Kick off the postClip + enqueue-on-catch flow as a detached promise (no `await` on the function's return path):
   ```ts
   void (async () => {
     try {
       await postClip({ blob: phase.blob, filename, lat: pos.lat, lng: pos.lng, ts });
       setUploadStatus({ kind: "idle" });
     } catch (err) {
       console.error("[recorder] postClip failed; enqueuing locally:", err);
       try {
         await enqueue({ blob: phase.blob, mimeType: phase.mimeType, lat: pos.lat, lng: pos.lng, ts });
         setUploadStatus({ kind: "error", message: "Upload queued — will retry" });
       } catch {
         setUploadStatus({ kind: "error", message: "Upload failed" });
       }
     }
   })();
   ```
   Capture `phase.blob`, `phase.mimeType`, `pos.lat`, `pos.lng`, `ts`, `filename` into local consts BEFORE navigate so the closure doesn't re-read stale state.

The `setPhase({ kind: "submitting", ... })` line becomes irrelevant on the happy path because the user has already left this view — but the existing error-screen branches (`location-blocked`, `location-unavailable`) must remain intact. Those run BEFORE setUploadStatus/navigate, so they still block on the GPS check. Do not touch those branches.

Remove the now-unused "submitting" phase rendering branch in `RetakeScreen` invocation? — keep RetakeScreen's `submitting` prop API intact (it's used briefly between user tap and navigate to disable the Post button, ~one frame). The `submitting` phase still exists for the GPS-pending → upload-kickoff window, so leave that machinery alone.

Note (CLAUDE.md anonymity): no session_id surfaces in the bar message. The bus message strings are static event-shaped phrases.

**CameraUploadButton.tsx — `onPick` (currently lines 19-43):**

Same refactor:
1. After file is picked + GPS resolved, capture all upload args into local consts
2. `setUploadStatus({ kind: "uploading" })`
3. `navigate("/feed")`
4. Detached promise: postClip → on catch → enqueue → setUploadStatus(idle/error)
5. Drop the `setBusy(true/false)` wrapping — the spinner-on-button is no longer needed because the user is no longer on the camera screen by the time the upload runs. The expanding hover-to-"Upload" affordance can stay; just remove the `busy` state entirely (or keep it briefly true for the synchronous setup span between file-pick and navigate, then drop). Cleanest: delete `busy` state, delete the spinner span, simplify. Confirm visually that the button is no longer mid-screen during upload.

**Both files:** Ensure imports are sorted/lint-clean. Do not introduce any new dependencies.

**iOS Safari sanity:** the only iOS-sensitive thing here is that GPS reads must still happen inside the existing flow (Recorder samples GPS at record-tap via `gpsPromiseRef`, CameraUploadButton awaits inline). Both paths preserve their existing GPS handling because the navigate-immediately swap happens AFTER GPS resolves on the happy path. Verify this on real iPhone in Task 4.
  </action>
  <verify>
    <automated>cd /Users/liamshalom/Hacktech/frontend &amp;&amp; pnpm tsc -b &amp;&amp; pnpm test</automated>
  </verify>
  <done>
- Recorder.tsx `submitClip`: navigate fires BEFORE postClip await; status bus is set to uploading/idle/error appropriately
- CameraUploadButton.tsx `onPick`: navigate fires BEFORE postClip await; status bus drives the bar; `busy` local state removed (or no longer drives any visible UI)
- TypeScript build clean
- All existing tests still pass
- Manual: `pnpm dev`, record a 5s clip, tap Post — feed appears in the same animation frame; bar appears at top under wordmark; bar disappears on success
- Manual error path: with backend stopped (`OFFLINE_DEMO` won't help here — just stop the local backend), record + post → feed appears, bar shows "Upload queued — will retry" then auto-dismisses after 6s
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 4: Real-iPhone smoke test on iOS Safari</name>
  <what-built>
Optimistic navigation + top-of-feed indeterminate progress bar driven by a new `uploadStatusBus`. Both upload entry points (RetakeScreen Post button → Recorder.submitClip; and CameraUploadButton file-picker) now navigate to /feed immediately on tap and run the upload as a detached promise.
  </what-built>
  <how-to-verify>
On a real iPhone (NOT desktop emulator — CLAUDE.md "iOS Safari is the primary surface"):

1. Open the app via `https://<your-ngrok-or-vercel-preview>` on iPhone Safari. Hard-reload to clear sessionStorage.
2. Tap record button. Grant camera + location dialogs. Record for 6+ seconds. Tap stop.
3. On RetakeScreen, tap "Post". **Expected:** feed view replaces the retake preview within ~1 animation frame (no visible 1-2s pause on the recording/retake screen). A thin coral progress bar appears at the top of the feed under the "NEWZ" wordmark within the same paint.
4. **Expected:** the bar stays visible for the duration of the actual upload (typically 1–4s on cellular). When the upload completes, the bar disappears smoothly.
5. Wait for SSE `segment_published` to land — your videorecording shows up in the feed. (This was already working pre-change; just confirm the navigate-early refactor didn't break the SSE listener.)
6. Repeat with the CameraUploadButton path: tap the coral up-arrow button on the camera screen, pick a video file. **Expected:** same behavior — feed appears immediately, bar appears immediately, bar disappears on success.
7. **Error path:** put the iPhone into Airplane Mode briefly during step 3's upload. Tap Post. **Expected:** feed appears immediately, bar shows "Upload queued — will retry" in error state, auto-dismisses after 6s. (The clip enqueues locally per existing uploadQueue.ts behavior — re-toggle airplane mode off and revisit /feed to flush.)
8. **Anonymity check:** read every word in the bar across uploading + error states. Confirm zero usernames, no "your upload", no per-user attribution. Should read as event-shaped only.
9. **Safe-area check:** confirm the bar doesn't bleed into the iOS status-bar area at the top of the screen (it should sit under the Masthead which already accounts for layout).
  </how-to-verify>
  <resume-signal>Type "approved" or describe what's broken (be specific: which step, expected vs. actual, screenshot path if helpful).</resume-signal>
</task>

</tasks>

<verification>
- `pnpm tsc -b` passes
- `pnpm test` passes (existing tests + new uploadStatusBus.test.ts)
- Manual iOS Safari smoke (Task 4) signed off
- Grep check: `grep -rn "await postClip" frontend/src/` shows postClip is now only awaited INSIDE detached promises (not in the navigation path) and inside `uploadQueue.ts` (the retry walker — unchanged)
</verification>

<success_criteria>
- Tapping Post on RetakeScreen → feed appears within ~16ms (one paint), not 1-2s
- Tapping a file in CameraUploadButton → feed appears within ~16ms after file is picked, not 1-2s
- Indeterminate animated bar visible at top of feed during upload, disappears on success
- Error state surfaced via the same bar (no silent disappear), auto-dismisses or is dismissable
- No new dependencies added
- Anonymity preserved — no usernames anywhere in the new UI
- iPhone Safari smoke test signs off (Task 4)
</success_criteria>

<output>
After completion:
1. Commit per task (atomic): `Task 1` → `feat(upload): add uploadStatusBus pub-sub`. `Task 2` → `feat(upload): add UploadProgressBar mounted in Feed`. `Task 3` → `feat(upload): navigate to feed before upload completes`.
2. Write `.planning/quick/260430-smd-when-a-user-clicks-button-to-upload-vide/260430-smd-SUMMARY.md` with: what shipped, files touched, manual verification result, any deferred follow-ups.
3. Update STATE.md "Quick Tasks Completed" table with the new entry (260430-smd).
</output>

<open_questions>
- Sticky-positioning approach for the bar: Task 2 picks "sibling sticky at top:96px" — if Masthead's height changes (currently fixed via `h-[96px]` in Masthead.tsx:8), the bar will desync. Acceptable for the pilot; flag in SUMMARY if encountered.
- Indeterminate-only animation: backend doesn't expose upload-progress events on `/clips`. If at some point we want a true 0-100% bar, swap fetch for `XMLHttpRequest` + `upload.onprogress`. Out of scope for this quick.
- Concurrency: bus models a single in-flight upload (constraints explicitly allow this). If two uploads kick off back-to-back (rapid Post → camera → Post), the second `setUploadStatus("uploading")` is idempotent and the bar continues. The first error/success race could clobber the second — acceptable for pilot, flag if observed in Task 4.
</open_questions>
