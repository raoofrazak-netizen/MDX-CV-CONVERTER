const API = "";

async function apiFetch(path, options = {}) {
  const res = await fetch(API + path, options);
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  const contentType = res.headers.get("content-type") || "";
  return contentType.includes("application/json") ? res.json() : res;
}

function fmtDate(iso) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch (_) { return iso; }
}

function pill(text, cls) {
  return `<span class="pill ${cls}">${text}</span>`;
}

function statusLabel(status) {
  return status.replaceAll("_", " ");
}

function actionLabel(action) {
  return action.replaceAll("_", " ").replace(/^./, c => c.toUpperCase());
}
