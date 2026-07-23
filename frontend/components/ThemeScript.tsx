/**
 * Applies the stored theme before React hydrates.
 *
 * Without this the page paints in the default theme and then snaps to the
 * stored one — a flash that reads as a bug even though nothing is broken. The
 * script is tiny and runs synchronously in <head>, which is the only place it
 * can run early enough to matter.
 */
export function ThemeScript() {
  const script = `
(function () {
  try {
    var stored = localStorage.getItem('masar-theme');
    if (stored === 'light' || stored === 'dark') {
      document.documentElement.setAttribute('data-theme', stored);
    }
    // No stored preference: leave data-theme unset so the CSS
    // prefers-color-scheme block decides.
  } catch (e) {}
})();`;
  return <script dangerouslySetInnerHTML={{ __html: script }} />;
}
