import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "newz.theme";

function readInitialTheme(): Theme {
  if (typeof document === "undefined") return "light";
  // index.html hydration script already set this from localStorage; trust it.
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export function useTheme(): [Theme, (next: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(readInitialTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const setTheme = (next: Theme) => {
    setThemeState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // private mode / quota — silently ignore; in-memory state still flips.
    }
  };

  return [theme, setTheme];
}
