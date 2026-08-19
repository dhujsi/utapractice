(() => {
  const panel = document.getElementById("neteasePanel");
  if (!panel) return;

  const els = {
    bridgeUrl: document.getElementById("neteaseBridgeUrl"),
    saveBridge: document.getElementById("neteaseSaveBridge"),
    status: document.getElementById("neteaseStatus"),
    login: document.getElementById("neteaseLogin"),
    logout: document.getElementById("neteaseLogout"),
    qrWrap: document.getElementById("neteaseQrWrap"),
    qrImage: document.getElementById("neteaseQrImage"),
    qrMessage: document.getElementById("neteaseQrMessage"),
    query: document.getElementById("neteaseQuery"),
    search: document.getElementById("neteaseSearch"),
    quality: document.getElementById("neteaseQuality"),
    withLyrics: document.getElementById("neteaseWithLyrics"),
    results: document.getElementById("neteaseResults"),
    resultStatus: document.getElementById("neteaseResultStatus"),
    download: document.getElementById("neteaseDownload"),
  };

  const storageKey = "utapractice.neteaseBridgeBase";
  const state = {
    results: [],
    selectedId: null,
    qrTimer: null,
  };

  function defaultBridgeBase() {
    const host = window.location.hostname || "127.0.0.1";
    return `http://${host}:8503`;
  }

  function bridgeBase() {
    return String(els.bridgeUrl.value || "").trim().replace(/\/+$/, "");
  }

  function setBridgeBase(value) {
    const normalized = String(value || "").trim().replace(/\/+$/, "");
    els.bridgeUrl.value = normalized;
    localStorage.setItem(storageKey, normalized);
  }

  function setStatus(message, kind = "") {
    els.status.textContent = message;
    els.status.dataset.kind = kind;
  }

  function setResultStatus(message, kind = "") {
    els.resultStatus.textContent = message;
    els.resultStatus.dataset.kind = kind;
  }

  function formatDuration(ms) {
    const seconds = Math.max(0, Math.round(Number(ms || 0) / 1000));
    const minutes = Math.floor(seconds / 60);
    return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
  }

  async function bridgeRequest(path, options = {}) {
    const base = bridgeBase();
    if (!base) throw new Error("请先填写网易云桥接地址");
    const response = await fetch(`${base}${path}`, {
      headers: options.body ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers || {},
      ...options,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
    return payload;
  }

  async function refreshLoginStatus() {
    try {
      setStatus("正在检查网易云登录状态...");
      const payload = await bridgeRequest("/api/netease/status");
      if (payload.connected) {
        setStatus(payload.nickname ? `已登录：${payload.nickname}` : "网易云已登录", "success");
        els.login.hidden = true;
        els.logout.hidden = false;
        return true;
      }
      setStatus("未登录网易云；搜索可用，会员音频下载需要扫码登录");
      els.login.hidden = false;
      els.logout.hidden = true;
      return false;
    } catch (error) {
      setStatus(`桥接服务不可用：${error.message}`, "error");
      els.login.hidden = false;
      els.logout.hidden = true;
      return false;
    }
  }

  function stopQrPolling() {
    if (state.qrTimer) clearTimeout(state.qrTimer);
    state.qrTimer = null;
  }

  async function pollQr(key) {
    stopQrPolling();
    try {
      const payload = await bridgeRequest(`/api/netease/qr/check?key=${encodeURIComponent(key)}`);
      if (payload.code === 803) {
        els.qrMessage.textContent = "登录成功";
        stopQrPolling();
        setTimeout(() => {
          els.qrWrap.hidden = true;
        }, 800);
        await refreshLoginStatus();
        return;
      }
      if (payload.code === 800) {
        els.qrMessage.textContent = "二维码已过期，请重新生成";
        stopQrPolling();
        return;
      }
      els.qrMessage.textContent = payload.code === 802 ? "已扫码，请在网易云里确认" : "等待扫码...";
      state.qrTimer = setTimeout(() => pollQr(key), 1800);
    } catch (error) {
      els.qrMessage.textContent = `登录检查失败：${error.message}`;
      stopQrPolling();
    }
  }

  async function startQrLogin() {
    stopQrPolling();
    els.login.disabled = true;
    try {
      setStatus("正在生成登录二维码...");
      const payload = await bridgeRequest("/api/netease/qr/start", { method: "POST", body: "{}" });
      if (!payload.qrimg) throw new Error("网易云没有返回二维码图片");
      els.qrImage.src = payload.qrimg;
      els.qrWrap.hidden = false;
      els.qrMessage.textContent = "请用网易云音乐扫码";
      setStatus("二维码已生成，扫码后在手机上确认");
      pollQr(payload.key);
    } catch (error) {
      setStatus(error.message, "error");
    } finally {
      els.login.disabled = false;
    }
  }

  async function logout() {
    stopQrPolling();
    try {
      await bridgeRequest("/api/netease/logout", { method: "POST", body: "{}" });
      els.qrWrap.hidden = true;
      await refreshLoginStatus();
    } catch (error) {
      setStatus(error.message, "error");
    }
  }

  function renderResults() {
    els.results.innerHTML = "";
    if (!state.results.length) {
      els.results.innerHTML = '<p class="netease-empty">没有找到歌曲</p>';
      els.download.disabled = true;
      return;
    }

    state.results.forEach((song) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "netease-result";
      button.dataset.songId = String(song.id);
      button.innerHTML = `
        <span class="netease-result-main">
          <strong></strong>
          <small></small>
        </span>
        <span class="netease-result-duration">${formatDuration(song.duration)}</span>
      `;
      button.querySelector("strong").textContent = song.name || "未命名";
      const meta = [song.artist, song.album].filter(Boolean).join(" · ");
      button.querySelector("small").textContent = meta || "未知歌手";
      button.addEventListener("click", () => {
        state.selectedId = String(song.id);
        els.results.querySelectorAll(".netease-result").forEach((node) => {
          node.classList.toggle("selected", node === button);
        });
        els.download.disabled = false;
        setResultStatus(`已选：${song.name}${song.artist ? ` · ${song.artist}` : ""}`);
      });
      els.results.appendChild(button);
    });
  }

  async function search() {
    const query = String(els.query.value || "").trim();
    if (!query) {
      setResultStatus("先输入歌名或歌手", "error");
      return;
    }
    els.search.disabled = true;
    els.download.disabled = true;
    state.selectedId = null;
    try {
      setResultStatus("正在搜索网易云...");
      const payload = await bridgeRequest(`/api/netease/search?q=${encodeURIComponent(query)}&limit=20`);
      state.results = Array.isArray(payload.songs) ? payload.songs : [];
      renderResults();
      setResultStatus(state.results.length ? `找到 ${state.results.length} 首，点一首再下载` : "没有找到歌曲");
    } catch (error) {
      state.results = [];
      renderResults();
      setResultStatus(error.message, "error");
    } finally {
      els.search.disabled = false;
    }
  }

  async function downloadSelected() {
    const song = state.results.find((item) => String(item.id) === String(state.selectedId));
    if (!song) {
      setResultStatus("先选一首歌", "error");
      return;
    }

    els.download.disabled = true;
    els.search.disabled = true;
    try {
      setResultStatus(`正在下载「${song.name}」到歌库...`);
      const payload = await bridgeRequest("/api/netease/download", {
        method: "POST",
        body: JSON.stringify({
          id: song.id,
          name: song.name,
          artist: song.artist,
          level: els.quality.value,
          with_lyrics: els.withLyrics.checked,
        }),
      });
      const lyricNote = payload.lyrics_saved ? "，歌词也已保存" : "";
      setResultStatus(`已下载：${payload.filename}${lyricNote}`, "success");

      if (typeof refreshSongsAfterLibraryMutation === "function") {
        await refreshSongsAfterLibraryMutation(payload.song_name).catch(() => {});
      } else if (typeof loadSongs === "function") {
        await loadSongs().catch(() => {});
      }
    } catch (error) {
      setResultStatus(error.message, "error");
    } finally {
      els.download.disabled = false;
      els.search.disabled = false;
    }
  }

  els.saveBridge.addEventListener("click", () => {
    setBridgeBase(els.bridgeUrl.value);
    refreshLoginStatus();
  });
  els.login.addEventListener("click", startQrLogin);
  els.logout.addEventListener("click", logout);
  els.search.addEventListener("click", search);
  els.query.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      search();
    }
  });
  els.download.addEventListener("click", downloadSelected);

  setBridgeBase(localStorage.getItem(storageKey) || defaultBridgeBase());
  refreshLoginStatus();
})();
