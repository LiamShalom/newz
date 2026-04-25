import { describe, it, expect, vi, afterEach } from "vitest";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react";
import { RecordButton } from "./RecordButton";

// React 18 requires this flag for act() to work without warnings in non-RTL test envs.
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

interface RenderProps {
  recording?: boolean;
  progress?: number;
  canStop?: boolean;
  onTap?: () => void;
}

let mounted: { container: HTMLDivElement; root: Root }[] = [];

function render(props: RenderProps = {}) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(
      <RecordButton
        recording={props.recording ?? false}
        progress={props.progress ?? 0}
        canStop={props.canStop}
        onTap={props.onTap ?? (() => {})}
      />,
    );
  });
  mounted.push({ container, root });
  return container.querySelector("button") as HTMLButtonElement;
}

afterEach(() => {
  mounted.forEach(({ root, container }) => {
    act(() => root.unmount());
    container.remove();
  });
  mounted = [];
});

describe("RecordButton min-duration gating", () => {
  it("disables button and dims to 0.5 when recording but canStop=false", () => {
    const onTap = vi.fn();
    const btn = render({
      recording: true,
      progress: 0.05,
      canStop: false,
      onTap,
    });
    expect(btn.disabled).toBe(true);
    expect(btn.style.opacity).toBe("0.5");
    btn.click();
    expect(onTap).not.toHaveBeenCalled();
  });

  it("enables button at full opacity when recording and canStop=true", () => {
    const onTap = vi.fn();
    const btn = render({
      recording: true,
      progress: 0.5,
      canStop: true,
      onTap,
    });
    expect(btn.disabled).toBe(false);
    expect(btn.style.opacity).toBe("1");
    btn.click();
    expect(onTap).toHaveBeenCalledOnce();
  });

  it("defaults canStop=true when prop is omitted (idle state)", () => {
    const btn = render({ recording: false });
    expect(btn.disabled).toBe(false);
    expect(btn.style.opacity).toBe("1");
  });

  it("uses the wait aria-label while gated", () => {
    const btn = render({ recording: true, progress: 0.05, canStop: false });
    expect(btn.getAttribute("aria-label")).toBe(
      "Recording — wait for minimum duration",
    );
  });

  it("uses the stop aria-label once gating clears", () => {
    const btn = render({ recording: true, progress: 0.5, canStop: true });
    expect(btn.getAttribute("aria-label")).toBe("Stop recording");
  });

  it("uses the start aria-label when not recording", () => {
    const btn = render({ recording: false });
    expect(btn.getAttribute("aria-label")).toBe("Start recording");
  });
});
