(() => {
  const panel = document.getElementById("neteasePanel");
  if (!panel) return;
  const isAndroid = Boolean(window.UtaPracticeAndroid);
  // 不再隐藏面板：APK 端请求改走 AndroidBridge，经 Java 转发到网易云桥接，绕开 CORS/明文限制。

  document.getElementById("neteaseWithLyrics")?.closest(".check-row")?.remove();

  const els = {
    bridgeUrl: document.getElementById("neteaseBridgeUrl"),
    saveBridge: document.getElementById("neteaseSaveBridge"),
    status: document.getElementById("neteaseStatus"),
    login: document.getElementById("neteaseLogin"),
    logout: document.getElementById("neteaseLogout"),
    qrWrap: document.getElementById("neteaseQrWrap"),
    qrImage: document.getElementById("neteaseQrImage"),
    qrMessage: document.getElementById("neteaseQrMessage"),
    noScanStatus: document.getElementById("neteaseNoScanStatus"),
    countryCode: document.getElementById("neteaseCountryCode"),
    phone: document.getElementById("neteasePhone"),
    captcha: document.getElementById("neteaseCaptcha"),
    sendCaptcha: document.getElementById("neteaseSendCaptcha"),
    captchaLogin: document.getElementById("neteaseCaptchaLogin"),
    cookieInput: document.getElementById("neteaseCookieInput"),
    cookieLogin: document.getElementById("neteaseCookieLogin"),
    query: document.getElementById("neteaseQuery"),
    search: document.getElementById("neteaseSearch"),
    quality: document.getElementById("neteaseQuality"),
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
    // 空值 = 走同源代理 /api/netease/*（方案 C），规避 CORS / 明文端口 / 8503 不可达。
    return "";
  }

  function loadBridgeBase() {
    const saved = localStorage.getItem(storageKey);
    if (saved) {
      const host = window.location.hostname || "127.0.0.1";
      if (saved === `http://${host}:8503` || saved === "http://127.0.0.1:8503") {
        // 旧版自动生成的默认值，平滑迁移到同源代理
        return "";
      }
    }
    return saved || "";
  }

  function bridgeBase() {
    return String(els.bridgeUrl.value || "").trim().replace(/\/+$/, "");
  }

  function setBridgeBase(value) {
    const normalized = String(value || "").trim().replace(/\/+$/, "");
    els.bridgeUrl.value = normalized;
    localStorage.setItem(storageKey, normalized);
    if (isAndroid) window.UtaPracticeAndroid.setNeteaseBridgeUrl(normalized);
  }

  function setStatus(message, kind = "") {
    els.status.textContent = message;
    els.status.dataset.kind = kind;
  }

  function setResultStatus(message, kind = "") {
    els.resultStatus.textContent = message;
    els.resultStatus.dataset.kind = kind;
  }

  function setNoScanStatus(message, kind = "") {
    els.noScanStatus.textContent = message;
    els.noScanStatus.dataset.kind = kind;
  }

  async function sendCaptcha() {
    const phone = String(els.phone.value || "").trim();
    if (!/^[0-9+]{5,20}$/.test(phone)) {
      setNoScanStatus("请先输入正确的手机号", "error");
      return;
    }
    els.sendCaptcha.disabled = true;
    try {
      setNoScanStatus("正在发送验证码...");
      const payload = await bridgeRequest("/api/netease/captcha/sent", {
        method: "POST",
        body: JSON.stringify({ phone, countrycode: String(els.countryCode.value || "86").trim() }),
      });
      setNoScanStatus(payload.message || "验证码已发送", "success");
    } catch (error) {
      setNoScanStatus(error.message, "error");
    } finally {
      els.sendCaptcha.disabled = false;
    }
  }

  async function loginWithCaptcha() {
    const phone = String(els.phone.value || "").trim();
    const captcha = String(els.captcha.value || "").trim();
    if (!phone || !captcha) {
      setNoScanStatus("请填写手机号和验证码", "error");
      return;
    }
    els.captchaLogin.disabled = true;
    try {
      setNoScanStatus("正在登录...");
      const payload = await bridgeRequest("/api/netease/login/cellphone", {
        method: "POST",
        body: JSON.stringify({ phone, captcha, countrycode: String(els.countryCode.value || "86").trim() }),
      });
      setNoScanStatus(payload.message || "登录成功", "success");
      await refreshLoginStatus();
    } catch (error) {
      setNoScanStatus(error.message, "error");
    } finally {
      els.captchaLogin.disabled = false;
    }
  }

  async function saveCookieLogin() {
    const cookie = String(els.cookieInput.value || "").trim();
    if (!cookie) {
      setNoScanStatus("请先粘贴网易云 Cookie", "error");
      return;
    }
    els.cookieLogin.disabled = true;
    try {
      setNoScanStatus("正在保存并验证 Cookie...");
      const payload = await bridgeRequest("/api/netease/cookie", {
        method: "POST",
        body: JSON.stringify({ cookie }),
      });
      setNoScanStatus(payload.message || "Cookie 已保存", "success");
      await refreshLoginStatus();
    } catch (error) {
      setNoScanStatus(error.message, "error");
    } finally {
      els.cookieLogin.disabled = false;
    }
  }

  function formatDuration(ms) {
    const seconds = Math.max(0, Math.round(Number(ms || 0) / 1000));
    const minutes = Math.floor(seconds / 60);
    return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
  }

  async function bridgeRequest(path, options = {}) {
    const method = String(options.method || "GET").toUpperCase();
    const body = options.body || "";
    if (isAndroid) {
      // APK 端：经 AndroidBridge 由 Java 转发到网易云桥接（方案 C 移动端）
      const raw = window.UtaPracticeAndroid.apiRequest(method, path, body);
      const payload = JSON.parse(raw || "{}");
      if (payload && payload.error && !payload.ok) throw new Error(payload.error);
      return payload;
    }
    const base = bridgeBase();
    if (base) {
      // 用户显式填写的自定义桥接地址
      const response = await fetch(`${base}${path}`, {
        headers: body ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers || {},
        method,
        body: body || undefined,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
      return payload;
    }
    // 同源代理（方案 C）：页面由 Flask 提供，/api/netease/* 被 Flask 转发到 bridge
    const response = await fetch(path, {
      headers: body ? { "Content-Type": "application/json" } : {},
      method,
      body: body || undefined,
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
      const confirmFold = document.getElementById("neteaseConfirmFold");
      if (confirmFold) confirmFold.open = true;
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
          with_lyrics: false,
        }),
      });
      setResultStatus(`已下载：${payload.filename}`, "success");

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
  els.sendCaptcha.addEventListener("click", sendCaptcha);
  els.captchaLogin.addEventListener("click", loginWithCaptcha);
  els.cookieLogin.addEventListener("click", saveCookieLogin);
  els.captcha.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      loginWithCaptcha();
    }
  });

  if (isAndroid) {
    setBridgeBase(window.UtaPracticeAndroid.getNeteaseBridgeUrl());
  } else {
    setBridgeBase(loadBridgeBase());
  }
  refreshLoginStatus();
})();

(() => {
  const script = document.createElement("script");
  script.src = "/web_static/library_workspace.js";
  document.body.appendChild(script);
})();
