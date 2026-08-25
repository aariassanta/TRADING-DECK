import React, { useEffect, useState } from 'react';

export type Theme = 'dark' | 'light';
const STORAGE_KEY = 'gh.theme.v1';

/** Read the persisted theme, falling back to the system preference. */
const readInitialTheme = (): Theme => {
  if (typeof window === 'undefined') return 'dark';
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'dark' || saved === 'light') return saved;
  } catch {
    // localStorage disabled
  }
  if (window.matchMedia?.('(prefers-color-scheme: light)').matches) return 'light';
  return 'dark';
};

/** Apply the theme to the <html> element so CSS variables cascade globally. */
const applyTheme = (theme: Theme) => {
  if (typeof document === 'undefined') return;
  document.documentElement.setAttribute('data-theme', theme);
};

interface ThemeToggleProps {
  /** Optional callback fired on theme change. */
  onChange?: (theme: Theme) => void;
}

/**
 * Compact toggle button — switches between dark and light by toggling the
 * `data-theme` attribute on <html>. State is persisted to localStorage.
 */
export const ThemeToggle: React.FC<ThemeToggleProps> = ({ onChange }) => {
  const [theme, setTheme] = useState<Theme>(() => {
    const t = readInitialTheme();
    // Apply synchronously on mount to avoid a flash of unstyled content
    applyTheme(t);
    return t;
  });

  // Re-apply if the user navigates back to this tab and the theme changed elsewhere
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const toggle = () => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Silent fail
    }
    onChange?.(next);
  };

  return (
    <button
      type="button"
      onClick={toggle}
      title={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
      aria-label="Toggle color theme"
      style={{
        padding: '4px 8px',
        borderRadius: '4px',
        fontSize: '13px',
        border: '1px solid var(--border-subtle)',
        background: 'transparent',
        color: 'var(--text-secondary)',
        cursor: 'pointer',
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        transition: 'all 0.15s',
      }}
    >
      <span aria-hidden="true">{theme === 'dark' ? '🌙' : '☀️'}</span>
      <span style={{ fontSize: '10px', fontWeight: 700, letterSpacing: '0.04em' }}>
        {theme === 'dark' ? 'DARK' : 'LIGHT'}
      </span>
    </button>
  );
};
