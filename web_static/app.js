const state = {
  songs: [],
  current: null,
  lyrics: [],
  filter: "all",
  displayMode: "both",
  align: "center",
  activeLine: null,
  ab: { a: null, b: null },
};

const els = {
  songSelect: document.getElementById("songSelect"),
  librarySongSelect: document.getElementById("librarySongSelect"),
  librarySongInfo: document.getElementById("librarySongInfo"),
  libraryLoadSong: document.getElementById("libraryLoadSong"),
  libraryEditLyrics: document.getElementById("libraryEditLyrics"),
  libraryDeleteSong: document.getElementById("libraryDeleteSong"),
  songTitle: document.getElementById("songTitle"),
  songAvailability: document.getElementById("songAvailability"),
  songPanel: document.getElementById("songPanel"),
  settingsPanel: document.getElementById("settingsPanel"),
  keyField: document.getElementById("keyField"),
  keySlider: document.getElementById("keySlider"),
  keyOutput: document.getElementById("keyOutput"),
  saveKey: document.getElementById("saveKey"),
  resetKey: document.getElementById("resetKey"),
  displayMode: document.getElementById("displayMode"),
  alignGroup: document.getElementById("alignGroup"),
  rangeInput: document.getElementById("rangeInput"),
  learnedInput: document.getElementById("learnedInput"),
  lyrics: document.getElementById("lyrics"),
  emptyState: document.getElementById("emptyState"),
  controls: document.getElementById("controls"),
  audio: document.getElementById("audio"),
  floatingControls: document.getElementById("floatingControls"),
  playButton: document.getElementById("playButton"),
  speedButton: document.getElementById("speedButton"),
  setAButton: document.getElementById("setAButton"),
  setBButton: document.getElementById("setBButton"),
  clearABButton: document.getElementById("clearABButton"),
  abStatus: document.getElementById("abStatus"),
  mobileABButton: document.getElementById("mobileABButton"),
  abHint: document.getElementById("abHint"),
  sideNav: document.querySelector(".side-nav"),
  sidePages: document.querySelectorAll(".side-page"),
  filterGroup: document.getElementById("filterGroup"),
  editLyrics: document.getElementById("editLyrics"),
  deleteSong: document.getElementById("deleteSong"),
  lyricsDialog: document.getElementById("lyricsDialog"),
  lyricsEditor: document.getElementById("lyricsEditor"),
  saveLyrics: document.getElementById("saveLyrics"),
  editorError: document.getElementById("editorError"),
  audioUploadInput: document.getElementById("audioUploadInput"),
  lyricsUploadInput: document.getElementById("lyricsUploadInput"),
  baseUrlInput: document.getElementById("baseUrlInput"),
  apiKeyInput: document.getElementById("apiKeyInput"),
  modelInput: document.getElementById("modelInput"),
  saveApiSettings: document.getElementById("saveApiSettings"),
  testApiSettings: document.getElementById("testApiSettings"),
  aiSettingsStatus: document.getElementById("aiSettingsStatus"),
  convertSongName: document.getElementById("convertSongName"),
  convertMode: document.getElementById("convertMode"),
  convertLrc: document.getElementById("convertLrc"),
  convertAnnotated: document.getElementById("convertAnnotated"),
  convertLyrics: document.getElementById("convertLyrics"),
  convertStatus: document.getElementById("convertStatus"),
  toast: document.getElementById("toast"),
  openSidebar: document.getElementById("openSidebar"),
  closeSidebar: document.getElementById("closeSidebar"),
  sidebar: document.querySelector(".sidebar"),
};

function formatTime(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return "--:--";
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  const rest = String(total % 60).padStart(2, "0");
  return `${minutes}:${rest}`;
}

function updateABStatus() {
  const { a, b } = state.ab;
  const active = a != null && b != null && b > a;
  els.abStatus.textContent = active ? `A ${formatTime(a)} → B ${formatTime(b)}` : `A ${formatTime(a)} · B ${formatTime(b)}`;
  els.clearABButton.disabled = a == null && b == null;
  els.mobileABButton.classList.toggle("active", active);
}

function resetAB() {
  state.ab = { a: null, b: null };
  updateABStatus();
}

function setABPoint(point) {
  const current = els.audio.currentTime || 0;
  if (point === "a") {
    state.ab.a = current;
    if (state.ab.b != null && state.ab.b <= current) state.ab.b = null;
  } else {
    state.ab.b = current;
    if (state.ab.a != null && state.ab.a >= current) state.ab.a = null;
  }
  updateABStatus();
}

function cycleMobileAB() {
  if (state.ab.a == null || (state.ab.a != null && state.ab.b != null)) {
    state.ab = { a: els.audio.currentTime || 0, b: null };
    showToast(`A 已设为 ${formatTime(state.ab.a)}`);
  } else {
    const current = els.audio.currentTime || 0;
    if (current <= state.ab.a) {
      showToast("B 点需要在 A 点之后");
      return;
    }
    state.ab.b = current;
    showToast(`B 已设为 ${formatTime(state.ab.b)}`);
  }
  updateABStatus();
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: options.body instanceof FormData ? options.headers || {} : { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || "请求失败");
  return payload;
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => {
    els.toast.hidden = true;
  }, 2200);
}

function filteredSongs() {
  return state.songs.filter((song) => {
    if (state.filter === "learned") return song.learned;
    if (state.filter === "unlearned") return !song.learned;
    return true;
  });
}

function renderSongSelect() {
  const songs = filteredSongs();
  els.songSelect.innerHTML = "";
  els.librarySongSelect.innerHTML = "";
  if (!songs.length) {
    const option = document.createElement("option");
    option.textContent = "暂无歌曲";
    option.value = "";
    els.songSelect.append(option);
    els.librarySongSelect.append(option.cloneNode(true));
    renderLibraryInfo();
    return;
  }
  for (const song of songs) {
    const option = document.createElement("option");
    option.value = song.name;
    const flags = [song.has_audio ? "音频" : null, song.has_lyrics ? song.lyrics_type?.toUpperCase() : null].filter(Boolean).join(" + ");
    option.textContent = `${song.name} (${flags || "空条目"})`;
    els.songSelect.append(option);
    els.librarySongSelect.append(option.cloneNode(true));
  }

  if (state.current && songs.some((song) => song.name === state.current.name)) {
    els.songSelect.value = state.current.name;
    els.librarySongSelect.value = state.current.name;
  } else if (songs.length) {
    loadSong(songs[0].name);
  }
  renderLibraryInfo();
}

function selectedLibrarySong() {
  return state.songs.find((song) => song.name === els.librarySongSelect.value) || null;
}

function renderLibraryInfo() {
  const song = selectedLibrarySong();
  if (!song) {
    els.librarySongInfo.textContent = "请选择歌曲";
    els.libraryLoadSong.disabled = true;
    els.libraryEditLyrics.disabled = true;
    els.libraryDeleteSong.disabled = true;
    return;
  }
  els.librarySongInfo.textContent = `${song.has_audio ? "有音频" : "无音频"} · ${song.has_lyrics ? `${song.lyrics_type?.toUpperCase()} 歌词` : "无歌词"} · ${song.learned ? "已学会" : "未学会"}`;
  els.libraryLoadSong.disabled = false;
  els.libraryEditLyrics.disabled = false;
  els.libraryDeleteSong.disabled = false;
}

function lineText(line) {
  const original = line.original_html || "";
  const translation = line.translation || "";
  if (state.displayMode === "original") return original;
  if (state.displayMode === "translation") return translation;
  return `${original}<br><span class="translation-text">${translation}</span>`;
}

function renderLyrics() {
  els.lyrics.className = `lyrics align-${state.align}`;
  els.lyrics.innerHTML = "";
  state.activeLine = null;

  if (!state.lyrics.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "这首歌还没有歌词";
    els.lyrics.append(empty);
    return;
  }

  for (let index = 0; index < state.lyrics.length; index += 1) {
    const line = state.lyrics[index];
    const node = document.createElement("div");
    node.className = "lyric-line";
    node.dataset.startTime = String(line.time ?? 0);
    node.dataset.endTime = String(state.lyrics[index + 1]?.time ?? 999999);
    node.innerHTML = lineText(line);
    node.addEventListener("click", () => {
      if (!state.current?.has_audio) return;
      els.audio.currentTime = Number(line.time || 0);
      els.audio.play();
    });
    els.lyrics.append(node);
  }
}

function syncAudioSource() {
  if (!state.current?.has_audio) return;
  const key = Number(els.keySlider.value);
  const currentTime = els.audio.currentTime || 0;
  const wasPaused = els.audio.paused;
  els.keyOutput.value = String(key);
  els.audio.src = `/api/songs/${encodeURIComponent(state.current.name)}/audio?key=${key}`;
  els.audio.addEventListener(
    "loadedmetadata",
    () => {
      if (currentTime > 0 && currentTime < els.audio.duration) {
        els.audio.currentTime = currentTime;
      }
      if (!wasPaused) els.audio.play();
    },
    { once: true },
  );
}

async function loadSongs() {
  state.songs = await requestJson("/api/songs");
  renderSongSelect();
}

async function loadSettings() {
  const settings = await requestJson("/api/settings");
  els.baseUrlInput.value = settings.base_url || "";
  els.modelInput.value = settings.model || "";
  els.apiKeyInput.placeholder = settings.has_api_key ? "已保存，留空则不修改" : "尚未保存 API Key";
  els.aiSettingsStatus.textContent = settings.has_api_key
    ? `当前状态：已保存 API Key，模型 ${settings.model || "未设置"}`
    : "当前状态：尚未保存 API Key";
}

async function loadSong(name) {
  if (!name) return;
  const song = await requestJson(`/api/songs/${encodeURIComponent(name)}`);
  state.current = song;
  state.lyrics = song.lyrics || [];

  els.emptyState.hidden = true;
  els.songPanel.hidden = false;
  els.settingsPanel.hidden = false;
  els.songTitle.textContent = `♫ ${song.name}`;
  els.songAvailability.textContent = `${song.has_audio ? "有音频" : "仅歌词/无音频"} · ${song.has_lyrics ? `${song.lyrics_type?.toUpperCase()} 歌词` : "无歌词"}`;
  els.keySlider.value = String(song.saved_key || 0);
  els.keyOutput.value = String(song.saved_key || 0);
  els.rangeInput.value = song.range || "";
  els.learnedInput.checked = Boolean(song.learned);
  els.keyField.hidden = !song.has_audio;
  els.saveKey.disabled = !song.has_audio;
  els.resetKey.disabled = !song.has_audio;
  els.controls.hidden = !song.has_audio;
  els.floatingControls.hidden = !song.has_audio;
  els.audio.pause();
  els.audio.removeAttribute("src");
  resetAB();

  if (song.has_audio) syncAudioSource();
  renderLyrics();
  els.songSelect.value = song.name;
  els.librarySongSelect.value = song.name;
  renderLibraryInfo();
}

function highlightCurrentLyric() {
  if (!state.current?.has_audio) return;
  const currentTime = els.audio.currentTime;
  if (state.ab.a != null && state.ab.b != null && state.ab.b > state.ab.a && currentTime >= state.ab.b) {
    els.audio.currentTime = state.ab.a;
    els.audio.play();
    return;
  }
  const lines = els.lyrics.querySelectorAll(".lyric-line");
  for (const line of lines) {
    const start = Number(line.dataset.startTime);
    const end = Number(line.dataset.endTime);
    if (currentTime >= start && currentTime < end) {
      if (line !== state.activeLine) {
        state.activeLine?.classList.remove("active");
        line.classList.add("active");
        state.activeLine = line;
        line.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      return;
    }
  }
  state.activeLine?.classList.remove("active");
  state.activeLine = null;
}

async function saveMeta(patch, message) {
  if (!state.current) return;
  const result = await requestJson(`/api/songs/${encodeURIComponent(state.current.name)}/meta`, {
    method: "POST",
    body: JSON.stringify(patch),
  });
  Object.assign(state.current, result.info || {});
  const song = state.songs.find((item) => item.name === state.current.name);
  if (song) Object.assign(song, result.info || {});
  showToast(message);
}

async function uploadFiles(input, fieldName, url) {
  const data = new FormData();
  for (const file of input.files) data.append(fieldName, file);
  await requestJson(url, { method: "POST", body: data });
  input.value = "";
  await loadSongs();
  showToast("上传完成");
}

els.filterGroup.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-filter]");
  if (!button) return;
  state.filter = button.dataset.filter;
  els.filterGroup.querySelectorAll("button").forEach((node) => node.classList.toggle("active", node === button));
  renderSongSelect();
});
els.songSelect.addEventListener("change", () => loadSong(els.songSelect.value));
els.librarySongSelect.addEventListener("change", renderLibraryInfo);
els.libraryLoadSong.addEventListener("click", () => loadSong(els.librarySongSelect.value));
els.keySlider.addEventListener("input", () => {
  els.keyOutput.value = els.keySlider.value;
});
els.keySlider.addEventListener("change", syncAudioSource);
els.saveKey.addEventListener("click", () => saveMeta({ saved_key: Number(els.keySlider.value) }, "默认 Key 已保存"));
els.resetKey.addEventListener("click", () => {
  els.keySlider.value = "0";
  els.keyOutput.value = "0";
  syncAudioSource();
});
els.displayMode.addEventListener("change", () => {
  state.displayMode = els.displayMode.value;
  renderLyrics();
});
els.alignGroup.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-align]");
  if (!button) return;
  state.align = button.dataset.align;
  els.alignGroup.querySelectorAll("button").forEach((node) => node.classList.toggle("active", node === button));
  renderLyrics();
});
els.rangeInput.addEventListener("change", () => saveMeta({ range: els.rangeInput.value }, "备注已保存"));
els.learnedInput.addEventListener("change", () => saveMeta({ learned: els.learnedInput.checked }, "状态已保存"));
els.audio.addEventListener("timeupdate", highlightCurrentLyric);
els.audio.addEventListener("play", () => {
  els.playButton.textContent = "❚❚";
});
els.audio.addEventListener("pause", () => {
  els.playButton.textContent = "▶";
});
els.playButton.addEventListener("click", () => {
  if (!state.current?.has_audio) return;
  if (els.audio.paused) els.audio.play();
  else els.audio.pause();
});
els.speedButton.addEventListener("click", () => {
  const next = els.audio.playbackRate === 1 ? 0.75 : els.audio.playbackRate === 0.75 ? 0.5 : 1;
  els.audio.playbackRate = next;
  els.speedButton.textContent = `${next.toFixed(2).replace(".00", "")}x`;
});
els.setAButton.addEventListener("click", () => setABPoint("a"));
els.setBButton.addEventListener("click", () => setABPoint("b"));
els.clearABButton.addEventListener("click", resetAB);
els.mobileABButton.addEventListener("click", cycleMobileAB);
els.mobileABButton.addEventListener("pointerdown", () => {
  els.abHint.classList.add("visible");
});
["pointerup", "pointercancel", "pointerleave"].forEach((eventName) => {
  els.mobileABButton.addEventListener(eventName, () => {
    els.abHint.classList.remove("visible");
  });
});
els.sideNav.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-page]");
  if (!button) return;
  const page = button.dataset.page;
  els.sideNav.querySelectorAll("button").forEach((node) => node.classList.toggle("active", node === button));
  els.sidePages.forEach((panel) => panel.classList.toggle("active", panel.dataset.pagePanel === page));
});
document.addEventListener("keydown", (event) => {
  if (["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName)) return;
  if (event.code === "Space" && state.current?.has_audio) {
    event.preventDefault();
    els.playButton.click();
  }
});
els.editLyrics.addEventListener("click", () => {
  if (!state.current) return;
  els.editorError.textContent = "";
  els.lyricsEditor.value = JSON.stringify(state.lyrics, null, 2);
  els.lyricsDialog.showModal();
});
els.libraryEditLyrics.addEventListener("click", async () => {
  const song = selectedLibrarySong();
  if (!song) return;
  if (!state.current || state.current.name !== song.name) {
    await loadSong(song.name);
  }
  els.editLyrics.click();
});
els.saveLyrics.addEventListener("click", async () => {
  try {
    const nextLyrics = JSON.parse(els.lyricsEditor.value);
    await requestJson(`/api/songs/${encodeURIComponent(state.current.name)}/lyrics`, {
      method: "POST",
      body: JSON.stringify(nextLyrics),
    });
    state.lyrics = nextLyrics;
    state.current.has_lyrics = true;
    state.current.lyrics_type = "json";
    renderLyrics();
    els.lyricsDialog.close();
    showToast("歌词已保存");
  } catch (error) {
    els.editorError.textContent = error.message;
  }
});
els.libraryDeleteSong.addEventListener("click", async () => {
  const song = selectedLibrarySong();
  if (!song) return;
  if (!confirm(`确定删除「${song.name}」吗？文件会移动到归档目录。`)) return;
  await requestJson(`/api/songs/${encodeURIComponent(song.name)}/delete`, { method: "POST" });
  state.current = null;
  await loadSongs();
  showToast("歌曲已归档");
});
els.audioUploadInput.addEventListener("change", () => uploadFiles(els.audioUploadInput, "audio", "/api/upload/audio"));
els.lyricsUploadInput.addEventListener("change", () => uploadFiles(els.lyricsUploadInput, "lyrics", "/api/upload/lyrics"));
els.saveApiSettings.addEventListener("click", async () => {
  els.saveApiSettings.disabled = true;
  els.aiSettingsStatus.textContent = "当前状态：正在保存接口设置...";
  try {
    await requestJson("/api/settings", {
      method: "POST",
      body: JSON.stringify({
        base_url: els.baseUrlInput.value,
        api_key: els.apiKeyInput.value,
        model: els.modelInput.value,
      }),
    });
    els.apiKeyInput.value = "";
    await loadSettings();
    els.aiSettingsStatus.textContent = "当前状态：接口设置已保存";
    showToast("接口设置已保存");
  } catch (error) {
    els.aiSettingsStatus.textContent = `当前状态：保存失败 - ${error.message}`;
    showToast("接口设置保存失败");
  } finally {
    els.saveApiSettings.disabled = false;
  }
});
els.testApiSettings.addEventListener("click", async () => {
  els.testApiSettings.disabled = true;
  els.aiSettingsStatus.textContent = "当前状态：正在测试连接...";
  try {
    const result = await requestJson("/api/settings/test", { method: "POST", body: JSON.stringify({}) });
    els.aiSettingsStatus.textContent = `当前状态：连接可用（${result.message || "OK"}）`;
    showToast("AI 连接测试成功");
  } catch (error) {
    els.aiSettingsStatus.textContent = `当前状态：连接失败 - ${error.message}`;
    showToast("AI 连接测试失败");
  } finally {
    els.testApiSettings.disabled = false;
  }
});
els.convertLyrics.addEventListener("click", async () => {
  els.convertLyrics.disabled = true;
  const oldText = els.convertLyrics.textContent;
  els.convertLyrics.textContent = "生成中...";
  const modeLabel = els.convertMode.value === "chunked" ? "实验性分段" : "稳定整首";
  els.convertStatus.textContent = `当前状态：正在使用${modeLabel}模式生成 JSON...`;
  try {
    const result = await requestJson("/api/convert-lyrics", {
      method: "POST",
      body: JSON.stringify({
        song_name: els.convertSongName.value,
        conversion_mode: els.convertMode.value,
        lrc_text: els.convertLrc.value,
        annotated_text: els.convertAnnotated.value,
      }),
    });
    await loadSongs();
    await loadSong(result.song_name);
    const details = Array.isArray(result.steps) ? `：${result.steps.join("；")}` : "";
    els.convertStatus.textContent = `当前状态：完成，已加入歌库「${result.song_name}」${details}`;
    showToast("JSON 已生成并加入歌库");
  } catch (error) {
    els.convertStatus.textContent = `当前状态：生成失败 - ${error.message}`;
    showToast("生成失败");
  } finally {
    els.convertLyrics.disabled = false;
    els.convertLyrics.textContent = oldText;
  }
});
els.openSidebar.addEventListener("click", () => els.sidebar.classList.add("open"));
els.closeSidebar.addEventListener("click", () => els.sidebar.classList.remove("open"));

Promise.all([loadSettings(), loadSongs()]).catch((error) => showToast(error.message));
