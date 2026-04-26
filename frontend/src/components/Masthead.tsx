import { ThemeSwitch } from "./ui/theme-switch-button";

// Centered NEWZ wordmark, ThemeToggle right. Bottom tab bar handles
// navigation, so the masthead stays focused on brand + theme.
export function Masthead() {
  return (
    <header className="sticky top-0 z-20 bg-surface">
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
    </header>
  );
}
