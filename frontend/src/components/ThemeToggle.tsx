import { Moon, Sun } from "lucide-react";
import { useTheme } from "../theme";

export function ThemeToggle() {
  const [theme, setTheme] = useTheme();
  const next = theme === "light" ? "dark" : "light";
  const Icon = theme === "light" ? Moon : Sun;
  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} mode`}
      className="flex items-center justify-center w-8 h-8 rounded-full text-ink-tertiary hover:text-ink-secondary transition-colors"
    >
      <Icon size={18} strokeWidth={1.75} />
    </button>
  );
}
