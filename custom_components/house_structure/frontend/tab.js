/*
 * What a tab's page on the Thermal Lab page needs: Home Assistant's
 * connection and theme. Load it before your own script:
 *
 *   <script src="/house_structure_static/tab.js"></script>
 *
 * then use window.thermalLab:
 *
 *   ask(message)                  one websocket request, a promise of its result
 *   subscribe(callback, message)  a websocket subscription; a promise of the
 *                                 function that ends it
 *   applyTheme(map)               copy Home Assistant's theme into your CSS
 *                                 variables: {"--yours": "--theirs", ...}
 *                                 (THEME below is used if map is left out)
 *   remember(key, value) / recall(key, fallback)
 *                                 localStorage, namespaced, that never throws
 *
 * A tab page sits in the frame, which sits in Home Assistant's panel, so it
 * looks up the window chain for the connection rather than at its parent.
 * Same-origin only: a tab page is always served by Home Assistant itself.
 */
(function () {
  "use strict";

  const THEME = {
    "--bg": "--primary-background-color", "--card": "--card-background-color",
    "--text": "--primary-text-color", "--muted": "--secondary-text-color",
    "--line": "--divider-color", "--accent": "--primary-color",
    "--chip": "--secondary-background-color",
  };

  /* The nearest window above this one that holds Home Assistant's connection. */
  function hassWindow() {
    let w = window;
    while (w.parent && w.parent !== w) {
      w = w.parent;
      try { if (w.hassConnection) return w; } catch (e) { return null; }
    }
    return null;
  }

  async function connection() {
    const w = hassWindow();
    if (!w) throw new Error("Open this page from the Thermal Lab page in Home Assistant's sidebar.");
    const { conn } = await w.hassConnection;
    return conn;
  }

  async function ask(message) {
    return (await connection()).sendMessagePromise(message);
  }

  async function subscribe(callback, message) {
    return (await connection()).subscribeMessage(callback, message);
  }

  function applyTheme(map) {
    const root = document.documentElement;
    let style = null;
    try { style = getComputedStyle(window.top.document.documentElement); } catch (e) { return; }
    for (const [ours, theirs] of Object.entries(map || THEME)) {
      const value = style.getPropertyValue(theirs).trim();
      if (value) root.style.setProperty(ours, value);
    }
    try {
      const dark = window.top.document.querySelector("home-assistant")?.hass?.themes?.darkMode;
      if (dark !== undefined) root.dataset.theme = dark ? "dark" : "light";
    } catch (e) { /* not available */ }
  }

  const PREFIX = "thermal_lab.";
  function remember(key, value) {
    try { localStorage.setItem(PREFIX + key, JSON.stringify(value)); } catch (e) { /* private mode */ }
  }
  function recall(key, fallback) {
    try {
      const v = localStorage.getItem(PREFIX + key);
      return v === null ? fallback : JSON.parse(v);
    } catch (e) { return fallback; }
  }

  window.thermalLab = { connection, ask, subscribe, applyTheme, remember, recall, THEME };
})();
