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

  const libraryView = document.createElement('section');
  libraryView.className = 'library-view';
  libraryView.id = 'libraryView';
  libraryView.hidden = true;
  libraryView.innerHTML = `
    <div class="workspace-header library-workspace-header">
      <div>
        <p class="meta-line">本地歌库</p>
        <h2>歌曲、下载与导入</h2>
      </div>
      <p class="status-line" id="libraryWorkspaceStatus">正在读取歌库...</p>
    </div>
    <div class="library-main-grid">
      <section class="library-catalog" aria-label="本地歌曲列表">
        <div class="section-heading library-list-heading">
          <h2>歌曲列表</h2>
          <span class="meta-line" id="librarySongCount"></span>
        </div>
        <label class="field library-filter-field">
          <span>筛选歌名</span>
          <input id="libraryListFilter" type="search" autocomplete="off" placeholder="输入歌名筛选">
        </label>
        <div class="library-song-list" id="librarySongList"></div>
      </section>
      <div class="library-detail-column" id="libraryDetailColumn"></div>
    </div>
  `;
  main.insertBefore(libraryView, workspaceView);

  const detailColumn = libraryView.querySelector('#libraryDetailColumn');
  const librarySongList = libraryView.querySelector('#librarySongList');
  const libraryListFilter = libraryView.querySelector('#libraryListFilter');
  const librarySongCount = libraryView.querySelector('#librarySongCount');
  const libraryWorkspaceStatus = libraryView.querySelector('#libraryWorkspaceStatus');

  const directPanels = Array.from(librarySidePage.querySelectorAll(':scope > .panel'));
  const managementPanel = directPanels.find((panel) => panel.querySelector('#librarySongSelect')) || directPanels[0];
  const neteasePanel = document.getElementById('neteasePanel');
  const otherPanels = directPanels.filter((panel) => panel !== managementPanel && panel !== neteasePanel);

  if (managementPanel) {
    managementPanel.classList.add('library-management-panel');
    const heading = managementPanel.querySelector('h2');
    if (heading) heading.textContent = '当前条目';
    const oldSelectorField = librarySongSelect.closest('.field');
    if (oldSelectorField) oldSelectorField.hidden = true;
    detailColumn.appendChild(managementPanel);
  }

  if (neteasePanel) {
    neteasePanel.classList.add('library-source-panel');
    detailColumn.appendChild(neteasePanel);
  }

  if (otherPanels.length) {
    const importGrid = document.createElement('div');
    importGrid.className = 'library-import-grid';
    otherPanels.forEach((panel) => importGrid.appendChild(panel));
    detailColumn.appendChild(importGrid);
  }

  const sideNote = document.createElement('section');
  sideNote.className = 'panel library-side-note';
  sideNote.innerHTML = '<h2>歌库</h2><p class="meta-line">歌曲列表、网易云下载和本地导入已经移到右侧工作区。</p>';
  librarySidePage.appendChild(sideNote);

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
    return `${audio} · ${lyrics} · ${song?.learned ? '已学会' : '未学会'}`;
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
    librarySongCount.textContent = query ? `${shown.length} / ${songs.length}` : `${songs.length} 首`;
    libraryWorkspaceStatus.textContent = songs.length ? `本地共 ${songs.length} 首歌曲` : '本地歌库还是空的';

    if (!shown.length) {
      const empty = document.createElement('p');
      empty.className = 'library-list-empty';
      empty.textContent = songs.length ? '没有匹配的歌曲' : '还没有歌曲，可以从右侧下载或导入。';
      librarySongList.appendChild(empty);
      return;
    }

    shown.forEach((song) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'library-song-row';
      button.dataset.songName = song.name;

      const main = document.createElement('span');
      main.className = 'library-song-row-main';
      const title = document.createElement('strong');
      title.textContent = song.name;
      const meta = document.createElement('small');
      meta.textContent = songMeta(song);
      main.append(title, meta);

      const stateLabel = document.createElement('span');
      stateLabel.className = 'library-song-row-state';
      stateLabel.textContent = song.learned ? '已学会' : '';
      button.append(main, stateLabel);

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
