import { Moon, Sun } from "lucide-react";
import { useTheme } from "../../theme";

interface ThemeSwitchProps {
  className?: string;
}

export function ThemeSwitch({ className = "" }: ThemeSwitchProps) {
  const [theme, setTheme] = useTheme();
  const next = theme === "light" ? "dark" : "light";

  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} mode`}
      className={`relative flex h-8 w-8 items-center justify-center rounded-full text-ink-primary hover:opacity-70 transition-opacity overflow-hidden ${className}`}
    >
      <Sun
        className={`absolute h-5 w-5 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] ${
          theme === "light"
            ? "scale-100 translate-y-0 opacity-100"
            : "scale-50 translate-y-5 opacity-0"
        }`}
        strokeWidth={1.75}
      />
      <Moon
        className={`absolute h-5 w-5 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] ${
          theme === "dark"
            ? "scale-100 translate-y-0 opacity-100"
            : "scale-50 translate-y-5 opacity-0"
        }`}
        strokeWidth={1.75}
      />
    </button>
  );
}
