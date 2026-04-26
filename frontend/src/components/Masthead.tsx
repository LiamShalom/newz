import { ThemeToggle } from "./ThemeToggle";

// Centered NEWZ wordmark, ThemeToggle right. Bottom tab bar handles
// navigation, so the masthead stays focused on brand + theme.
export function Masthead() {
  return (
    <header className="sticky top-0 z-20 bg-surface">
      <div className="mx-auto max-w-[640px] flex items-center justify-between px-5 h-[56px]">
        <span className="w-8" aria-hidden />
        <span className="inline-flex items-center bg-accent-record text-white font-black tracking-wide px-2.5 py-1 text-[15px] leading-none rounded-sm">
          NEWZ
        </span>
        <ThemeToggle />
      </div>
    </header>
  );
}
