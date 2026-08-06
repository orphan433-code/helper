const FAVICON_FILE = "/favicon.svg";
const FAVICON_IDLE =
  "data:image/svg+xml," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="none">
      <rect width="32" height="32" rx="8" fill="#0f172a"/>
      <rect x="2" y="2" width="28" height="28" rx="6" fill="#1e293b"/>
      <path d="M9 8h14v3.15h-5.25V24h-3.5V11.15H9V8z" fill="#e2e8f0"/>
    </svg>`,
  );
const FAVICON_ALERT =
  "data:image/svg+xml," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="none">
      <rect width="32" height="32" rx="8" fill="#7f1d1d"/>
      <rect x="2" y="2" width="28" height="28" rx="6" fill="#dc2626"/>
      <path d="M9 8h14v3.15h-5.25V24h-3.5V11.15H9V8z" fill="#ffffff"/>
    </svg>`,
  );

let titleTimer: ReturnType<typeof setInterval> | null = null;
let faviconTimer: ReturnType<typeof setInterval> | null = null;
let titleBase = "";
let attentionMark = "⚠ Ошибка";
let paused = false;
let listenersBound = false;

function faviconLink(): HTMLLinkElement | null {
  return document.querySelector("link[rel='icon']");
}

function setFavicon(href: string) {
  const link = faviconLink();
  if (!link) return;
  if (link.getAttribute("href") === href) return;
  link.setAttribute("href", href);
}

function stripAttentionTitle(title: string) {
  return String(title || "").replace(/^(⚠[^·]*·\s*|●\s*)+/, "");
}

function stopTimers() {
  if (titleTimer) {
    clearInterval(titleTimer);
    titleTimer = null;
  }
  if (faviconTimer) {
    clearInterval(faviconTimer);
    faviconTimer = null;
  }
}

function startTimers() {
  stopTimers();
  if (paused || document.hidden) return;

  const base = stripAttentionTitle(titleBase || document.title || "TJS");
  const mark = attentionMark;
  let blink = false;
  titleTimer = setInterval(() => {
    blink = !blink;
    document.title = blink ? `${mark} · ${base}` : `● ${base}`;
  }, 700);

  let favBlink = false;
  setFavicon(FAVICON_ALERT);
  faviconTimer = setInterval(() => {
    favBlink = !favBlink;
    setFavicon(favBlink ? FAVICON_ALERT : FAVICON_IDLE);
  }, 700);
}

function onVisibility() {
  if (!titleBase && !titleTimer && !faviconTimer) return;
  if (document.hidden) {
    paused = true;
    stopTimers();
  } else if (titleBase) {
    paused = false;
    startTimers();
  }
}

function onFocus() {
  // Пользователь вернулся — хватит мигать (диалог всё ещё открыт).
  if (!titleBase) return;
  paused = true;
  stopTimers();
  const base = stripAttentionTitle(titleBase);
  document.title = `${attentionMark} · ${base}`;
  setFavicon(FAVICON_ALERT);
}

function bindListeners() {
  if (listenersBound || typeof window === "undefined") return;
  listenersBound = true;
  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("focus", onFocus);
}

/** Blink tab title + favicon (alert / idle). */
export function grabWindowAttention(prefix?: string, _detail?: string) {
  bindListeners();
  try {
    window.focus();
  } catch {
    /* ignore */
  }

  if (!titleBase) titleBase = stripAttentionTitle(document.title || "TJS");
  attentionMark = prefix || "⚠ Ошибка";
  paused = false;
  document.title = `${attentionMark} · ${stripAttentionTitle(titleBase)}`;
  startTimers();
}

export function clearTitleAttention() {
  stopTimers();
  paused = false;
  setFavicon(FAVICON_FILE);
  if (titleBase) {
    document.title = stripAttentionTitle(titleBase);
    titleBase = "";
  } else {
    document.title = stripAttentionTitle(document.title) || "TJS Browser";
  }
}

export function isAttentionActive() {
  return titleBase !== "" || titleTimer !== null || faviconTimer !== null;
}
