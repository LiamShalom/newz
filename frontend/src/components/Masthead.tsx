import { ThemeSwitch } from "./ui/theme-switch-button";

// Centered NEWZ wordmark, ThemeToggle right. Bottom tab bar handles
// navigation, so the masthead stays focused on brand + theme.
//
// The 16px gradient strip below the wordmark row fades surface → transparent
// so titles scrolling up under the sticky header dissolve into it instead of
// hard-clipping mid-letter against the masthead's bottom edge.
export function Masthead() {
  return (
    <header className="sticky top-0 z-30">
      <div className="bg-surface">
        <div className="mx-auto max-w-[640px] flex items-center justify-between px-5 h-[96px]">
          <span className="w-8" aria-hidden />
          <span
            className="text-ink-primary leading-none tracking-[-0.02em]"
            style={{ fontFamily: '"Bagel Fat One", ui-sans-serif, system-ui, sans-serif' }}
          >
            <span className="text-[48px] align-baseline">New</span>
            <span className="text-[72px] align-baseline -ml-1">z</span>
          </span>
          <ThemeSwitch />
        </div>
      </div>
      <div
        aria-hidden
        className="h-4 pointer-events-none"
        style={{ background: "linear-gradient(to bottom, var(--color-surface), transparent)" }}
      />
    </header>
  );
}
