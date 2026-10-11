// Per-browser display preferences (board look, analysis behaviour). Stored in
// localStorage; everything works with the defaults if storage is unavailable.

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export type BoardThemeId = "walnut" | "slate" | "emerald" | "midnight";

export const BOARD_THEMES: Record<BoardThemeId, { label: string; light: string; dark: string }> = {
  walnut: { label: "Walnut", light: "#e9dcc3", dark: "#b08661" },
  slate: { label: "Slate", light: "#d5dbe1", dark: "#7a8b9c" },
  emerald: { label: "Tournament", light: "#eeeed2", dark: "#769656" },
  midnight: { label: "Midnight", light: "#a3b1c2", dark: "#4e5d70" },
};

interface PreferencesState {
  boardTheme: BoardThemeId;
  showCoordinates: boolean;
  animations: boolean;
  showBestArrow: boolean;
  autoAnalyze: boolean;
  set: (patch: Partial<Omit<PreferencesState, "set">>) => void;
}

const safeStorage = createJSONStorage(() => {
  try {
    const probe = "__chesslab__";
    window.localStorage.setItem(probe, probe);
    window.localStorage.removeItem(probe);
    return window.localStorage;
  } catch {
    const memory = new Map<string, string>();
    return {
      getItem: (k: string) => memory.get(k) ?? null,
      setItem: (k: string, v: string) => void memory.set(k, v),
      removeItem: (k: string) => void memory.delete(k),
    };
  }
});

export const usePreferences = create<PreferencesState>()(
  persist(
    (set) => ({
      boardTheme: "walnut",
      showCoordinates: true,
      animations: true,
      showBestArrow: true,
      autoAnalyze: true,
      set: (patch) => set(patch),
    }),
    { name: "chesslab.preferences", storage: safeStorage, version: 1 },
  ),
);
