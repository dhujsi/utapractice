const state = {
  page: "practice",
  songs: [],
  current: null,
  lyrics: [],
  filter: "all",
  displayMode: "both",
  align: "center",
  activeLine: null,
  ab: { a: null, b: null },
  workspace: {
    results: [],
    selectedResult: null,
    preview: null,
    data: null,
  },
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
  playerView: document.getElementById("playerView"),
  workspaceView: document.getElementById("workspaceView"),
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
  refreshJobs: document.getElementById("refreshJobs"),
  jobList: document.getElementById("jobList"),
  workspaceStatus: document.getElementById("workspaceStatus"),
  workspaceSongName: document.getElementById("workspaceSongName"),
  workspaceArtist: document.getElementById("workspaceArtist"),
  workspaceAlbum: document.getElementById("workspaceAlbum"),
  workspaceProvider: document.getElementById("workspaceProvider"),
  searchLyrics: document.getElementById("searchLyrics"),
  usePreview: document.getElementById("usePreview"),
  saveWorkspace: document.getElementById("saveWorkspace"),
  realignWorkspace: document.getElementById("realignWorkspace"),
  generateWorkspaceRuby: document.getElementById("generateWorkspaceRuby"),
  previewGenerated: document.getElementById("previewGenerated"),
  publishWorkspace: document.getElementById("publishWorkspace"),
  searchSummary: document.getElementById("searchSummary"),
  searchResults: document.getElementById("searchResults"),
  mergedPreview: document.getElementById("mergedPreview"),
  workspaceOriginalLrc: document.getElementById("workspaceOriginalLrc"),
  workspaceTranslationLrc: document.getElementById("workspaceTranslationLrc"),
  workspaceRomanLrc: document.getElementById("workspaceRomanLrc"),
  generatedSummary: document.getElementById("generatedSummary"),
  generatedPreviewBox: document.getElementById("generatedPreviewBox"),
  toast: document.getElementById("toast"),
  openSidebar: document.getElementById("openSidebar"),
  closeSidebar: document.getElementById("closeSidebar"),
  sidebar: document.querySelector(".sidebar"),
};

let jobPollTimer = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatTime(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return "--:--";
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  const rest = String(total % 60).padStart(2, "0");
  return `${minutes}:${rest}`;
}

function formatDuration(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return "";
  const total = Math.max(0, Math.round(Number(seconds)));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return minutes ? `${minutes}分${rest}秒` : `${rest}秒`;
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

function setPage(page) {
  state.page = page;
  els.sideNav.querySelectorAll("button[data-page]").forEach((node) => {
    node.classList.toggle("active", node.dataset.page === page);
  });
  els.sidePages.forEach((panel) => panel.classList.toggle("active", panel.dataset.pagePanel === page));
  els.playerView.hidden = page === "generator";
  els.workspaceView.hidden = page !== "generator";
  if (page === "generator") {
    loadJobs().then(scheduleJobPollingIfNeeded).catch(() => {});
  }
  if (window.matchMedia("(max-width: 760px)").matches) els.sidebar.classList.remove("open");
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

function filteredSongs() {
  return state.songs.filter((song) => {
    if (state.filter === "learned") return song.learned;
    if (state.filter === "unlearned") return !song.learned;
    return true;
  });
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
  } else {
    loadSong(songs[0].name).catch((error) => showToast(error.message));
  }
  renderLibraryInfo();
}

function lineText(line) {
  const original = line.original_html || "";
  const translation = line.translation || "";
  if (state.displayMode === "original") return original || "";
  if (state.displayMode === "translation") return escapeHtml(translation || "");
  return translation ? `${original}<br><span class="translation-text">${escapeHtml(translation)}</span>` : original;
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
      els.audio.play().catch(() => {});
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
      if (currentTime > 0 && currentTime < els.audio.duration) els.audio.currentTime = currentTime;
      if (!wasPaused) els.audio.play().catch(() => {});
    },
    { once: true },
  );
}

async function loadSongs() {
  state.songs = await requestJson("/api/songs");
  renderSongSelect();
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
    els.audio.play().catch(() => {});
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

async function loadSettings() {
  const settings = await requestJson("/api/settings");
  els.baseUrlInput.value = settings.base_url || "";
  els.modelInput.value = settings.model || "";
  els.apiKeyInput.placeholder = settings.has_api_key ? "已保存，留空则不修改" : "尚未保存 API Key";
  els.aiSettingsStatus.textContent = settings.has_api_key
    ? `当前状态：已保存 API Key，模型 ${settings.model || "未设置"}`
    : "当前状态：尚未保存 API Key";
}

function jobStatusLabel(status) {
  const labels = { queued: "排队中", running: "生成中", done: "已完成", failed: "失败", stopped: "已停止", warning: "异常完成" };
  return labels[status] || status || "未知";
}

function jobStepMessages(job) {
  return (job.steps || []).map((step) => String(step.message || step || ""));
}

function jobHasFinalFailureLog(job) {
  return job.status === "done" && jobStepMessages(job).some((message) => {
    if (message.includes("次失败")) return false;
    return message.includes("段失败") || message.includes("生成失败") || message.includes("校验失败");
  });
}

function jobTypeLabel(job) {
  if (job.type === "generate_ruby_from_rows") return "工作页 ruby 生成";
  if (job.mode === "chunked") return "旧版实验性分段";
  return "旧版稳定整首";
}

function renderJobs(jobs) {
  els.jobList.innerHTML = "";
  if (!jobs.length) {
    const empty = document.createElement("p");
    empty.className = "meta-line";
    empty.textContent = "暂无任务";
    els.jobList.append(empty);
    return;
  }

  for (const job of jobs.slice(0, 12)) {
    const displayStatus = jobHasFinalFailureLog(job) ? "warning" : job.status;
    const item = document.createElement("article");
    item.className = `job-item ${displayStatus || ""}`;

    const title = document.createElement("div");
    title.className = "job-title";
    title.innerHTML = `<strong>${escapeHtml(job.song_name || "未命名")}</strong><span>${jobStatusLabel(displayStatus)}</span>`;
    item.append(title);

    const meta = document.createElement("p");
    meta.className = "meta-line";
    const runningSeconds =
      job.duration_seconds == null && job.started_at && job.status === "running"
        ? (Date.now() - new Date(job.started_at).getTime()) / 1000
        : job.duration_seconds;
    const duration = runningSeconds == null ? "" : ` · AI 用时 ${formatDuration(runningSeconds)}`;
    const progress = Number.isFinite(Number(job.progress)) ? ` · ${Number(job.progress)}%` : "";
    meta.textContent = `${jobTypeLabel(job)}${progress}${duration} · ${job.updated_at || job.created_at || ""}`;
    item.append(meta);

    if (Number.isFinite(Number(job.progress))) {
      const progressBar = document.createElement("div");
      progressBar.className = "job-progress";
      progressBar.innerHTML = `<span style="width:${Math.max(0, Math.min(100, Number(job.progress)))}%"></span>`;
      item.append(progressBar);
    }

    const stepMessages = jobStepMessages(job);
    const steps = document.createElement("div");
    steps.className = "job-steps";
    for (const message of stepMessages.slice(-8)) {
      const line = document.createElement("div");
      line.className = "job-step-line";
      line.textContent = message;
      steps.append(line);
    }
    item.append(steps);

    if (stepMessages.length > 8) {
      const details = document.createElement("details");
      details.className = "job-log-details";
      details.open = displayStatus === "failed" || displayStatus === "warning";
      const summary = document.createElement("summary");
      summary.textContent = `查看全部日志（${stepMessages.length} 条）`;
      details.append(summary);
      const allSteps = document.createElement("div");
      allSteps.className = "job-steps";
      for (const message of stepMessages) {
        const line = document.createElement("div");
        line.className = "job-step-line";
        line.textContent = message;
        allSteps.append(line);
      }
      details.append(allSteps);
      item.append(details);
    }

    if (job.status === "queued" || job.status === "running") {
      const stopButton = document.createElement("button");
      stopButton.type = "button";
      stopButton.textContent = job.stop_requested ? "停止中..." : "停止";
      stopButton.disabled = Boolean(job.stop_requested);
      stopButton.addEventListener("click", async () => {
        await requestJson(`/api/convert-jobs/${encodeURIComponent(job.id)}/stop`, { method: "POST", body: JSON.stringify({}) });
        await loadJobs();
        scheduleJobPolling();
      });
      item.append(stopButton);
    }
    if (["done", "failed", "stopped"].includes(job.status)) {
      const deleteButton = document.createElement("button");
      deleteButton.type = "button";
      deleteButton.className = "job-delete-button";
      deleteButton.textContent = "×";
      deleteButton.title = "删除任务";
      deleteButton.setAttribute("aria-label", "删除任务");
      deleteButton.addEventListener("click", async () => {
        await requestJson(`/api/convert-jobs/${encodeURIComponent(job.id)}`, { method: "DELETE" });
        await loadJobs();
      });
      item.prepend(deleteButton);
    }
    els.jobList.append(item);
  }
}

async function loadJobs() {
  const jobs = await requestJson("/api/convert-jobs");
  renderJobs(jobs);
  return jobs;
}

function scheduleJobPollingIfNeeded(jobs) {
  if (jobs.some((job) => job.status === "queued" || job.status === "running")) scheduleJobPolling();
}

function scheduleJobPolling() {
  if (jobPollTimer) clearInterval(jobPollTimer);
  jobPollTimer = setInterval(async () => {
    try {
      const jobs = await loadJobs();
      if (!jobs.some((job) => job.status === "queued" || job.status === "running")) {
        clearInterval(jobPollTimer);
        jobPollTimer = null;
      }
    } catch {
      clearInterval(jobPollTimer);
      jobPollTimer = null;
    }
  }, 2500);
}

function workspaceName() {
  return (els.workspaceSongName.value || state.workspace.selectedResult?.title || "").trim();
}

function setWorkspaceStatus(message) {
  els.workspaceStatus.textContent = message;
}

function renderSearchResults() {
  els.searchResults.innerHTML = "";
  els.searchSummary.textContent = state.workspace.results.length ? `${state.workspace.results.length} 条结果` : "暂无结果";
  state.workspace.results.forEach((result, index) => {
    const button = document.createElement("div");
    button.setAttribute("role", "button");
    button.tabIndex = 0;
    button.className = "search-result";
    button.dataset.index = String(index);
    button.innerHTML = `
      <strong>${escapeHtml(result.title || "未命名")}</strong>
      <span>${escapeHtml(result.artist || "未知歌手")} · ${escapeHtml(result.album || "未知专辑")}</span>
      <em>${escapeHtml(result.provider)} · ${result.duration ? formatTime(result.duration) : "未知时长"} · ${result.has_translation ? "含翻译" : "无翻译"}${result.has_roman ? " · 含注音" : ""}${result.has_word_timing ? " · 含逐字" : ""}</em>
    `;
    button.addEventListener("click", () => selectSearchResult(index));
    button.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectSearchResult(index);
      }
    });
    els.searchResults.append(button);
  });
}

function renderMergedRows(rows) {
  els.mergedPreview.innerHTML = "";
  if (!rows?.length) {
    els.mergedPreview.textContent = "暂无可预览内容";
    return;
  }
  for (const row of rows) {
    const item = document.createElement("div");
    item.className = "merged-row";
    item.innerHTML = `
      <span>${formatTime(row.time)}</span>
      <strong>${escapeHtml(row.original || "")}</strong>
      ${row.translation ? `<small>${escapeHtml(row.translation)}</small>` : ""}
      ${row.roman ? `<small>${escapeHtml(row.roman)}</small>` : ""}
    `;
    els.mergedPreview.append(item);
  }
}

function renderGenerated(lyrics) {
  els.generatedPreviewBox.innerHTML = "";
  els.generatedSummary.textContent = lyrics?.length ? `${lyrics.length} 行` : "尚未生成";
  if (!lyrics?.length) {
    els.generatedPreviewBox.textContent = "暂无生成结果";
    return;
  }
  for (const line of lyrics) {
    const item = document.createElement("div");
    item.className = "generated-row";
    item.innerHTML = `
      <span>${formatTime(line.time)}</span>
      <strong>${line.original_html || ""}</strong>
      ${line.translation ? `<small>${escapeHtml(line.translation)}</small>` : ""}
    `;
    els.generatedPreviewBox.append(item);
  }
}

function workspaceMatchesEditor(workspace) {
  if (!workspace) return false;
  return (
    (workspace.song_name || "") === workspaceName() &&
    (workspace.artist || "") === els.workspaceArtist.value.trim() &&
    (workspace.original_lrc || "") === els.workspaceOriginalLrc.value &&
    (workspace.translation_lrc || "") === els.workspaceTranslationLrc.value &&
    (workspace.roman_lrc || "") === els.workspaceRomanLrc.value
  );
}

function workspaceHasGenerated(workspace) {
  return (
    workspaceMatchesEditor(workspace) &&
    ["generated", "published"].includes(workspace.status) &&
    Array.isArray(workspace.generated_lyrics) &&
    workspace.generated_lyrics.length > 0
  );
}

function clearGeneratedPreview(message) {
  renderGenerated([]);
  if (state.workspace.data) {
    state.workspace.data.generated_lyrics = [];
    if (message) state.workspace.data.status = "draft";
  }
  if (message) setWorkspaceStatus(message);
}

function populateWorkspace(workspace) {
  state.workspace.data = workspace;
  els.workspaceSongName.value = workspace.song_name || workspaceName();
  els.workspaceArtist.value = workspace.artist || "";
  els.workspaceOriginalLrc.value = workspace.original_lrc || "";
  els.workspaceTranslationLrc.value = workspace.translation_lrc || "";
  els.workspaceRomanLrc.value = workspace.roman_lrc || "";
  renderMergedRows(workspace.line_rows || []);
  renderGenerated(workspace.generated_lyrics || []);
}

function renderPreview(preview) {
  state.workspace.preview = preview;
  els.workspaceOriginalLrc.value = preview.original_lrc || "";
  els.workspaceTranslationLrc.value = preview.translation_lrc || "";
  els.workspaceRomanLrc.value = preview.roman_lrc || "";
  renderMergedRows(preview.line_rows || []);
  clearGeneratedPreview("已切换来源预览，旧生成结果已隐藏");
}

async function selectSearchResult(index) {
  const result = state.workspace.results[index];
  if (!result) return;
  state.workspace.selectedResult = result;
  els.searchResults.querySelectorAll(".search-result").forEach((node) => node.classList.toggle("active", Number(node.dataset.index) === index));
  setWorkspaceStatus(`正在预览：${result.provider} · ${result.title || ""}`);
  try {
    const preview = await requestJson("/api/lyrics-preview", {
      method: "POST",
      body: JSON.stringify({ result }),
    });
    renderPreview(preview);
    setWorkspaceStatus(`已预览 ${result.provider} 版本，尚未保存`);
  } catch (error) {
    setWorkspaceStatus(`预览失败：${error.message}`);
    showToast("预览失败");
  }
}

async function searchLyrics() {
  const songName = workspaceName();
  if (!songName) {
    showToast("请先输入歌曲名");
    return;
  }
  els.searchLyrics.disabled = true;
  setWorkspaceStatus("正在搜索歌词来源...");
  try {
    const payload = {
      song_name: songName,
      artist: els.workspaceArtist.value.trim(),
      album: els.workspaceAlbum.value.trim(),
      provider: els.workspaceProvider.value,
      duration:
        state.current?.name === songName && Number.isFinite(els.audio.duration) && els.audio.duration > 0
          ? Math.round(els.audio.duration)
          : null,
    };
    const result = await requestJson("/api/lyrics-search", { method: "POST", body: JSON.stringify(payload) });
    state.workspace.results = result.results || [];
    state.workspace.selectedResult = null;
    state.workspace.preview = null;
    renderSearchResults();
    clearGeneratedPreview();
    const errorCount = Object.keys(result.errors || {}).length;
    setWorkspaceStatus(errorCount ? `搜索完成，${errorCount} 个来源失败，已显示可用结果` : "搜索完成");
  } catch (error) {
    setWorkspaceStatus(`搜索失败：${error.message}`);
    showToast("搜索失败");
  } finally {
    els.searchLyrics.disabled = false;
  }
}

function workspacePayload() {
  const current = state.workspace.data;
  const originalLrc = els.workspaceOriginalLrc.value;
  const translationLrc = els.workspaceTranslationLrc.value;
  const romanLrc = els.workspaceRomanLrc.value;
  const sourceUnchanged =
    current &&
    current.original_lrc === originalLrc &&
    current.translation_lrc === translationLrc &&
    current.roman_lrc === romanLrc;
  return {
    song_name: workspaceName(),
    artist: els.workspaceArtist.value.trim(),
    source: current?.source || {
      provider: state.workspace.selectedResult?.provider || "",
      song_id: state.workspace.selectedResult?.source_song_id || "",
      album: state.workspace.selectedResult?.album || "",
      duration: state.workspace.selectedResult?.duration ?? null,
    },
    original_lrc: originalLrc,
    translation_lrc: translationLrc,
    roman_lrc: romanLrc,
    generated_lyrics: sourceUnchanged ? current.generated_lyrics || [] : [],
  };
}

async function saveWorkspace({ silent = false } = {}) {
  const payload = workspacePayload();
  if (!payload.song_name) throw new Error("Song name is required");
  if (!payload.original_lrc.trim()) throw new Error("原文 LRC 不能为空");
  const workspace = await requestJson(`/api/lyrics-workspace/${encodeURIComponent(payload.song_name)}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  populateWorkspace(workspace);
  if (!silent) {
    setWorkspaceStatus("工作源已保存");
    showToast("工作源已保存");
  }
  return workspace;
}

async function usePreview() {
  const songName = workspaceName();
  if (!songName) {
    showToast("请先输入歌曲名");
    return;
  }
  if (!state.workspace.selectedResult || !state.workspace.preview) {
    showToast("请先选择一个搜索结果");
    return;
  }
  const workspace = await requestJson(`/api/lyrics-workspace/${encodeURIComponent(songName)}/use-preview`, {
    method: "POST",
    body: JSON.stringify({
      song_name: songName,
      artist: els.workspaceArtist.value.trim(),
      result: state.workspace.selectedResult,
      preview: state.workspace.preview,
    }),
  });
  populateWorkspace(workspace);
  setWorkspaceStatus("已保存为工作源");
  showToast("已保存工作源");
}

async function loadWorkspace(name) {
  const workspace = await requestJson(`/api/lyrics-workspace/${encodeURIComponent(name)}`);
  populateWorkspace(workspace);
  setWorkspaceStatus(`已载入工作源：${workspace.song_name}`);
  return workspace;
}

async function realignWorkspace() {
  const saved = await saveWorkspace({ silent: true });
  const workspace = await requestJson(`/api/lyrics-align/${encodeURIComponent(saved.song_name)}`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  populateWorkspace(workspace);
  setWorkspaceStatus("已重新对齐，生成结果已清空");
  showToast("已重新对齐");
}

async function generateWorkspaceRuby() {
  if (state.workspace.data) {
    state.workspace.data.generated_lyrics = [];
    state.workspace.data.status = "draft";
  }
  renderGenerated([]);
  const workspace = await saveWorkspace({ silent: true });
  workspace.status = "generating";
  workspace.generated_lyrics = [];
  workspace.errors = [];
  populateWorkspace(workspace);
  setWorkspaceStatus("正在提交 AI 生成任务...");
  const job = await requestJson("/api/convert-jobs", {
    method: "POST",
    body: JSON.stringify({
      type: "generate_ruby_from_rows",
      song_name: workspace.song_name,
      concurrency: 4,
    }),
  });
  setWorkspaceStatus(`任务已加入后台队列：${job.song_name}`);
  await loadJobs();
  scheduleJobPolling();
  showToast("后台任务已提交");
}

async function previewGenerated() {
  const name = workspaceName();
  if (!name) {
    showToast("请先输入歌曲名");
    return;
  }
  const workspace = await requestJson(`/api/lyrics-workspace/${encodeURIComponent(name)}`);
  if (!workspaceMatchesEditor(workspace)) {
    clearGeneratedPreview("当前编辑内容和已保存工作源不一致，请先保存并重新生成");
    showToast("没有当前内容对应的生成结果");
    return;
  }
  if (!workspaceHasGenerated(workspace)) {
    const message = workspace.status === "generating" ? "当前任务仍在生成中，完成后再预览" : "当前工作源尚未生成结果";
    clearGeneratedPreview(message);
    showToast("暂无可预览的生成结果");
    return;
  }
  populateWorkspace(workspace);
  setWorkspaceStatus(`已载入当前生成结果：${workspace.generated_lyrics.length} 行`);
}

async function publishWorkspace() {
  const name = workspaceName();
  if (!name) {
    showToast("请先输入歌曲名");
    return;
  }
  const result = await requestJson(`/api/lyrics-workspace/${encodeURIComponent(name)}/publish`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  setWorkspaceStatus(`已发布正式歌词：${result.published_count ?? result.lyrics_count} 行`);
  await loadSongs();
  if (state.current?.name === name) await loadSong(name);
  showToast("已发布为正式歌词");
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
els.libraryLoadSong.addEventListener("click", async () => {
  await loadSong(els.librarySongSelect.value);
  setPage("practice");
});
els.libraryEditLyrics.addEventListener("click", async () => {
  const song = selectedLibrarySong();
  if (!song) return;
  if (!state.current || state.current.name !== song.name) await loadSong(song.name);
  els.editLyrics.click();
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
  els.playButton.textContent = "⏸";
});
els.audio.addEventListener("pause", () => {
  els.playButton.textContent = "▶";
});
els.playButton.addEventListener("click", () => {
  if (!state.current?.has_audio) return;
  if (els.audio.paused) els.audio.play().catch(() => {});
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
els.mobileABButton.addEventListener("pointerdown", () => els.abHint.classList.add("visible"));
["pointerup", "pointercancel", "pointerleave"].forEach((eventName) => {
  els.mobileABButton.addEventListener(eventName, () => els.abHint.classList.remove("visible"));
});

els.sideNav.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-page]");
  if (!button) return;
  setPage(button.dataset.page);
});
document.addEventListener("keydown", (event) => {
  if (["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName)) return;
  if (event.code === "Space" && state.current?.has_audio && state.page !== "generator") {
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
    els.aiSettingsStatus.textContent = `当前状态：连接可用，${result.message || "OK"}`;
    showToast("AI 连接测试成功");
  } catch (error) {
    els.aiSettingsStatus.textContent = `当前状态：连接失败 - ${error.message}`;
    showToast("AI 连接测试失败");
  } finally {
    els.testApiSettings.disabled = false;
  }
});

els.searchLyrics.addEventListener("click", () => searchLyrics());
els.usePreview.addEventListener("click", () => usePreview().catch((error) => showToast(error.message)));
els.saveWorkspace.addEventListener("click", () => saveWorkspace().catch((error) => showToast(error.message)));
els.realignWorkspace.addEventListener("click", () => realignWorkspace().catch((error) => showToast(error.message)));
els.generateWorkspaceRuby.addEventListener("click", () => generateWorkspaceRuby().catch((error) => {
  setWorkspaceStatus(`提交失败：${error.message}`);
  showToast("提交失败");
}));
els.previewGenerated.addEventListener("click", () => previewGenerated().catch((error) => showToast(error.message)));
els.publishWorkspace.addEventListener("click", () => publishWorkspace().catch((error) => showToast(error.message)));
els.refreshJobs.addEventListener("click", () => loadJobs().catch((error) => showToast(error.message)));
els.openSidebar.addEventListener("click", () => els.sidebar.classList.add("open"));
els.closeSidebar.addEventListener("click", () => els.sidebar.classList.remove("open"));

Promise.all([loadSettings(), loadSongs(), loadJobs()])
  .then(([, , jobs]) => scheduleJobPollingIfNeeded(jobs))
  .catch((error) => showToast(error.message));
