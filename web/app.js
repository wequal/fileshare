const API = "/api/v1";
const TOKEN_KEY = "fileshare_token";
const USER_KEY = "fileshare_user";

const isIOS =
  /iPad|iPhone|iPod/.test(navigator.userAgent) ||
  (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

let token = sessionStorage.getItem(TOKEN_KEY);
let currentUser = null;
let currentPath = "/";
let canWrite = false;
let chunkSize = 8 * 1024 * 1024;
let maxParallel = 4;

const $ = (id) => document.getElementById(id);

function show(el) { el.classList.remove("hidden"); }
function hide(el) { el.classList.add("hidden"); }

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (!(options.body instanceof FormData) && options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(API + path, { ...options, headers });
  if (res.status === 401) {
    logout();
    throw new Error("Session expired");
  }
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!res.ok) {
    const msg = data?.detail || (typeof data?.detail === "string" ? data.detail : res.statusText);
    throw new Error(Array.isArray(msg) ? msg.map((m) => m.msg || m).join(", ") : String(msg || res.status));
  }
  return data;
}

function formatSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function iconFor(entry) {
  if (entry.type === "directory") return "📁";
  if (entry.type === "image") return "🖼";
  if (entry.type === "video") return "🎬";
  return "📄";
}

function logout() {
  token = null;
  currentUser = null;
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
  hide($("browser-view"));
  show($("login-view"));
}

async function login(username, password) {
  const data = await api("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  token = data.access_token;
  sessionStorage.setItem(TOKEN_KEY, token);
  currentUser = { username: data.username, is_admin: data.is_admin };
  sessionStorage.setItem(USER_KEY, JSON.stringify(currentUser));
  await openBrowser();
}

async function openBrowser() {
  hide($("login-view"));
  show($("browser-view"));
  currentPath = "/";
  await loadDirectory(currentPath);
}

async function loadDirectory(path) {
  currentPath = path || "/";
  $("current-path").textContent = currentPath;
  $("back-btn").classList.toggle("hidden", currentPath === "/" || currentPath === "");

  const data = await api(`/files?path=${encodeURIComponent(currentPath)}`);
  canWrite = data.can_write;
  $("mkdir-btn").classList.toggle("hidden", !canWrite);
  $("upload-wrap").classList.toggle("hidden", !canWrite);

  const list = $("file-list");
  list.innerHTML = "";

  const entries = (data.entries || []).sort((a, b) => {
    if (a.type === "directory" && b.type !== "directory") return -1;
    if (b.type === "directory" && a.type !== "directory") return 1;
    return a.name.localeCompare(b.name);
  });

  if (entries.length === 0) {
    show($("empty-msg"));
  } else {
    hide($("empty-msg"));
  }

  for (const entry of entries) {
    const li = document.createElement("li");
    const isDir = entry.type === "directory";

    li.innerHTML = `
      <span class="icon">${iconFor(entry)}</span>
      <span class="meta">
        <span class="name">${escapeHtml(entry.name)}</span>
        <span class="detail">${isDir ? "Folder" : formatSize(entry.size)}</span>
      </span>
      <span class="actions"></span>
    `;

    const actions = li.querySelector(".actions");

    if (!isDir) {
      const dl = document.createElement("a");
      dl.textContent = "Get";
      dl.href = `${API}/files/download?path=${encodeURIComponent(entry.path)}`;
      dl.addEventListener("click", (e) => {
        e.stopPropagation();
        downloadWithAuth(entry.path, entry.name);
      });
      actions.appendChild(dl);
    }

    if (canWrite && !isDir) {
      const del = document.createElement("button");
      del.type = "button";
      del.textContent = "Del";
      del.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm(`Delete ${entry.name}?`)) return;
        await api(`/files?path=${encodeURIComponent(entry.path)}`, { method: "DELETE" });
        await loadDirectory(currentPath);
      });
      actions.appendChild(del);
    }

    li.addEventListener("click", () => {
      if (isDir) loadDirectory(entry.path);
    });

    list.appendChild(li);
  }
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

async function downloadWithAuth(path, filename) {
  const res = await fetch(
    `${API}/files/download?path=${encodeURIComponent(path)}`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!res.ok) {
    alert("Download failed");
    return;
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function isVideoFile(file) {
  return (
    (file.type && file.type.startsWith("video/")) ||
    /\.(mov|mp4|m4v|avi|mkv|webm)$/i.test(file.name || "")
  );
}

function uploadParallelism() {
  return isIOS ? 1 : maxParallel;
}

function shouldUseMultipart(file) {
  if (isIOS && isVideoFile(file)) return false;
  return file.size === 0 || file.size > chunkSize;
}

const STALL_TIMEOUT_MS = 45000;
const UPLOAD_RETRIES = 3;

function uploadSimpleXHR(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const url = `${API}/files/upload?path=${encodeURIComponent(currentPath)}`;
    const form = new FormData();
    form.append("file", file, file.name || "upload");

    let lastProgress = Date.now();
    let lastLoaded = 0;
    let stallTimer = null;

    function clearStall() {
      if (stallTimer) {
        clearInterval(stallTimer);
        stallTimer = null;
      }
    }

    function startStallDetector() {
      stallTimer = setInterval(() => {
        if (Date.now() - lastProgress > STALL_TIMEOUT_MS) {
          clearStall();
          try { xhr.abort(); } catch {}
          reject(new Error(`Upload stalled (no progress for ${STALL_TIMEOUT_MS / 1000}s)`));
        }
      }, 5000);
    }

    xhr.open("POST", url);
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0) {
        if (e.loaded > lastLoaded) {
          lastLoaded = e.loaded;
          lastProgress = Date.now();
        }
        onProgress(e.loaded / e.total);
      }
    };

    xhr.onload = () => {
      clearStall();
      if (xhr.status === 401) {
        logout();
        return reject(new Error("Session expired"));
      }
      let data = {};
      try { data = xhr.responseText ? JSON.parse(xhr.responseText) : {}; }
      catch { data = { detail: xhr.responseText || xhr.statusText }; }
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(1);
        return resolve(data);
      }
      const detail = data.detail;
      const msg = Array.isArray(detail)
        ? detail.map((m) => m.msg || m).join(", ")
        : (detail || `Upload failed (${xhr.status})`);
      reject(new Error(String(msg)));
    };

    xhr.onerror = () => { clearStall(); reject(new Error("Network error during upload")); };
    xhr.onabort = () => { clearStall(); };
    xhr.ontimeout = () => { clearStall(); reject(new Error("Upload timed out")); };
    xhr.timeout = 0;
    startStallDetector();
    xhr.send(form);
  });
}

async function uploadWithRetry(file, onProgress) {
  let lastErr = null;
  for (let attempt = 1; attempt <= UPLOAD_RETRIES; attempt++) {
    try {
      const prog = $("upload-progress");
      if (prog && attempt > 1) {
        prog.textContent = `${file.name}: retry ${attempt}/${UPLOAD_RETRIES}...`;
      }
      return await uploadSimpleXHR(file, onProgress);
    } catch (e) {
      lastErr = e;
      await new Promise((r) => setTimeout(r, 1000 * attempt));
    }
  }
  throw lastErr || new Error("Upload failed after retries");
}

async function uploadFile(file, onProgress) {
  if (isIOS && isVideoFile(file)) {
    return uploadWithRetry(file, onProgress);
  }
  if (shouldUseMultipart(file)) {
    return uploadMultipart(file, onProgress);
  }
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(
    `${API}/files/upload?path=${encodeURIComponent(currentPath)}`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Upload failed");
  }
  onProgress(1);
  return res.json();
}

async function uploadMultipart(file, onProgress) {
  const sequential = isIOS || isVideoFile(file) || file.size <= 0;

  const init = await api("/files/uploads", {
    method: "POST",
    body: JSON.stringify({
      path: currentPath,
      filename: file.name,
      total_size: sequential ? 0 : file.size,
    }),
  });

  chunkSize = init.chunk_size;
  const uploadId = init.upload_id;

  if (sequential || init.unknown_size || init.total_parts === 0) {
    return uploadMultipartSequential(file, uploadId, onProgress);
  }

  const totalParts = init.total_parts;

  let status = await api(`/files/uploads/${uploadId}`);
  const done = new Set(status.parts_received || []);

  const parts = [];
  for (let n = 1; n <= totalParts; n++) {
    if (!done.has(n)) parts.push(n);
  }

  let completed = done.size;

  async function uploadPart(partNumber) {
    const start = (partNumber - 1) * chunkSize;
    const end = Math.min(start + chunkSize, file.size);
    const blob = file.slice(start, end);

    const res = await fetch(
      `${API}/files/uploads/${uploadId}/parts/${partNumber}`,
      {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/octet-stream",
        },
        body: blob,
      }
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Part ${partNumber} failed`);
    }
    completed++;
    onProgress(completed / totalParts);
    return res.json();
  }

  const queue = [...parts];
  const workers = Array.from(
    { length: Math.min(uploadParallelism(), queue.length || 1) },
    async () => {
      while (queue.length) {
        const part = queue.shift();
        await uploadPart(part);
      }
    }
  );
  await Promise.all(workers);

  return api(`/files/uploads/${uploadId}/complete`, { method: "POST" });
}

function putChunkXHR(uploadId, partNumber, blob, onChunkProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", `${API}/files/uploads/${uploadId}/parts/${partNumber}`);
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.timeout = 60000;
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onChunkProgress) onChunkProgress(e.loaded);
    };
    xhr.onload = () => {
      if (xhr.status === 401) {
        logout();
        return reject(new Error("Session expired"));
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText || "{}")); }
        catch { resolve({}); }
        return;
      }
      let detail = xhr.statusText;
      try { detail = JSON.parse(xhr.responseText).detail || detail; } catch {}
      reject(new Error(`Part ${partNumber}: ${detail} (HTTP ${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error(`Part ${partNumber}: network error`));
    xhr.ontimeout = () => reject(new Error(`Part ${partNumber}: timed out`));
    xhr.onabort = () => reject(new Error(`Part ${partNumber}: aborted`));
    xhr.send(blob);
  });
}

async function uploadMultipartSequential(file, uploadId, onProgress) {
  let partNumber = 1;
  let uploadedBytes = 0;
  const knownTotal = file.size > 0 ? file.size : 0;
  const totalParts = knownTotal > 0
    ? Math.max(1, Math.ceil(knownTotal / chunkSize))
    : 0;
  const maxRetries = 3;

  while (true) {
    const start = (partNumber - 1) * chunkSize;
    const end = knownTotal > 0
      ? Math.min(start + chunkSize, knownTotal)
      : start + chunkSize;
    const blob = file.slice(start, end);
    if (blob.size === 0) break;

    let lastErr = null;
    let success = false;
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        const partsLabel = totalParts > 0 ? `${partNumber}/${totalParts}` : `${partNumber}`;
        const retryLabel = attempt > 1 ? ` retry ${attempt}` : "";
        await putChunkXHR(uploadId, partNumber, blob, (loaded) => {
          const total = knownTotal > 0 ? knownTotal : uploadedBytes + blob.size;
          const pct = Math.min(99, Math.round(((uploadedBytes + loaded) / Math.max(total, 1)) * 100));
          const prog = $("upload-progress");
          if (prog) {
            prog.textContent = `${file.name}: chunk ${partsLabel}${retryLabel} - ${pct}%`;
          }
          onProgress(Math.min(0.99, (uploadedBytes + loaded) / Math.max(total, 1)));
        });
        success = true;
        break;
      } catch (e) {
        lastErr = e;
        const prog = $("upload-progress");
        if (prog) {
          prog.textContent = `${file.name}: chunk ${partNumber} failed (${e.message}), retrying...`;
        }
        await new Promise((r) => setTimeout(r, 500 * attempt));
      }
    }
    if (!success) throw lastErr || new Error(`Part ${partNumber} failed after retries`);

    uploadedBytes += blob.size;
    if (knownTotal > 0 && uploadedBytes >= knownTotal) {
      partNumber++;
      break;
    }
    partNumber++;
  }

  if (partNumber === 1) {
    throw new Error("File is empty or unreadable on this device");
  }

  onProgress(1);
  return api(`/files/uploads/${uploadId}/complete`, {
    method: "POST",
    body: JSON.stringify({ final_parts: partNumber - 1 }),
  });
}

function pickRoute(file) {
  if (isIOS && isVideoFile(file)) return "ios-single-post";
  if (file.size === 0) return "multipart-unknown";
  if (file.size > chunkSize) return "multipart-sized";
  return "simple-fetch";
}

async function handleFiles(fileList) {
  if (!canWrite) {
    alert("You do not have write access to this folder");
    return;
  }
  const files = Array.from(fileList);
  if (!files.length) return;

  const prog = $("upload-progress");
  show(prog);

  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    const sizeMB = (file.size / (1024 * 1024)).toFixed(2);
    const route = pickRoute(file);
    prog.textContent =
      `Uploading ${i + 1}/${files.length}: ${file.name} ` +
      `(${sizeMB} MB, route: ${route})`;
    try {
      await uploadFile(file, (p) => {
        prog.textContent =
          `${file.name} [${route}]: ${Math.round(p * 100)}% of ${sizeMB} MB`;
      });
    } catch (e) {
      alert(
        `Upload failed\n` +
          `File: ${file.name}\n` +
          `Size: ${sizeMB} MB\n` +
          `Type: ${file.type || "(none)"}\n` +
          `iOS: ${isIOS}\n` +
          `Route: ${route}\n` +
          `Error: ${e.message}`
      );
    }
  }

  hide(prog);
  await loadDirectory(currentPath);
}

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = $("login-error");
  hide(err);
  try {
    await login($("username").value.trim(), $("password").value);
  } catch (ex) {
    err.textContent = ex.message;
    show(err);
  }
});

$("logout-btn").addEventListener("click", logout);

$("back-btn").addEventListener("click", () => {
  const p = currentPath.replace(/\/$/, "") || "/";
  const parent = p === "/" ? "/" : p.substring(0, p.lastIndexOf("/")) || "/";
  loadDirectory(parent);
});

function createFileInput() {
  const input = document.createElement("input");
  input.type = "file";
  input.id = "file-input";
  input.multiple = true;
  input.accept = "video/quicktime,video/mp4,video/*,image/*";
  input.addEventListener("change", onFileInputChange);
  return input;
}

function resetFileInput() {
  const old = $("file-input");
  old.replaceWith(createFileInput());
}

function onFileInputChange(e) {
  const files = e.target.files;
  if (files?.length) handleFiles(files);
  resetFileInput();
}

$("file-input").replaceWith(createFileInput());

$("mkdir-btn").addEventListener("click", async () => {
  const name = prompt("Folder name:");
  if (!name) return;
  const path = `${currentPath.replace(/\/$/, "")}/${name}`.replace("//", "/");
  await api(`/files/mkdir?path=${encodeURIComponent(path)}`, { method: "POST" });
  await loadDirectory(currentPath);
});

const dropZone = $("drop-zone");
if ("draggable" in document.createElement("div")) {
  show(dropZone);
  ["dragenter", "dragover"].forEach((ev) => {
    document.addEventListener(ev, (e) => {
      e.preventDefault();
      dropZone.classList.add("active");
    });
  });
  ["dragleave", "drop"].forEach((ev) => {
    document.addEventListener(ev, (e) => {
      e.preventDefault();
      dropZone.classList.remove("active");
      if (ev === "drop" && e.dataTransfer?.files?.length) {
        handleFiles(e.dataTransfer.files);
      }
    });
  });
}

(async function init() {
  if (token) {
    try {
      const me = await api("/auth/me");
      currentUser = me;
      await openBrowser();
    } catch {
      logout();
    }
  }
})();
