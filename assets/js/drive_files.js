(function () {
  const widgets = document.querySelectorAll('[data-drive-widget]');
  if (!widgets.length) return;

  const formatDate = (value) => {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '-';
    try {
      return new Intl.DateTimeFormat('es-ES', {
        dateStyle: 'short',
        timeStyle: 'short'
      }).format(date);
    } catch (err) {
      return date.toLocaleString();
    }
  };

  const formatModifiedDate = (modifiedValue, createdValue) => {
    if (!modifiedValue) return '-';
    const modifiedDate = new Date(modifiedValue);
    if (Number.isNaN(modifiedDate.getTime())) return '-';
    const createdDate = new Date(createdValue);
    if (!Number.isNaN(createdDate.getTime())) {
      if (modifiedDate.getTime() === createdDate.getTime()) return 'Sin cambios';
    }
    return formatDate(modifiedValue);
  };

  widgets.forEach((widget) => {
    const listUrl = widget.dataset.driveListUrl;
    const uploadUrl = widget.dataset.driveUploadUrl || listUrl;
    const downloadUrlTemplate = widget.dataset.driveDownloadUrl;
    const deleteUrlTemplate = widget.dataset.driveDeleteUrl;
    const historyUrl = widget.dataset.driveHistoryUrl;
    const restoreUrlTemplate = widget.dataset.driveRestoreUrl;
    const descriptionUrlTemplate = widget.dataset.driveDescriptionUrl;
    const canDelete = widget.dataset.driveCanDelete === 'true';
    const canHistory = widget.dataset.driveCanHistory === 'true';
    const dropzone = widget.querySelector('[data-drive-dropzone]');
    const fileInput = widget.querySelector('[data-drive-input]');
    const descModal = widget.querySelector('[data-drive-desc-modal]');
    const descTitle = widget.querySelector('[data-drive-desc-title]');
    const descHint = widget.querySelector('[data-drive-desc-hint]');
    const descClose = widget.querySelector('[data-drive-desc-close]');
    const descEnabled = widget.querySelector('[data-drive-desc-enabled]');
    const descText = widget.querySelector('[data-drive-desc-text]');
    const descCancel = widget.querySelector('[data-drive-desc-cancel]');
    const descConfirm = widget.querySelector('[data-drive-desc-confirm]');
    const statusEl = widget.querySelector('[data-drive-status]');
    const listBtn = widget.querySelector('[data-drive-open-list]');
    const listModal = widget.querySelector('[data-drive-list-modal]');
    const listHead = widget.querySelector('[data-drive-list-head]');
    const listBody = widget.querySelector('[data-drive-list-body]');
    const listClose = widget.querySelector('[data-drive-list-close]');
    const listRefresh = widget.querySelector('[data-drive-list-refresh]');
    const listHistoryBtn = widget.querySelector('[data-drive-history-btn]');
    const listBackBtn = widget.querySelector('[data-drive-back-btn]');
    const listSearch = widget.querySelector('[data-drive-list-search]');
    const conflictModal = widget.querySelector('[data-drive-conflict-modal]');
    const conflictBody = widget.querySelector('[data-drive-conflict-body]');
    const conflictClose = widget.querySelector('[data-drive-conflict-close]');
    const conflictConfirm = widget.querySelector('[data-drive-conflict-confirm]');
    const dialogModal = widget.querySelector('[data-drive-dialog-modal]');
    const dialogTitle = widget.querySelector('[data-drive-dialog-title]');
    const dialogMessage = widget.querySelector('[data-drive-dialog-message]');
    const dialogClose = widget.querySelector('[data-drive-dialog-close]');
    const dialogCancel = widget.querySelector('[data-drive-dialog-cancel]');
    const dialogConfirm = widget.querySelector('[data-drive-dialog-confirm]');
    const scopeLabel = widget.dataset.driveLabel || 'comision';
    const supportsDirectoryPicker = typeof window.showDirectoryPicker === 'function';
    const countEl = widget.querySelector('[data-drive-count]');
    const newChipEl = widget.querySelector('[data-drive-new-chip]');

    let pendingFiles = [];
    let currentListMode = 'active';
    let currentListColCount = 5;
    let lastActiveFiles = [];
    let isMarkingOnClose = false;
    let pendingUploadDescription = '';
    let pendingDescMode = null; // 'upload' | 'edit'
    let pendingDescFileId = null;
    let pendingDescFileName = null;

    const setStatus = (message, tone, isLoading) => {
      if (!statusEl) return;
      statusEl.textContent = message || '';
      statusEl.classList.remove('is-error', 'is-success');
      statusEl.classList.toggle('is-loading', Boolean(isLoading));
      if (tone) statusEl.classList.add(tone === 'error' ? 'is-error' : 'is-success');
    };

    const setBusy = (busy) => {
      if (dropzone) dropzone.classList.toggle('is-disabled', busy);
      if (fileInput) fileInput.disabled = Boolean(busy);
    };

    const setCount = (count) => {
      if (!countEl) return;
      if (typeof count === 'number') {
        countEl.textContent = `Archivos: ${count}`;
        return;
      }
      countEl.textContent = 'Archivos: -';
    };

    const setNewChip = (files) => {
      if (!newChipEl) return;
      const list = Array.isArray(files) ? files : [];
      const anyNew = list.some((file) => Boolean(file && file.isNew));
      newChipEl.style.display = anyNew ? '' : 'none';
    };

    const markFilesSeen = async (files) => {
      const list = Array.isArray(files) ? files : [];
      const pendingFiles = list.filter((file) => file && file.isNew && file.dbId);
      const pending = Array.from(new Set(pendingFiles.map((file) => file.dbId)));
      if (!pending.length) return 0;

      try {
        let marked = 0;
        for (const dbId of pending) {
          const response = await fetch('/api/me/seen', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Accept': 'application/json',
              'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin',
            body: JSON.stringify({ item_type: 'drivefile', item_id: dbId })
          }).catch(() => null);

          let ok = false;
          if (response && response.ok) {
            try {
              const data = await response.json();
              ok = Boolean(data && data.ok);
            } catch (err) {
              ok = false;
            }
          }

          if (ok) {
            marked += 1;
            pendingFiles
              .filter((file) => file && file.dbId === dbId)
              .forEach((file) => {
                file.isNew = false;
              });
          }
        }
        return marked;
      } catch (err) {
        // Silencioso: el UI no depende de esto.
      }

      return 0;
    };

    const toggleModal = (modal, show) => {
      if (!modal) return;
      modal.classList.toggle('open', show);
      modal.setAttribute('aria-hidden', show ? 'false' : 'true');
    };

    const showDialog = ({
      title,
      message,
      confirmText,
      cancelText,
      showCancel
    }) => {
      if (!dialogModal) return Promise.resolve(false);

      if (dialogTitle) dialogTitle.textContent = title || 'Confirmación';
      if (dialogMessage) dialogMessage.textContent = message || '';

      if (dialogConfirm) dialogConfirm.textContent = confirmText || 'Aceptar';
      if (dialogCancel) dialogCancel.textContent = cancelText || 'Cancelar';

      const wantsCancel = showCancel !== false;
      if (dialogCancel) dialogCancel.style.display = wantsCancel ? '' : 'none';

      toggleModal(dialogModal, true);

      return new Promise((resolve) => {
        let resolved = false;
        const cleanup = () => {
          dialogModal.removeEventListener('click', onOverlayClick);
          if (dialogClose) dialogClose.removeEventListener('click', onCancel);
          if (dialogCancel) dialogCancel.removeEventListener('click', onCancel);
          if (dialogConfirm) dialogConfirm.removeEventListener('click', onConfirm);
          document.removeEventListener('keydown', onEscape);
        };

        const finish = (value) => {
          if (resolved) return;
          resolved = true;
          cleanup();
          toggleModal(dialogModal, false);
          resolve(value);
        };

        const onConfirm = () => finish(true);
        const onCancel = () => finish(false);
        const onOverlayClick = (event) => {
          if (event.target === dialogModal) onCancel();
        };
        const onEscape = (event) => {
          if (event.key === 'Escape') onCancel();
        };

        dialogModal.addEventListener('click', onOverlayClick);
        if (dialogClose) dialogClose.addEventListener('click', onCancel);
        if (dialogCancel) dialogCancel.addEventListener('click', onCancel);
        if (dialogConfirm) dialogConfirm.addEventListener('click', onConfirm);
        document.addEventListener('keydown', onEscape);
      });
    };

    const openDescriptionModalForUpload = (files) => {
      if (!descModal) {
        // Sin modal, subimos sin descripción.
        pendingUploadDescription = '';
        uploadFiles();
        return;
      }

      pendingDescMode = 'upload';
      pendingDescFileId = null;
      pendingDescFileName = null;

      const count = files ? files.length : 0;
      if (descTitle) descTitle.textContent = 'Descripción de la subida';
      if (descHint) {
        if (count > 1) {
          descHint.textContent = `Has seleccionado ${count} archivos. La misma descripción se aplicará a todos. Puedes dejarla en blanco y editarla más tarde.`;
        } else {
          descHint.textContent = 'Puedes añadir una descripción al archivo. Puedes dejarla en blanco y editarla más tarde.';
        }
      }

      if (descEnabled) descEnabled.checked = false;
      if (descText) {
        descText.value = '';
        descText.disabled = true;
      }

      toggleModal(descModal, true);
    };

    const openDescriptionModalForEdit = (fileId, fileName, currentValue) => {
      if (!descModal || !descriptionUrlTemplate) return;

      pendingDescMode = 'edit';
      pendingDescFileId = fileId;
      pendingDescFileName = fileName;

      if (descTitle) descTitle.textContent = 'Editar descripción';
      if (descHint) descHint.textContent = `Archivo: ${fileName || 'archivo'}`;

      if (descEnabled) descEnabled.checked = true;
      if (descText) {
        descText.disabled = false;
        descText.value = (currentValue || '').toString();
        setTimeout(() => descText.focus(), 0);
      }

      toggleModal(descModal, true);
    };

    const cancelConflicts = () => {
      pendingFiles = [];
      if (fileInput) fileInput.value = '';
      setBusy(false);
      setStatus('Subida cancelada.', null, false);
    };

    const closeModalOnEscape = (event) => {
      if (event.key !== 'Escape') return;
      if (dialogModal && dialogModal.classList.contains('open')) return;
      if (listModal && listModal.classList.contains('open')) closeListModal();
      if (conflictModal && conflictModal.classList.contains('open')) {
        toggleModal(conflictModal, false);
        cancelConflicts();
      }
    };

    document.addEventListener('keydown', closeModalOnEscape);

    const prepareFiles = (files) => {
      if (!files || !files.length) return;
      pendingFiles = Array.from(files);
      openDescriptionModalForUpload(pendingFiles);
    };

    const buildConflictRow = (conflict, index) => {
      const row = document.createElement('div');
      row.className = 'drive-conflict-row';
      row.dataset.fileName = conflict.name;
      const nameEl = document.createElement('div');
      nameEl.className = 'drive-conflict-name';
      nameEl.textContent = conflict.name;

      const metaEl = document.createElement('div');
      metaEl.className = 'drive-conflict-meta';
      metaEl.textContent = `Modificado: ${formatDate(conflict.modifiedTime)} · Subido: ${formatDate(conflict.createdTime)}`;

      const options = document.createElement('div');
      options.className = 'drive-conflict-options';
      const groupName = `drive-conflict-${index}`;

      const optionOverwrite = document.createElement('label');
      const canOverwrite = conflict.canOverwrite !== false;
      optionOverwrite.innerHTML = `<input type="radio" name="${groupName}" value="overwrite" ${canOverwrite ? '' : 'disabled'}> Sobrescribir`;

      const optionRename = document.createElement('label');
      optionRename.innerHTML = `<input type="radio" name="${groupName}" value="rename"> Renombrar`;

      const optionSkip = document.createElement('label');
      optionSkip.innerHTML = `<input type="radio" name="${groupName}" value="skip"> Omitir`;

      const renameInput = document.createElement('input');
      renameInput.type = 'text';
      renameInput.className = 'drive-conflict-rename';
      renameInput.placeholder = 'Nuevo nombre';
      renameInput.value = conflict.name;
      renameInput.disabled = true;
      renameInput.addEventListener('input', () => {
        renameInput.classList.remove('is-error');
      });

      options.append(optionOverwrite, optionRename, optionSkip, renameInput);

      if (!canOverwrite) {
        const note = document.createElement('div');
        note.className = 'drive-conflict-note';
        note.textContent = 'No tienes permiso para sobrescribir (solo 2 días para el autor; luego coordinadores/administradores).';
        options.appendChild(note);
      }

      options.addEventListener('change', (event) => {
        const target = event.target;
        if (!target || target.name !== groupName) return;
        renameInput.disabled = target.value !== 'rename';
        if (target.value !== 'rename') {
          renameInput.value = conflict.name;
        } else {
          renameInput.focus();
          renameInput.select();
        }
      });

      row.append(nameEl, metaEl, options);
      return row;
    };

    const uploadFiles = async (resolutions) => {
      if (!pendingFiles.length) return;
      if (!uploadUrl) {
        setStatus('No se pudo determinar el endpoint de subida.', 'error');
        return;
      }

      const formData = new FormData();
      pendingFiles.forEach((file) => formData.append('files', file, file.name));
      formData.append('description', pendingUploadDescription || '');
      if (resolutions) formData.append('resolutions', JSON.stringify(resolutions));

      setBusy(true);
      setStatus(`Subiendo ${pendingFiles.length} archivo(s) a la ${scopeLabel}...`, null, true);

      try {
        const response = await fetch(uploadUrl, {
          method: 'POST',
          body: formData,
          headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        const data = await response.json();

        if (response.status === 409 && data.conflicts) {
          setBusy(false);
          setStatus('Hay archivos duplicados. Revisa las opciones.', null, false);
          conflictBody.innerHTML = '';
          data.conflicts.forEach((conflict, index) => {
            conflictBody.appendChild(buildConflictRow(conflict, index));
          });
          toggleModal(conflictModal, true);
          return;
        }

        if (!data.ok) {
          setBusy(false);
          setStatus(data.error || 'No se pudo subir los archivos.', 'error', false);
          return;
        }

        const uploaded = data.uploaded || [];
        const skipped = data.skipped || [];
        const message = `Archivos subidos: ${uploaded.length}. Omitidos: ${skipped.length}.`;
        setBusy(false);
        setStatus(message, 'success', false);

        if (uploaded.length) {
          await showDialog({
            title: 'Normas de edición',
            message:
              'Puedes modificar o eliminar los archivos que subas durante los próximos 2 días. Pasado ese plazo, solo coordinadores/administradores podrán hacerlo.',
            confirmText: 'Entendido',
            showCancel: false
          });
        }

        pendingFiles = [];
        if (fileInput) fileInput.value = '';
        pendingUploadDescription = '';
        if (listModal && listModal.classList.contains('open')) loadFileList();
        refreshCount();
      } catch (err) {
        setBusy(false);
        setStatus('Error inesperado subiendo archivos.', 'error', false);
      }
    };

    const setTableHead = (mode) => {
      if (!listHead) return;
      if (mode === 'history') {
        listHead.innerHTML = `
          <tr>
            <th>Nombre</th>
            <th>Descripción</th>
            <th>Subido</th>
            <th>Modificado</th>
            <th>Eliminado</th>
            <th></th>
          </tr>
        `;
        return;
      }

      listHead.innerHTML = `
        <tr>
          <th>Nombre</th>
          <th>Descripción</th>
          <th>Modificado</th>
          <th>Subido</th>
          <th></th>
        </tr>
      `;
    };

    const renderEmptyRow = (colspan, message) => {
      const row = document.createElement('tr');
      row.innerHTML = `<td colspan="${colspan}" class="drive-files-empty">${message}</td>`;
      return row;
    };

    const applySearchFilter = () => {
      if (!listSearch || !listBody) return;
      const query = (listSearch.value || '').trim().toLowerCase();

      // Eliminar row de "sin resultados" previa.
      const oldEmpty = listBody.querySelector('tr[data-drive-search-empty]');
      if (oldEmpty) oldEmpty.remove();

      const rows = Array.from(listBody.querySelectorAll('tr'));
      let visible = 0;

      rows.forEach((row) => {
        if (row.querySelector('.drive-files-empty')) return;
        const haystack = (row.dataset.searchText || '').toLowerCase();
        const match = !query || haystack.includes(query);
        row.style.display = match ? '' : 'none';
        if (match) visible += 1;
      });

      if (!query) return;

      if (visible === 0 && rows.length) {
        const empty = renderEmptyRow(currentListColCount, 'No hay resultados para la búsqueda.');
        empty.setAttribute('data-drive-search-empty', 'true');
        listBody.appendChild(empty);
      }
    };

    const renderDescriptionCell = (file) => {
      const cell = document.createElement('td');
      const wrap = document.createElement('div');
      wrap.className = 'drive-files-desc-wrap';

      const text = document.createElement('span');
      text.className = 'drive-files-desc-text';
      text.textContent = (file.description || '').toString() || '—';
      wrap.appendChild(text);

      const canEditDescription =
        file && typeof file.canEditDescription === 'boolean' ? file.canEditDescription : canDelete;
      if (canEditDescription && descriptionUrlTemplate) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'drive-files-edit-desc';
        btn.setAttribute('title', 'Editar descripción');
        btn.setAttribute('aria-label', 'Editar descripción');
        btn.setAttribute('data-drive-edit-desc', '');
        btn.dataset.fileId = file.id;
        btn.dataset.fileName = file.name || 'archivo';
        btn.dataset.currentDescription = (file.description || '').toString();
        btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false"><path d="M12 20h9" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
        wrap.appendChild(btn);
      }

      cell.appendChild(wrap);
      return cell;
    };

    const loadFileList = async (mode) => {
      const resolvedMode = mode || currentListMode || 'active';
      currentListMode = resolvedMode;

      const url = resolvedMode === 'history' ? historyUrl : listUrl;
      const colCount = resolvedMode === 'history' ? 6 : 5;
      currentListColCount = colCount;
      if (!url) return;
      if (!listBody) return;
      listBody.innerHTML = '';

      setTableHead(resolvedMode);
      listBody.appendChild(renderEmptyRow(colCount, 'Cargando archivos...'));

      if (listHistoryBtn) {
        listHistoryBtn.style.display = canHistory && historyUrl ? '' : 'none';
      }
      if (listBackBtn) {
        listBackBtn.style.display = resolvedMode === 'history' ? '' : 'none';
      }

      try {
        const response = await fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        const data = await response.json();
        if (!data.ok) {
          listBody.innerHTML = '';
          listBody.appendChild(renderEmptyRow(colCount, data.error || 'No se pudo cargar la lista.'));
          return;
        }

        const files = data.files || [];
        if (resolvedMode === 'active') lastActiveFiles = files;
        if (resolvedMode === 'active') setCount(files.length);
        if (resolvedMode === 'active') setNewChip(files);
        if (!files.length) {
          listBody.innerHTML = '';
          listBody.appendChild(renderEmptyRow(colCount, 'No hay archivos en la carpeta.'));
          return;
        }

        listBody.innerHTML = '';
        files.forEach((file) => {
          const downloadUrl = downloadUrlTemplate
            ? downloadUrlTemplate.replace('__FILE_ID__', file.id)
            : '#';
          const rowEl = document.createElement('tr');
          rowEl.dataset.searchText = `${(file.name || '').toString()} ${(file.description || '').toString()}`.trim();
          const nameCell = document.createElement('td');
          const nameText = document.createElement('span');
          nameText.className = 'drive-files-name';
          nameText.textContent = file.name || '-';
          nameCell.appendChild(nameText);

          if (file && file.isNew) {
            const chip = document.createElement('span');
            chip.className = 'chip chip--new';
            chip.textContent = 'Nuevo';
            chip.style.marginLeft = '0.5rem';
            nameCell.appendChild(chip);
          }

          const descCell = renderDescriptionCell(file);

          const buildAuditCell = (whenValue, byValue) => {
            const cell = document.createElement('td');
            const wrap = document.createElement('div');
            wrap.className = 'drive-files-audit';
            const dateEl = document.createElement('div');
            dateEl.className = 'drive-files-audit__date';
            dateEl.textContent = formatDate(whenValue);
            const byEl = document.createElement('div');
            byEl.className = 'drive-files-audit__by';
            byEl.textContent = byValue ? `por ${byValue}` : '-';
            wrap.append(dateEl, byEl);
            cell.appendChild(wrap);
            return cell;
          };

          let uploadedOrCreatedCell;
          let modifiedCell;
          let deletedCell = null;

          if (resolvedMode === 'history') {
            uploadedOrCreatedCell = buildAuditCell(file.uploadedAt, file.uploadedBy);
            modifiedCell = buildAuditCell(file.modifiedAt, file.modifiedBy);
            deletedCell = buildAuditCell(file.deletedAt, file.deletedBy);
          } else {
            uploadedOrCreatedCell = document.createElement('td');
            uploadedOrCreatedCell.textContent = formatDate(file.createdTime);

            modifiedCell = document.createElement('td');
            const modifiedLabel = file.modifiedAt
              ? formatDate(file.modifiedAt)
              : formatModifiedDate(file.modifiedTime, file.createdTime);
            modifiedCell.textContent = modifiedLabel;
          }

          const actionCell = document.createElement('td');
          const actionWrap = document.createElement('div');
          actionWrap.className = 'drive-files-actions-cell';

          const downloadLink = document.createElement('a');
          downloadLink.className = 'drive-files-download';
          downloadLink.href = downloadUrl;
          downloadLink.setAttribute('aria-label', 'Descargar archivo');
          downloadLink.setAttribute('title', 'Descargar');
          downloadLink.innerHTML = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false"><path d="M12 3v12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /><path d="M7 11l5 5 5-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /><path d="M5 21h14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /></svg>';
          downloadLink.setAttribute('data-no-loader', '');
          downloadLink.setAttribute('data-drive-download', '');
          downloadLink.dataset.fileName = file.name || 'archivo';
          actionWrap.appendChild(downloadLink);

          const canDeleteFile =
            file && typeof file.canDelete === 'boolean' ? file.canDelete : canDelete;
          if (canDeleteFile && deleteUrlTemplate) {
            const deleteBtn = document.createElement('button');
            deleteBtn.type = 'button';
            deleteBtn.className = 'drive-files-delete';
            deleteBtn.setAttribute('aria-label', 'Eliminar archivo');
            deleteBtn.setAttribute('title', 'Eliminar');
            deleteBtn.setAttribute('data-drive-delete', '');
            deleteBtn.dataset.fileId = file.id;
            deleteBtn.dataset.fileName = file.name || 'archivo';
            deleteBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6h14Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /><path d="M10 11v6M14 11v6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /></svg>';
            actionWrap.appendChild(deleteBtn);
          }

          const canRestoreFile =
            file && typeof file.canRestore === 'boolean' ? file.canRestore : false;
          if (resolvedMode === 'history' && restoreUrlTemplate && file.deletedAt && canRestoreFile) {
            const restoreBtn = document.createElement('button');
            restoreBtn.type = 'button';
            restoreBtn.className = 'drive-files-restore';
            restoreBtn.setAttribute('aria-label', 'Restaurar archivo');
            restoreBtn.setAttribute('title', 'Restaurar');
            restoreBtn.setAttribute('data-drive-restore', '');
            restoreBtn.dataset.fileId = file.id;
            restoreBtn.dataset.fileName = file.name || 'archivo';
            restoreBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false"><path d="M3 12a9 9 0 1 0 3-6.7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M3 4v5h5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
            actionWrap.appendChild(restoreBtn);
          }

          actionCell.appendChild(actionWrap);

          if (resolvedMode === 'history') {
            rowEl.append(nameCell, descCell, uploadedOrCreatedCell, modifiedCell, deletedCell, actionCell);
          } else {
            rowEl.append(nameCell, descCell, modifiedCell, uploadedOrCreatedCell, actionCell);
          }
          listBody.appendChild(rowEl);
        });

        applySearchFilter();
      } catch (err) {
        if (resolvedMode === 'active') setCount(null);
        if (resolvedMode === 'active') setNewChip([]);
        listBody.innerHTML = '';
        listBody.appendChild(renderEmptyRow(colCount, 'Error cargando archivos.'));
      }
    };

    const saveDescription = async (fileId, value) => {
      if (!descriptionUrlTemplate || !fileId) return;
      const url = descriptionUrlTemplate.replace('__FILE_ID__', fileId);
      setStatus('Guardando descripcion...', null, true);
      try {
        const response = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
          },
          credentials: 'same-origin',
          body: JSON.stringify({ description: value || '' })
        });
        const data = await response.json();
        if (!data.ok) throw new Error(data.error || 'save_failed');
        setStatus('Descripcion guardada.', 'success', false);
      } catch (err) {
        setStatus('No se pudo guardar la descripcion.', 'error', false);
      }
    };

    const restoreFile = async (fileId, fileName) => {
      if (!restoreUrlTemplate || !fileId) return;
      const confirmed = await showDialog({
        title: 'Restaurar archivo',
        message: `¿Restaurar "${fileName || 'archivo'}"?`,
        confirmText: 'Restaurar',
        cancelText: 'Cancelar',
        showCancel: true
      });
      if (!confirmed) return;
      const url = restoreUrlTemplate.replace('__FILE_ID__', fileId);
      setStatus('Restaurando archivo...', null, true);
      try {
        const response = await fetch(url, {
          method: 'POST',
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
          credentials: 'same-origin'
        });
        const data = await response.json();
        if (!data.ok) {
          await showDialog({
            title: 'No se pudo restaurar',
            message: data.error || 'No se pudo restaurar el archivo.',
            confirmText: 'Cerrar',
            showCancel: false
          });
          throw new Error(data.error || 'restore_failed');
        }
        setStatus('Archivo restaurado.', 'success', false);
        loadFileList('history');
        refreshCount();
      } catch (err) {
        setStatus('No se pudo restaurar el archivo.', 'error', false);
      }
    };

    const refreshCount = async () => {
      if (!listUrl || !countEl) return;
      try {
        const response = await fetch(listUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        const data = await response.json();
        if (!data.ok) {
          setCount(null);
          setNewChip([]);
          return;
        }
        const files = data.files || [];
        setCount(files.length);
        setNewChip(files);
      } catch (err) {
        setCount(null);
        setNewChip([]);
      }
    };

    const downloadWithPicker = async (downloadUrl, fileName) => {
      if (!supportsDirectoryPicker) return false;
      setStatus('Selecciona la carpeta de destino.', null, false);
      try {
        const dirHandle = await window.showDirectoryPicker();
        if (!dirHandle) return true;
        setStatus('Descargando archivo...', null, true);
        const response = await fetch(downloadUrl, {
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
          credentials: 'same-origin'
        });
        if (!response.ok) {
          throw new Error('download_failed');
        }
        const blob = await response.blob();
        const safeName = fileName || 'archivo';
        const fileHandle = await dirHandle.getFileHandle(safeName, { create: true });
        const writable = await fileHandle.createWritable();
        await writable.write(blob);
        await writable.close();
        setStatus(`Archivo guardado: ${safeName}`, 'success', false);
      } catch (err) {
        if (err && err.name === 'AbortError') {
          setStatus('Descarga cancelada.', null, false);
          return true;
        }
        setStatus('No se pudo descargar el archivo.', 'error', false);
      }
      return true;
    };

    const deleteFile = async (fileId, fileName) => {
      if (!deleteUrlTemplate || !fileId) return;
      const confirmed = await showDialog({
        title: 'Eliminar archivo',
        message: `¿Eliminar "${fileName || 'archivo'}"?`,
        confirmText: 'Eliminar',
        cancelText: 'Cancelar',
        showCancel: true
      });
      if (!confirmed) return;
      const deleteUrl = deleteUrlTemplate.replace('__FILE_ID__', fileId);
      setStatus('Eliminando archivo...', null, true);
      try {
        const response = await fetch(deleteUrl, {
          method: 'DELETE',
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
          credentials: 'same-origin'
        });
        const data = await response.json();
        if (!data.ok) {
          await showDialog({
            title: 'No se pudo eliminar',
            message: data.error || 'No se pudo eliminar el archivo.',
            confirmText: 'Cerrar',
            showCancel: false
          });
          throw new Error(data.error || 'delete_failed');
        }
        setStatus('Archivo eliminado.', 'success', false);
        loadFileList();
        refreshCount();
      } catch (err) {
        setStatus('No se pudo eliminar el archivo.', 'error', false);
      }
    };

    if (dropzone && fileInput) {
      dropzone.addEventListener('click', () => fileInput.click());
      dropzone.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          fileInput.click();
        }
      });
      dropzone.addEventListener('dragover', (event) => {
        event.preventDefault();
        dropzone.classList.add('is-dragover');
      });
      dropzone.addEventListener('dragleave', () => {
        dropzone.classList.remove('is-dragover');
      });
      dropzone.addEventListener('drop', (event) => {
        event.preventDefault();
        dropzone.classList.remove('is-dragover');
        prepareFiles(event.dataTransfer.files);
      });
      fileInput.addEventListener('change', () => prepareFiles(fileInput.files));
    }

    if (listBtn) {
      listBtn.addEventListener('click', () => {
        // UX: al abrir el modal, quitamos el chip de "Nuevo" del contador (se va a revisar en el modal).
        setNewChip([]);
        toggleModal(listModal, true);
        loadFileList('active');
        if (listSearch) {
          listSearch.value = '';
        }
      });
    }

    if (listSearch) {
      listSearch.addEventListener('input', () => applySearchFilter());
    }

    async function closeListModal() {
      if (!listModal) return;
      toggleModal(listModal, false);

      if (currentListMode !== 'active') return;
      const hadNew = Array.isArray(lastActiveFiles)
        ? lastActiveFiles.some((file) => file && file.isNew && file.dbId)
        : false;
      if (!hadNew) return;
      if (isMarkingOnClose) return;
      isMarkingOnClose = true;
      try {
        const marked = await markFilesSeen(lastActiveFiles);
        await refreshCount();
        if (marked > 0 && typeof window.refreshUnreadCounts === 'function') {
          window.refreshUnreadCounts();
        }
      } finally {
        isMarkingOnClose = false;
      }
    }

    if (listClose && listModal) {
      listClose.addEventListener('click', () => closeListModal());
      listModal.addEventListener('click', (event) => {
        if (event.target === listModal) closeListModal();
      });
    }

    if (listRefresh) {
      listRefresh.addEventListener('click', () => loadFileList());
    }

    if (listHistoryBtn) {
      if (!(canHistory && historyUrl)) {
        listHistoryBtn.style.display = 'none';
      }
      listHistoryBtn.addEventListener('click', () => {
        loadFileList('history');
      });
    }

    if (listBackBtn) {
      listBackBtn.addEventListener('click', () => {
        loadFileList('active');
      });
    }

    if (listBody) {
      listBody.addEventListener('click', (event) => {
        const deleteBtn = event.target.closest('[data-drive-delete]');
        if (deleteBtn) {
          event.preventDefault();
          deleteFile(deleteBtn.dataset.fileId, deleteBtn.dataset.fileName);
          return;
        }

        const restoreBtn = event.target.closest('[data-drive-restore]');
        if (restoreBtn) {
          event.preventDefault();
          restoreFile(restoreBtn.dataset.fileId, restoreBtn.dataset.fileName);
          return;
        }

        const editBtn = event.target.closest('[data-drive-edit-desc]');
        if (editBtn) {
          event.preventDefault();
          openDescriptionModalForEdit(
            editBtn.dataset.fileId,
            editBtn.dataset.fileName,
            editBtn.dataset.currentDescription
          );
          return;
        }

        const downloadLink = event.target.closest('[data-drive-download]');
        if (downloadLink) {
          if (!supportsDirectoryPicker) {
            setStatus('Tu navegador no permite elegir carpeta. Se usara la descarga normal.', null, false);
            return;
          }
          event.preventDefault();
          downloadWithPicker(downloadLink.href, downloadLink.dataset.fileName);
        }
      });
    }

    if (descEnabled && descText) {
      descEnabled.addEventListener('change', () => {
        const enabled = Boolean(descEnabled.checked);
        descText.disabled = !enabled;
        if (enabled) {
          descText.focus();
        } else {
          descText.value = '';
        }
      });
    }

    const closeDescModal = () => {
      if (!descModal) return;
      toggleModal(descModal, false);
      pendingDescMode = null;
      pendingDescFileId = null;
      pendingDescFileName = null;
    };

    if (descClose) descClose.addEventListener('click', closeDescModal);
    if (descCancel) descCancel.addEventListener('click', () => {
      if (pendingDescMode === 'upload') {
        cancelConflicts();
      }
      closeDescModal();
    });
    if (descModal) {
      descModal.addEventListener('click', (event) => {
        if (event.target === descModal) {
          if (pendingDescMode === 'upload') {
            cancelConflicts();
          }
          closeDescModal();
        }
      });
    }

    if (descConfirm) {
      descConfirm.addEventListener('click', () => {
        const wants = descEnabled ? Boolean(descEnabled.checked) : false;
        const value = wants && descText ? descText.value.trim() : '';

        if (pendingDescMode === 'upload') {
          pendingUploadDescription = value;
          closeDescModal();
          uploadFiles();
          return;
        }

        if (pendingDescMode === 'edit' && pendingDescFileId) {
          const fileId = pendingDescFileId;
          closeDescModal();
          saveDescription(fileId, value);
          // refresca lista para reflejar el cambio
          loadFileList();
        }
      });
    }

    if (conflictClose && conflictModal) {
      conflictClose.addEventListener('click', () => {
        toggleModal(conflictModal, false);
        cancelConflicts();
      });
      conflictModal.addEventListener('click', (event) => {
        if (event.target === conflictModal) {
          toggleModal(conflictModal, false);
          cancelConflicts();
        }
      });
    }

    if (conflictConfirm) {
      conflictConfirm.addEventListener('click', () => {
        const resolutions = {};
        const rows = conflictBody.querySelectorAll('.drive-conflict-row');
        let hasError = false;
        rows.forEach((row) => {
          const fileName = row.dataset.fileName;
          const selected = row.querySelector('input[type="radio"]:checked');
          const action = selected ? selected.value : 'skip';
          if (action === 'rename') {
            const renameInput = row.querySelector('.drive-conflict-rename');
            const newName = renameInput ? renameInput.value.trim() : '';
            if (!newName) {
              hasError = true;
              renameInput.classList.add('is-error');
              return;
            }
            resolutions[fileName] = { action: 'rename', new_name: newName };
            return;
          }
          resolutions[fileName] = { action };
        });

        if (hasError) {
          setStatus('Completa los nuevos nombres antes de continuar.', 'error', false);
          return;
        }

        toggleModal(conflictModal, false);
        uploadFiles(resolutions);
      });
    }

    refreshCount();
  });
})();
