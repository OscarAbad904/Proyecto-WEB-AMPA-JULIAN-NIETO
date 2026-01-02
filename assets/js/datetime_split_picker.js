(function () {
  function pad2(n) {
    return String(n).padStart(2, '0');
  }

  function formatDateYMD(d) {
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  }

  function formatDateDMY(d) {
    return `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)}/${d.getFullYear()}`;
  }

  function formatTimeHM(d) {
    return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  }

  function parseYMD(ymd) {
    const [y, m, day] = (ymd || '').split('-').map(Number);
    if (!y || !m || !day) return null;
    return new Date(y, m - 1, day, 0, 0, 0, 0);
  }

  function parseDMY(dmy) {
    const [day, m, y] = (dmy || '').split('/').map(Number);
    if (!y || !m || !day) return null;
    return new Date(y, m - 1, day, 0, 0, 0, 0);
  }

  function parseDate(dateStr) {
    if ((dateStr || '').includes('/')) return parseDMY(dateStr);
    return parseYMD(dateStr);
  }

  function parseHM(hm) {
    const [h, m] = (hm || '').split(':').map(Number);
    if (Number.isNaN(h) || Number.isNaN(m)) return null;
    return { h, m };
  }

  function buildLocalDateTime(dateStr, hm) {
    const base = parseDate(dateStr);
    const t = parseHM(hm);
    if (!base || !t) return null;
    base.setHours(t.h, t.m, 0, 0);
    return base;
  }

  function safeAlert(msg) {
    if (window.ampaAlert) return window.ampaAlert(msg);
    return window.alert(msg);
  }

  function initSplitDateTimePicker(cfg) {
    const config = cfg || {};

    const nowStr = config.nowStr || '';
    const enforceStartAfterNowEnabled = config.enforceStartAfterNow !== false;

    const startAtHidden = document.getElementById(config.startAtId || 'startAt');
    const endAtHidden = document.getElementById(config.endAtId || 'endAt');

    const startDateInput = document.getElementById(config.startDateId || 'startDate');
    const startTimeInput = document.getElementById(config.startTimeId || 'startTime');
    const endTimeInput = document.getElementById(config.endTimeId || 'endTime');

    const startTimePopover = document.getElementById(config.startTimePopoverId || 'startTimePopover');
    const endTimePopover = document.getElementById(config.endTimePopoverId || 'endTimePopover');

    const formEl = config.formId ? document.getElementById(config.formId) : null;

    if (!startAtHidden || !endAtHidden || !startDateInput || !startTimeInput || !endTimeInput) {
      return {
        syncAll: function () {},
        setFromHidden: function () {},
        setValues: function () {},
        getValues: function () {
          return { startAt: startAtHidden?.value || '', endAt: endAtHidden?.value || '' };
        },
      };
    }

    let __syncInProgress = false;

    function closeTimePopovers(exceptPopover) {
      [startTimePopover, endTimePopover].forEach(function (pop) {
        if (!pop || pop === exceptPopover) return;
        pop.classList.remove('is-open');
        pop.setAttribute('aria-hidden', 'true');
      });
    }

    function dockLatestTimepickerModalInto(popoverEl) {
      if (!popoverEl) return false;
      const modals = document.querySelectorAll('.tp-ui-modal');
      if (!modals || !modals.length) return false;

      const modal = modals[modals.length - 1];
      if (!popoverEl.contains(modal)) {
        popoverEl.replaceChildren(modal);
      }

      popoverEl.classList.add('is-open');
      popoverEl.setAttribute('aria-hidden', 'false');
      return true;
    }

    function dockOnOpen(popoverEl) {
      if (!popoverEl) return;
      closeTimePopovers(popoverEl);

      let tries = 0;
      const tick = function () {
        tries += 1;
        if (dockLatestTimepickerModalInto(popoverEl) || tries > 12) return;
        requestAnimationFrame(tick);
      };

      requestAnimationFrame(tick);
    }

    function setHiddenFromVisible() {
      const startDT = buildLocalDateTime(startDateInput.value, startTimeInput.value);
      if (startDT) {
        startAtHidden.value = `${formatDateYMD(startDT)}T${formatTimeHM(startDT)}`;
      }

      // Fin usa SIEMPRE la misma fecha que Inicio.
      const endDT = buildLocalDateTime(startDateInput.value, endTimeInput.value);
      if (endDT) {
        endAtHidden.value = `${formatDateYMD(endDT)}T${formatTimeHM(endDT)}`;
      }

      if (typeof config.onChange === 'function') {
        config.onChange({ startAt: startAtHidden.value, endAt: endAtHidden.value });
      }
    }

    function validateEndTime() {
      const startDT = buildLocalDateTime(startDateInput.value, startTimeInput.value);
      if (!startDT) return;

      const minEnd = new Date(startDT.getTime() + 60 * 1000);
      const endDT = buildLocalDateTime(startDateInput.value, endTimeInput.value);

      if (!endDT || endDT < minEnd) {
        const suggestedEnd = new Date(startDT.getTime() + 60 * 60 * 1000);
        endTimeInput.value = formatTimeHM(suggestedEnd);
      }
    }

    function enforceStartAfterNow() {
      if (!nowStr) return;

      const now = new Date(nowStr);
      const startDT = buildLocalDateTime(startDateInput.value, startTimeInput.value);
      if (!startDT) return;

      if (startDT <= now) {
        const fixed = new Date(now.getTime() + 60 * 1000);
        startDateInput.value = formatDateYMD(fixed);
        startTimeInput.value = formatTimeHM(fixed);

        if (window.__startDatePicker) {
          const current = window.__startDatePicker.get('select');
          const needs =
            !current ||
            current.year !== fixed.getFullYear() ||
            current.month !== fixed.getMonth() ||
            current.date !== fixed.getDate();
          if (needs) {
            window.__startDatePicker.set(
              'select',
              [fixed.getFullYear(), fixed.getMonth(), fixed.getDate()],
              { muted: true }
            );
          }
        }
        if (window.__startTimePickerInstance) {
          window.__startTimePickerInstance.setValue(formatTimeHM(fixed));
        }
      }
    }

    function syncAll() {
      if (__syncInProgress) return;
      __syncInProgress = true;
      try {
        if (enforceStartAfterNowEnabled) {
          enforceStartAfterNow();
        }
        validateEndTime();
        setHiddenFromVisible();
      } finally {
        __syncInProgress = false;
      }
    }

    function setFromHidden() {
      const initialStart = startAtHidden.value || '';
      const initialEnd = endAtHidden.value || '';

      if (initialStart.includes('T')) {
        const [d, t] = initialStart.split('T');
        const dateObj = parseYMD(d);
        if (dateObj) {
          startDateInput.value = formatDateDMY(dateObj);
        }
        startTimeInput.value = t;
      }

      if (initialEnd.includes('T')) {
        const [, t] = initialEnd.split('T');
        endTimeInput.value = t;
      }

      // Si no hay valores, preseleccionar ahora+1min y fin=+1hora
      if ((!startDateInput.value || !startTimeInput.value) && nowStr) {
        const base = new Date(nowStr);
        base.setMinutes(base.getMinutes() + 1);
        startDateInput.value = formatDateDMY(base);
        startTimeInput.value = formatTimeHM(base);
      }

      syncAll();

      // Sincronizar pickers
      const startDT = buildLocalDateTime(startDateInput.value, startTimeInput.value);
      if (startDT && window.__startDatePicker) {
        window.__startDatePicker.set(
          'select',
          [startDT.getFullYear(), startDT.getMonth(), startDT.getDate()],
          { muted: true }
        );
      }

      if (window.__startTimePickerInstance && startTimeInput.value) {
        window.__startTimePickerInstance.setValue(startTimeInput.value);
      }
      if (window.__endTimePickerInstance && endTimeInput.value) {
        window.__endTimePickerInstance.setValue(endTimeInput.value);
      }
    }

    // Init: pickers
    if (window.jQuery && window.jQuery.fn && window.jQuery.fn.pickadate) {
      window.jQuery(function () {
        const now = nowStr ? new Date(nowStr) : new Date();
        const minDate = new Date(now.getFullYear(), now.getMonth(), now.getDate());

        window.jQuery('#' + (config.startDateId || 'startDate')).pickadate({
          format: 'dd/mm/yyyy',
          formatSubmit: 'yyyy-mm-dd',
          hiddenName: true,
          editable: true,
          min: minDate,
          monthsFull: [
            'Enero',
            'Febrero',
            'Marzo',
            'Abril',
            'Mayo',
            'Junio',
            'Julio',
            'Agosto',
            'Septiembre',
            'Octubre',
            'Noviembre',
            'Diciembre',
          ],
          monthsShort: ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'],
          weekdaysFull: ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'],
          weekdaysShort: ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'],
          today: 'Hoy',
          clear: 'Limpiar',
          close: 'Cerrar',
          firstDay: 1,
          onSet: function () {
            syncAll();
          },
        });

        window.__startDatePicker = window.jQuery('#' + (config.startDateId || 'startDate')).pickadate('picker');

        const TimepickerUI = window.TimepickerUI;
        if (TimepickerUI) {
          window.__startTimePickerInstance = new TimepickerUI(startTimeInput, {
            clock: {
              type: '24h',
              incrementHours: 1,
              incrementMinutes: 1,
              autoSwitchToMinutes: true,
            },
            ui: {
              theme: 'm2',
              animation: true,
              backdrop: false,
              editable: false,
            },
            labels: {
              time: 'Elige una hora',
              ok: 'Aceptar',
              cancel: 'Cancelar',
              mobileHour: 'Hora',
              mobileMinute: 'Minutos',
            },
            callbacks: {
              onConfirm: function () {
                syncAll();
              },
              onUpdate: function () {
                setHiddenFromVisible();
              },
            },
          });
          window.__startTimePickerInstance.create();

          window.__endTimePickerInstance = new TimepickerUI(endTimeInput, {
            clock: {
              type: '24h',
              incrementHours: 1,
              incrementMinutes: 1,
              autoSwitchToMinutes: true,
            },
            ui: {
              theme: 'm2',
              animation: true,
              backdrop: false,
              editable: false,
            },
            labels: {
              time: 'Elige una hora',
              ok: 'Aceptar',
              cancel: 'Cancelar',
              mobileHour: 'Hora',
              mobileMinute: 'Minutos',
            },
            callbacks: {
              onConfirm: function () {
                syncAll();
              },
              onUpdate: function () {
                setHiddenFromVisible();
              },
            },
          });
          window.__endTimePickerInstance.create();
        }

        startTimeInput?.addEventListener('click', function () {
          dockOnOpen(startTimePopover);
        });
        startTimeInput?.addEventListener('focus', function () {
          dockOnOpen(startTimePopover);
        });
        endTimeInput?.addEventListener('click', function () {
          dockOnOpen(endTimePopover);
        });
        endTimeInput?.addEventListener('focus', function () {
          dockOnOpen(endTimePopover);
        });

        document.addEventListener('mousedown', function (e) {
          const t = e.target;
          const insideTimepickerModal = !!(t && t.closest && t.closest('.tp-ui-modal'));
          const insideStart =
            (startTimePopover && startTimePopover.contains(t)) ||
            (startTimeInput && startTimeInput.contains(t));
          const insideEnd =
            (endTimePopover && endTimePopover.contains(t)) ||
            (endTimeInput && endTimeInput.contains(t));
          if (insideStart || insideEnd || insideTimepickerModal) return;
          closeTimePopovers(null);
        });

        setFromHidden();
      });
    } else {
      // Fallback: al menos setear desde hidden y sincronizar a mano
      setFromHidden();
    }

    startDateInput?.addEventListener('change', syncAll);
    startTimeInput?.addEventListener('change', syncAll);
    endTimeInput?.addEventListener('change', function () {
      setHiddenFromVisible();
    });

    if (formEl && nowStr) {
      formEl.addEventListener('submit', function (e) {
        // Asegurar coherencia antes de validar/submit.
        if (enforceStartAfterNowEnabled) {
          enforceStartAfterNow();
        }
        validateEndTime();
        setHiddenFromVisible();

        const startVal = startAtHidden.value;
        const endVal = endAtHidden.value;
        if (!startVal || !endVal) return;

        const startDT = new Date(startVal);
        const endDT = new Date(endVal);
        const now = new Date(nowStr);

        if (enforceStartAfterNowEnabled && startDT <= now) {
          e.preventDefault();
          document.getElementById('pageLoader')?.classList.remove('active');
          safeAlert('La fecha de inicio debe ser posterior a la fecha y hora actual');
          return false;
        }

        if (endDT <= startDT) {
          e.preventDefault();
          document.getElementById('pageLoader')?.classList.remove('active');
          safeAlert('La fecha de fin debe ser posterior a la fecha de inicio');
          return false;
        }

        return true;
      });
    }

    return {
      syncAll: syncAll,
      setFromHidden: setFromHidden,
      setValues: function (values) {
        if (values?.startAt != null) startAtHidden.value = values.startAt;
        if (values?.endAt != null) endAtHidden.value = values.endAt;
        setFromHidden();
      },
      getValues: function () {
        return { startAt: startAtHidden.value, endAt: endAtHidden.value };
      },
    };
  }

  window.initSplitDateTimePicker = initSplitDateTimePicker;
})();
