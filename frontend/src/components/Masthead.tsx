import { ThemeToggle } from "./ThemeToggle";

export function Masthead() {
  return (
    <header className="sticky top-0 z-20 bg-surface border-b border-hairline">
      <div className="mx-auto max-w-[640px] flex items-center justify-between px-5 h-[52px]">
        <span className="font-display font-bold text-[22px] tracking-tight text-ink-primary leading-none">
          Newz
        </span>
        <ThemeToggle />
      </div>
    </header>
  );
}
