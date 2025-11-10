const DEFAULT_BACKEND_PORT = 8000;

declare global {
  interface Window {
    __STOCKAI_API_BASE__?: string;
  }
}

function computeDefaultBase() {
  if (typeof window === "undefined") {
    return `http://localhost:${DEFAULT_BACKEND_PORT}`;
  }
  const { protocol, hostname, port } = window.location;
  const isStandardPort = !port || port === "80" || port === "443";
  if (isStandardPort) {
    return `${protocol}//${hostname}/api`;
  }
  return `${protocol}//${hostname}:${DEFAULT_BACKEND_PORT}`;
}

function readFromStorage() {
  if (typeof window === "undefined") {
    return undefined;
  }
  try {
    return window.localStorage.getItem("STOCKAI_API_BASE") || undefined;
  } catch {
    return undefined;
  }
}

export function resolveApiBase(): string {
  if (typeof window === "undefined") {
    return computeDefaultBase();
  }
  return window.__STOCKAI_API_BASE__ || readFromStorage() || computeDefaultBase();
}

export function setApiBase(base: string) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem("STOCKAI_API_BASE", base);
  } catch (err) {
    console.warn("failed to persist api base", err);
  }
  window.__STOCKAI_API_BASE__ = base;
}

export const API_BASE = resolveApiBase();
