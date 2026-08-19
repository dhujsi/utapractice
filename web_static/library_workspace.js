(() => {
  const librarySidePage = document.querySelector('.side-page[data-page-panel="library"]');
  const main = document.querySelector('.player');
  const playerView = document.getElementById('playerView');
  const workspaceView = document.getElementById('workspaceView');
  const librarySongSelect = document.getElementById('librarySongSelect');
  if (!librarySidePage || !main || !playerView || !workspaceView || !librarySongSelect) return;

  if (!document.querySelector('link[href="/web_static/library_workspace.css"]')) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/web_static/library_workspace.css';
    document.head.appendChild(link);
  }

  const directPanels = Array.from(librarySidePage.querySelectorAll(':scope > .panel'));
  const managementPanel = directPanels.find((panel) => panel.querySelector('#librarySongSelect')) || directPanels[0];
  const neteasePanel = document.getElementById('neteasePanel');
  const importPanels = directPanels.filter((panel) => panel !== managementPanel && panel !== neteasePanel);

  const catalogPanel = document.createElement('section');
  catalogPanel.className = 'panel library-sidebar-catalog';
  catalogPanel.innerHTML = `
    <div class="section-heading library-list-heading">
      <h2>歌库</h2>
      <span class="meta-line" id="librarySongCount"></span>
    </div>
    <label class="field library-filter-field">
      <span>筛选歌名</span>
      <input id="libraryListFilter" type="search" autocomplete="off" placeholder="输入歌名筛选">
    </label>
    <div class="library-song-list" id="librarySongList"></div>
  `;
  librarySidePage.insertBefore(catalogPanel, managementPanel || librarySidePage.firstChild);

  if (managementPanel) {
    managementPanel.classList.add('library-management-panel');
    const heading = managementPanel.querySelector('h2');
    if (heading) heading.textContent = '当前条目';
    const oldSelectorField = librarySongSelect.closest('.field');
    if (oldSelectorField) oldSelectorField.hidden = true;
  }

  const libraryView = document.createElement('section');
  libraryView.className = 'library-view';
  libraryView.id = 'libraryView';
  libraryView.hidden = true;
  libraryView.innerHTML = `
    <div class="workspace-header library-workspace-header">
      <div>
        <p class="meta-line">歌库工具</p>
        <h2>网易云下载与本地导入</h2>
      </div>
      <p class="status-line" id="libraryWorkspaceStatus">下载完成后会直接进入左侧歌库。</p>
    </div>
    <div class="library-detail-column" id="libraryDetailColumn"></div>
  `;
  main.insertBefore(libraryView, workspaceView);

  const detailColumn = libraryView.querySelector('#libraryDetailColumn');
  if (neteasePanel) {
    neteasePanel.classList.add('library-source-panel');
    detailColumn.appendChild(neteasePanel);
  }
  if (importPanels.length) {
    const importGrid = document.createElement('div');
    importGrid.className = 'library-import-grid';
    importPanels.forEach((panel) => importGrid.appendChild(panel));
    detailColumn.appendChild(importGrid);
  }

  const librarySongList = catalogPanel.querySelector('#librarySongList');
  const libraryListFilter = catalogPanel.querySelector('#libraryListFilter');
  const librarySongCount = catalogPanel.querySelector('#librarySongCount');

  function allSongs() {
    try {
      return Array.isArray(state?.songs) ? state.songs : [];
    } catch {
      return [];
    }
  }

  function songMeta(song) {
    const audio = song?.has_audio ? (song.audio_playable === false ? '音频不可用' : '有音频') : '无音频';
    const lyrics = song?.has_lyrics ? `${String(song.lyrics_type || '').toUpperCase() || '有'} 歌词` : '无歌词';
    return `${audio} · ${lyrics}`;
  }

  function ensureSelectOption(song) {
    let option = Array.from(librarySongSelect.options).find((item) => item.value === song.name);
    if (!option) {
      option = document.createElement('option');
      option.value = song.name;
      option.textContent = song.name;
      librarySongSelect.appendChild(option);
    }
  }

  function syncSelectedRow() {
    const selectedName = librarySongSelect.value;
    librarySongList.querySelectorAll('.library-song-row').forEach((row) => {
      row.classList.toggle('selected', row.dataset.songName === selectedName);
    });
  }

  function renderLibraryList() {
    const songs = allSongs();
    const query = String(libraryListFilter.value || '').trim().toLocaleLowerCase();
    const shown = query
      ? songs.filter((song) => String(song.name || '').toLocaleLowerCase().includes(query))
      : songs;

    librarySongList.innerHTML = '';
    librarySongCount.textContent = query ? `${shown.length}/${songs.length}` : `${songs.length} 首`;

    if (!shown.length) {
      const empty = document.createElement('p');
      empty.className = 'library-list-empty';
      empty.textContent = songs.length ? '没有匹配的歌曲' : '还没有歌曲';
      librarySongList.appendChild(empty);
      return;
    }

    shown.forEach((song) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'library-song-row';
      button.dataset.songName = song.name;

      const mainText = document.createElement('span');
      mainText.className = 'library-song-row-main';
      const title = document.createElement('strong');
      title.textContent = song.name;
      const meta = document.createElement('small');
      meta.textContent = songMeta(song);
      mainText.append(title, meta);

      const learned = document.createElement('span');
      learned.className = 'library-song-row-state';
      learned.textContent = song.learned ? '已学会' : '';
      button.append(mainText, learned);

      button.addEventListener('click', () => {
        ensureSelectOption(song);
        librarySongSelect.value = song.name;
        librarySongSelect.dispatchEvent(new Event('change', { bubbles: true }));
        syncSelectedRow();
      });
      librarySongList.appendChild(button);
    });
    syncSelectedRow();
  }

  let renderQueued = false;
  function scheduleLibraryRender() {
    if (renderQueued) return;
    renderQueued = true;
    queueMicrotask(() => {
      renderQueued = false;
      renderLibraryList();
    });
  }

  new MutationObserver(scheduleLibraryRender).observe(librarySongSelect, { childList: true, subtree: true });
  const libraryInfo = document.getElementById('librarySongInfo');
  if (libraryInfo) new MutationObserver(syncSelectedRow).observe(libraryInfo, { childList: true, subtree: true, characterData: true });
  libraryListFilter.addEventListener('input', renderLibraryList);
  librarySongSelect.addEventListener('change', syncSelectedRow);

  function syncMainViews(page) {
    playerView.hidden = page !== 'practice';
    workspaceView.hidden = page !== 'generator';
    libraryView.hidden = page !== 'library';
    if (page === 'library') renderLibraryList();
  }

  try {
    const coreSetPage = setPage;
    setPage = function setPageWithLibrary(page) {
      coreSetPage(page);
      syncMainViews(page);
    };
  } catch {
    document.querySelector('.side-nav')?.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-page]');
      if (button) syncMainViews(button.dataset.page);
    });
  }

  document.addEventListener('keydown', (event) => {
    let page = 'practice';
    try {
      page = state?.page || 'practice';
    } catch {
      page = 'practice';
    }
    if (page !== 'library' || event.code !== 'Space') return;
    if (['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(event.target?.tagName)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);

  let initialPage = 'practice';
  try {
    initialPage = state?.page || 'practice';
  } catch {
    initialPage = 'practice';
  }
  syncMainViews(initialPage);
  renderLibraryList();
})();
