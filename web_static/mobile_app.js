const storageKeys = {
  cloudConfigUrl: "utapractice.app.cloudConfigUrl",
  apiBaseUrl: "utapractice.app.apiBaseUrl",
};

const state = {
  apiBaseUrl: localStorage.getItem(storageKeys.apiBaseUrl) || window.location.origin,
  songs: [],
  currentSong: null,
};

const els = {
  cloudConfigUrl: document.getElementById("cloudConfigUrl"),
  apiBaseUrl: document.getElementById("apiBaseUrl"),
  syncCloud: document.getElementById("syncCloud"),
  useCurrentHost: document.getElementById("useCurrentHost"),
  connectServer: document.getElementById("connectServer"),
  connectionStatus: document.getElementById("connectionStatus"),
  serverList: document.getElementById("serverList"),
  refreshSongs: document.getElementById("refreshSongs"),
  songSelect: document.getElementById("songSelect"),
  songPanel: document.getElementById("songPanel"),
  songMeta: document.getElementById("songMeta"),
  songTitle: document.getElementById("songTitle"),
  audio: document.getElementById("audio"),
  lyrics: document.getElementById("lyrics"),
  toast: document.getElementById("toast"),
};

function cleanBaseUrl(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

function apiUrl(path) {
  return `${state.apiBaseUrl}${path}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => {
    els.toast.hidden = true;
  }, 2200);
}

function setStatus(message) {
  els.connectionStatus.textContent = message;
}

async function requestJson(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    headers: options.body instanceof FormData ? options.headers || {} : { "Content-Type": "application/json", ...(options.headers || {}) },
    mode: "cors",
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `请求失败：${response.status}`);
  return payload;
}

function saveServer(baseUrl) {
  state.apiBaseUrl = cleanBaseUrl(baseUrl);
  els.apiBaseUrl.value = state.apiBaseUrl;
  localStorage.setItem(storageKeys.apiBaseUrl, state.apiBaseUrl);
}

function normalizeCloudServers(config) {
  if (!config || typeof config !== "object") return [];
  if (Array.isArray(config.servers)) {
    return config.servers
      .map((server) => ({
        name: String(server.name || server.label || server.base_url || "未命名服务器"),
        baseUrl: cleanBaseUrl(server.base_url || server.baseUrl || server.url),
      }))
      .filter((server) => server.baseUrl);
  }
  const singleUrl = cleanBaseUrl(config.base_url || config.baseUrl || config.api_base_url || config.apiBaseUrl);
  return singleUrl ? [{ name: "云端默认服务器", baseUrl: singleUrl }] : [];
}

function renderCloudServers(servers) {
  els.serverList.innerHTML = "";
  if (!servers.length) {
    els.serverList.textContent = "云端配置中没有可用服务器";
    return;
  }
  for (const server of servers) {
    const button = document.createElement("button");
    button.type = "button";
    button.innerHTML = `<strong>${escapeHtml(server.name)}</strong><span>${escapeHtml(server.baseUrl)}</span>`;
    button.addEventListener("click", async () => {
      saveServer(server.baseUrl);
      await connectServer();
    });
    els.serverList.append(button);
  }
}

async function syncCloudConfig() {
  const url = cleanBaseUrl(els.cloudConfigUrl.value);
  if (!url) {
    showToast("请先填写云端配置 URL");
    return;
  }
  localStorage.setItem(storageKeys.cloudConfigUrl, url);
  els.syncCloud.disabled = true;
  setStatus("正在读取云端配置...");
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`云端返回 ${response.status}`);
    const config = await response.json();
    const servers = normalizeCloudServers(config);
    renderCloudServers(servers);
    const defaultUrl = cleanBaseUrl(config.default_base_url || config.defaultBaseUrl || config.default_server || servers[0]?.baseUrl);
    if (defaultUrl) saveServer(defaultUrl);
    setStatus(`已读取云端配置：${servers.length} 个服务器`);
  } catch (error) {
    setStatus(`云端配置读取失败：${error.message}`);
    showToast("同步失败");
  } finally {
    els.syncCloud.disabled = false;
  }
}

async function connectServer() {
  const nextBase = cleanBaseUrl(els.apiBaseUrl.value);
  if (!nextBase) {
    showToast("请填写服务器地址");
    return;
  }
  saveServer(nextBase);
  els.connectServer.disabled = true;
  setStatus("正在连接服务器...");
  try {
    const health = await requestJson("/api/app/health");
    setStatus(`已连接 ${health.name || "utapractice"} · ${health.songs_count ?? 0} 首歌`);
    await loadSongs();
  } catch (error) {
    setStatus(`连接失败：${error.message}`);
    showToast("服务器不可用");
  } finally {
    els.connectServer.disabled = false;
  }
}

function renderSongs() {
  els.songSelect.innerHTML = "";
  if (!state.songs.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "暂无歌曲";
    els.songSelect.append(option);
    return;
  }
  for (const song of state.songs) {
    const option = document.createElement("option");
    option.value = song.name;
    option.textContent = song.name;
    els.songSelect.append(option);
  }
}

async function loadSongs() {
  state.songs = await requestJson("/api/songs");
  renderSongs();
  if (state.songs[0]) await loadSong(state.songs[0].name);
}

function lineHtml(line) {
  const original = line.original_html || "";
  const translation = line.translation ? `<small>${escapeHtml(line.translation)}</small>` : "";
  return `${original}${translation}`;
}

function renderLyrics(lines) {
  els.lyrics.innerHTML = "";
  if (!Array.isArray(lines) || !lines.length) {
    els.lyrics.textContent = "这首歌没有歌词";
    return;
  }
  for (const line of lines) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "lyric-line";
    item.innerHTML = lineHtml(line);
    item.addEventListener("click", () => {
      if (!state.currentSong?.has_audio) return;
      els.audio.currentTime = Number(line.time || 0);
      els.audio.play().catch(() => {});
    });
    els.lyrics.append(item);
  }
}

async function loadSong(name) {
  if (!name) return;
  const song = await requestJson(`/api/songs/${encodeURIComponent(name)}`);
  state.currentSong = song;
  els.songPanel.hidden = false;
  els.songTitle.textContent = song.name;
  els.songMeta.textContent = `${song.has_audio ? "有音频" : "无音频"} · ${song.has_lyrics ? `${String(song.lyrics_type || "").toUpperCase()} 歌词` : "无歌词"}`;
  els.audio.pause();
  if (song.has_audio) {
    els.audio.hidden = false;
    els.audio.src = apiUrl(`/api/songs/${encodeURIComponent(song.name)}/audio?key=${Number(song.saved_key || 0)}`);
  } else {
    els.audio.hidden = true;
    els.audio.removeAttribute("src");
  }
  renderLyrics(song.lyrics || []);
}

els.cloudConfigUrl.value = localStorage.getItem(storageKeys.cloudConfigUrl) || "";
els.apiBaseUrl.value = state.apiBaseUrl;

els.syncCloud.addEventListener("click", () => syncCloudConfig());
els.useCurrentHost.addEventListener("click", () => {
  saveServer(window.location.origin);
  showToast("已填入当前访问地址");
});
els.connectServer.addEventListener("click", () => connectServer());
els.refreshSongs.addEventListener("click", () => loadSongs().catch((error) => showToast(error.message)));
els.songSelect.addEventListener("change", () => loadSong(els.songSelect.value).catch((error) => showToast(error.message)));

connectServer().catch(() => {});
