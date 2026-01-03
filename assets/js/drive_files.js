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
    const canDelete = widget.dataset.driveCanDelete === 'true';
    const dropzone = widget.querySelector('[data-drive-dropzone]');
    const fileInput = widget.querySelector('[data-drive-input]');
    const statusEl = widget.querySelector('[data-drive-status]');
    const listBtn = widget.querySelector('[data-drive-open-list]');
    const listModal = widget.querySelector('[data-drive-list-modal]');
    const listBody = widget.querySelector('[data-drive-list-body]');
    const listClose = widget.querySelector('[data-drive-list-close]');
    const listRefresh = widget.querySelector('[data-drive-list-refresh]');
    const conflictModal = widget.querySelector('[data-drive-conflict-modal]');
    const conflictBody = widget.querySelector('[data-drive-conflict-body]');
    const conflictClose = widget.querySelector('[data-drive-conflict-close]');
    const conflictConfirm = widget.querySelector('[data-drive-conflict-confirm]');
    const scopeLabel = widget.dataset.driveLabel || 'comision';
    const supportsDirectoryPicker = typeof window.showDirectoryPicker === 'function';
    const countEl = widget.querySelector('[data-drive-count]');

    let pendingFiles = [];

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

    const toggleModal = (modal, show) => {
      if (!modal) return;
      modal.classList.toggle('open', show);
      modal.setAttribute('aria-hidden', show ? 'false' : 'true');
    };

    const cancelConflicts = () => {
      pendingFiles = [];
      if (fileInput) fileInput.value = '';
      setBusy(false);
      setStatus('Subida cancelada.', null, false);
    };

    const closeModalOnEscape = (event) => {
      if (event.key !== 'Escape') return;
      if (listModal && listModal.classList.contains('open')) toggleModal(listModal, false);
      if (conflictModal && conflictModal.classList.contains('open')) {
        toggleModal(conflictModal, false);
        cancelConflicts();
      }
    };

    document.addEventListener('keydown', closeModalOnEscape);

    const prepareFiles = (files) => {
      if (!files || !files.length) return;
      pendingFiles = Array.from(files);
      uploadFiles();
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
      optionOverwrite.innerHTML = `<input type="radio" name="${groupName}" value="overwrite"> Sobrescribir`;

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
        pendingFiles = [];
        if (fileInput) fileInput.value = '';
        if (listModal && listModal.classList.contains('open')) loadFileList();
        refreshCount();
      } catch (err) {
        setBusy(false);
        setStatus('Error inesperado subiendo archivos.', 'error', false);
      }
    };

    const loadFileList = async () => {
      if (!listUrl) return;
      if (!listBody) return;
      listBody.innerHTML = '';
      const row = document.createElement('tr');
      row.innerHTML = `<td colspan="4" class="drive-files-empty">Cargando archivos...</td>`;
      listBody.appendChild(row);

      try {
        const response = await fetch(listUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        const data = await response.json();
        if (!data.ok) {
          listBody.innerHTML = `<tr><td colspan="4" class="drive-files-empty">${data.error || 'No se pudo cargar la lista.'}</td></tr>`;
          return;
        }

        const files = data.files || [];
        setCount(files.length);
        if (!files.length) {
          listBody.innerHTML = `<tr><td colspan="4" class="drive-files-empty">No hay archivos en la carpeta.</td></tr>`;
          return;
        }

        listBody.innerHTML = '';
        files.forEach((file) => {
          const downloadUrl = downloadUrlTemplate
            ? downloadUrlTemplate.replace('__FILE_ID__', file.id)
            : '#';
          const rowEl = document.createElement('tr');
          const nameCell = document.createElement('td');
          const nameText = document.createElement('span');
          nameText.className = 'drive-files-name';
          nameText.textContent = file.name || '-';
          nameCell.appendChild(nameText);

          const modifiedCell = document.createElement('td');
          modifiedCell.textContent = formatModifiedDate(file.modifiedTime, file.createdTime);

          const createdCell = document.createElement('td');
          createdCell.textContent = formatDate(file.createdTime);

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

          if (canDelete && deleteUrlTemplate) {
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

          actionCell.appendChild(actionWrap);

          rowEl.append(nameCell, modifiedCell, createdCell, actionCell);
          listBody.appendChild(rowEl);
        });
      } catch (err) {
        setCount(null);
        listBody.innerHTML = `<tr><td colspan="4" class="drive-files-empty">Error cargando archivos.</td></tr>`;
      }
    };

    const refreshCount = async () => {
      if (!listUrl || !countEl) return;
      try {
        const response = await fetch(listUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        const data = await response.json();
        if (!data.ok) {
          setCount(null);
          return;
        }
        setCount((data.files || []).length);
      } catch (err) {
        setCount(null);
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
      const confirmed = window.confirm(`Eliminar "${fileName || 'archivo'}"?`);
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
        toggleModal(listModal, true);
        loadFileList();
      });
    }

    if (listClose && listModal) {
      listClose.addEventListener('click', () => toggleModal(listModal, false));
      listModal.addEventListener('click', (event) => {
        if (event.target === listModal) toggleModal(listModal, false);
      });
    }

    if (listRefresh) {
      listRefresh.addEventListener('click', loadFileList);
    }

    if (listBody) {
      listBody.addEventListener('click', (event) => {
        const deleteBtn = event.target.closest('[data-drive-delete]');
        if (deleteBtn) {
          event.preventDefault();
          deleteFile(deleteBtn.dataset.fileId, deleteBtn.dataset.fileName);
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
