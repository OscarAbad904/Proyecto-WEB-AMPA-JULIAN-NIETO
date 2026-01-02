/**
 * Calendario AMPA - JavaScript
 * AMPA Julián Nieto Tapia
 * 
 * Maneja la conexión con la API del calendario,
 * renderizado de vistas y navegación.
 */

// Estado global del calendario
const CalendarState = {
  currentDate: new Date(),
  currentView: 'month', // 'month' | 'list'
  events: [],
  isLoading: false,
  error: null,
  cacheExpiry: 60000, // 1 minuto de cache en cliente
  lastFetch: 0,
  showAllMeetings: false,
  canToggleMeetings: false,
  lastFetchKey: '',
};

// Nombres de meses y días en español
const MONTHS_ES = [
  'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
  'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'
];

const DAYS_ES = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'];
const DAYS_SHORT_ES = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'];

// Inicialización
document.addEventListener('DOMContentLoaded', () => {
  initCalendar();
});

function isPastEvent(event) {
  if (!event) return false;
  const endRaw = event.fin || event.inicio;
  const end = new Date(endRaw);
  if (Number.isNaN(end.getTime())) return false;
  return end.getTime() < Date.now();
}

async function markSeenEventId(eventId) {
  if (!eventId || typeof eventId !== 'string' || !eventId.startsWith('event-')) return;
  const raw = eventId.slice('event-'.length);
  const id = Number.parseInt(raw, 10);
  if (!Number.isFinite(id) || id <= 0) return;
  try {
    const res = await fetch('/api/me/seen', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ item_type: 'event', item_id: id }),
    });
    if (!res.ok) return;
    const ev = CalendarState.events.find(e => e.id === eventId);
    if (ev) ev.is_new = false;
    renderUpcomingEvents();
    if (typeof window.refreshUnreadCounts === 'function') {
      window.refreshUnreadCounts();
    }
  } catch (_) {
    // Silencioso.
  }
}

/**
 * Inicializa el calendario
 */
function initCalendar() {
  // Detectar si es móvil para cambiar vista por defecto
  if (window.innerWidth <= 768) {
    CalendarState.currentView = 'list';
    updateViewButtons();
  }
  
  // Cargar eventos y renderizar
  loadCalendarEvents();
  
  // Configurar atajos de teclado
  document.addEventListener('keydown', handleKeyboard);
}

/**
 * Carga eventos desde la API del backend
 */
async function loadCalendarEvents() {
  if (CalendarState.isLoading) return;
  
  const fetchKey = CalendarState.showAllMeetings ? 'all_meetings' : 'my_meetings';

  // Verificar cache del cliente
  const now = Date.now();
  if (
    CalendarState.events.length > 0 &&
    CalendarState.lastFetchKey === fetchKey &&
    (now - CalendarState.lastFetch) < CalendarState.cacheExpiry
  ) {
    renderCalendar();
    return;
  }
  
  CalendarState.isLoading = true;
  showLoading(true);
  
  // Calcular rango de fechas (6 meses hacia adelante y 1 mes hacia atrás)
  const startDate = new Date();
  startDate.setMonth(startDate.getMonth() - 1);
  startDate.setDate(1);
  
  const endDate = new Date();
  endDate.setMonth(endDate.getMonth() + 6);
  
  const params = new URLSearchParams({
    rango_inicial: formatDateISO(startDate),
    rango_final: formatDateISO(endDate),
    limite: '100'
  });

  if (CalendarState.showAllMeetings) {
    params.set('todas_reuniones', '1');
  }
  
  try {
    const response = await fetch(`/api/calendario/mis-eventos?${params}`);
    const data = await response.json();
    
    if (data.ok) {
      CalendarState.events = data.eventos || [];
      CalendarState.lastFetch = now;
      CalendarState.lastFetchKey = fetchKey;
      CalendarState.error = null;

      CalendarState.canToggleMeetings = Boolean(data.can_toggle_reuniones);
      CalendarState.showAllMeetings = Boolean(data.mostrando_todas_reuniones);
      updateMeetingsToggleButton();
      
      renderCalendar();
      renderUpcomingEvents();
      
      // Mostrar indicador si los datos vienen de cache del servidor
      if (data.cached) {
        // noop: se muestra badge de cache sin log de depuracion
      }
    } else {
      throw new Error(data.error || 'Error al cargar eventos');
    }
  } catch (error) {
    console.error('Error cargando eventos:', error);
    CalendarState.error = error.message;
    showError(error.message);
  } finally {
    CalendarState.isLoading = false;
    showLoading(false);
  }
}

function updateMeetingsToggleButton() {
  const btn = document.getElementById('btn-toggle-meetings-scope');
  if (!btn) return;
  if (!CalendarState.canToggleMeetings) {
    btn.hidden = true;
    return;
  }
  btn.hidden = false;
  btn.textContent = CalendarState.showAllMeetings ? 'Ver mis reuniones' : 'Ver todas las reuniones';
}

function toggleMeetingsScope() {
  if (!CalendarState.canToggleMeetings) return;
  CalendarState.showAllMeetings = !CalendarState.showAllMeetings;
  CalendarState.lastFetch = 0;
  CalendarState.lastFetchKey = '';
  CalendarState.events = [];
  updateMeetingsToggleButton();
  loadCalendarEvents();
}

/**
 * Renderiza el calendario según la vista actual
 */
function renderCalendar() {
  updateMonthLabel();
  
  if (CalendarState.currentView === 'month') {
    renderMonthView();
  } else {
    renderListView();
  }
  
  // Ocultar estados de loading/error
  hideAllStatus();
  
  // Mostrar mensaje vacío si no hay eventos
  if (CalendarState.events.length === 0) {
    showEmpty();
  }
}

/**
 * Renderiza la vista mensual (grid)
 */
function renderMonthView() {
  const grid = document.getElementById('calendar-days-grid');
  if (!grid) return;
  
  const year = CalendarState.currentDate.getFullYear();
  const month = CalendarState.currentDate.getMonth();
  
  // Primer día del mes
  const firstDay = new Date(year, month, 1);
  // Último día del mes
  const lastDay = new Date(year, month + 1, 0);
  
  // Día de la semana del primer día (0=Dom, ajustamos para que Lunes=0)
  let startDayOfWeek = firstDay.getDay() - 1;
  if (startDayOfWeek < 0) startDayOfWeek = 6;
  
  // Días del mes anterior para rellenar
  const prevMonthLastDay = new Date(year, month, 0).getDate();
  
  let html = '';
  let dayCount = 1;
  let nextMonthDay = 1;
  
  // Calcular número de semanas necesarias
  const totalDays = startDayOfWeek + lastDay.getDate();
  const weeksNeeded = Math.ceil(totalDays / 7);
  
  for (let week = 0; week < weeksNeeded; week++) {
    for (let dayOfWeek = 0; dayOfWeek < 7; dayOfWeek++) {
      const cellIndex = week * 7 + dayOfWeek;
      let dayNumber, dateObj, isOtherMonth = false, isWeekend = false;
      
      if (cellIndex < startDayOfWeek) {
        // Días del mes anterior
        dayNumber = prevMonthLastDay - startDayOfWeek + cellIndex + 1;
        dateObj = new Date(year, month - 1, dayNumber);
        isOtherMonth = true;
      } else if (dayCount > lastDay.getDate()) {
        // Días del mes siguiente
        dayNumber = nextMonthDay++;
        dateObj = new Date(year, month + 1, dayNumber);
        isOtherMonth = true;
      } else {
        // Días del mes actual
        dayNumber = dayCount++;
        dateObj = new Date(year, month, dayNumber);
      }
      
      // Verificar si es fin de semana (Sáb=5, Dom=6 en nuestro sistema)
      isWeekend = (dayOfWeek === 5 || dayOfWeek === 6);
      
      // Verificar si es hoy
      const today = new Date();
      const isToday = dateObj.getDate() === today.getDate() &&
                      dateObj.getMonth() === today.getMonth() &&
                      dateObj.getFullYear() === today.getFullYear();
      
      // Obtener eventos de este día
      const dayEvents = getEventsForDate(dateObj);
      
      // Construir clases CSS
      const classes = ['calendar-day'];
      if (isOtherMonth) classes.push('other-month');
      if (isToday) classes.push('today');
      if (isWeekend) classes.push('weekend');
      if (dayEvents.length > 0) classes.push('has-events');
      
      // Renderizar eventos del día (máximo 3)
      let eventsHtml = '';
      const maxVisible = 3;
      dayEvents.slice(0, maxVisible).forEach(event => {
        const eventType = categorizeEvent(event);
        const pastClass = isPastEvent(event) ? 'is-past' : '';
        let displayTitle = event.titulo;
        
        // Mejorar título para reuniones de comisión/proyecto
        if (event.es_comision) {
          if (event.es_proyecto && event.project_name) {
            displayTitle = `Proyecto: ${event.project_name}`;
          } else if (event.commission_name) {
            displayTitle = `Comisión: ${event.commission_name}`;
          }
        }
        
        eventsHtml += `
          <div class="day-event event-type-${eventType} ${pastClass}" 
               onclick="openEventModal('${event.id}')" 
               title="${escapeHtml(displayTitle)}">
            ${escapeHtml(displayTitle)}
          </div>
        `;
      });
      
      if (dayEvents.length > maxVisible) {
        eventsHtml += `<div class="day-more">+${dayEvents.length - maxVisible} más</div>`;
      }
      
      html += `
        <div class="${classes.join(' ')}" data-date="${formatDateISO(dateObj)}">
          <div class="day-number">${dayNumber}</div>
          <div class="day-events">${eventsHtml}</div>
        </div>
      `;
    }
  }
  
  grid.innerHTML = html;
}

/**
 * Renderiza la vista de lista
 */
function renderListView() {
  const list = document.getElementById('events-list');
  if (!list) return;

  const allEvents = CalendarState.events || [];

  if (allEvents.length === 0) {
    list.innerHTML = `
      <div class="calendar-empty-list">
        <p>No hay eventos programados</p>
      </div>
    `;
    return;
  }
  
  // Agrupar eventos por fecha
  const groupedEvents = {};
  allEvents.forEach(event => {
    const dateKey = formatDateISO(new Date(event.inicio));
    if (!groupedEvents[dateKey]) {
      groupedEvents[dateKey] = [];
    }
    groupedEvents[dateKey].push(event);
  });
  
  // Renderizar grupos
  let html = '';
  Object.keys(groupedEvents).sort().forEach(dateKey => {
    const events = groupedEvents[dateKey];
    const date = new Date(dateKey);
    const formattedDate = formatDateLong(date);
    
    html += `<div class="event-list-group">`;
    html += `<div class="event-list-date">${formattedDate}</div>`;
    
    events.forEach(event => {
      const eventType = categorizeEvent(event);
      const timeStr = formatEventTime(event);
      const pastClass = isPastEvent(event) ? 'is-past' : '';
      
      html += `
        <div class="event-list-item ${pastClass}" onclick="openEventModal('${event.id}')">
          <div class="event-list-indicator event-type-${eventType}"></div>
          <div class="event-list-time">
            ${event.todo_el_dia ? '<span>Todo el día</span>' : `<span>${timeStr.start}</span>${timeStr.end ? `<span class="time-end">– ${timeStr.end}</span>` : ''}`}
          </div>
          <div class="event-list-content">
            <h4 class="event-list-title"><span class="event-title-text">${escapeHtml(event.titulo)}</span>${event.is_new ? ' <span class="chip chip--new">Nuevo</span>' : ''}</h4>
            ${event.es_comision ? `<span class="badge">Comisión</span>` : ''}
            ${event.ubicacion ? `
              <div class="event-list-location">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
                  <circle cx="12" cy="10" r="3"></circle>
                </svg>
                ${escapeHtml(event.ubicacion)}
              </div>
            ` : ''}
          </div>
        </div>
      `;
    });
    
    html += `</div>`;
  });
  
  list.innerHTML = html;
}

/**
 * Renderiza la lista de próximos eventos en el sidebar
 */
function renderUpcomingEvents() {
  const container = document.getElementById('upcoming-events');
  if (!container) return;
  
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  
  // Obtener próximos 5 eventos
  const upcoming = CalendarState.events
    .filter(event => new Date(event.inicio) >= today)
    .slice(0, 5);
  
  if (upcoming.length === 0) {
    container.innerHTML = `
      <div class="upcoming-empty">
        No hay eventos próximos
      </div>
    `;
    return;
  }
  
  let html = '';
  upcoming.forEach(event => {
    const date = new Date(event.inicio);
    const day = date.getDate();
    const month = MONTHS_ES[date.getMonth()].substring(0, 3).toUpperCase();
    const time = event.todo_el_dia ? 'Todo el día' : formatTime(date);
    const eventType = categorizeEvent(event);
    
    html += `
      <div class="upcoming-event upcoming-event-${eventType}" onclick="openEventModal('${event.id}')">
        <div class="upcoming-event-date">
          <div class="upcoming-event-day">${day}</div>
          <div class="upcoming-event-month">${month}</div>
        </div>
        <div class="upcoming-event-info">
          <h4 class="upcoming-event-title"><span class="event-title-text">${escapeHtml(event.titulo)}</span>${event.is_new ? ' <span class="chip chip--new">Nuevo</span>' : ''}</h4>
          <div class="upcoming-event-time">${time}</div>
        </div>
      </div>
    `;
  });
  
  container.innerHTML = html;
}

/**
 * Cambia entre vista mensual y lista
 */
function switchView(view) {
  CalendarState.currentView = view;
  updateViewButtons();
  
  const monthView = document.getElementById('month-view');
  const listView = document.getElementById('list-view');
  
  if (view === 'month') {
    monthView?.classList.remove('hidden');
    listView?.classList.add('hidden');
    renderMonthView();
  } else {
    monthView?.classList.add('hidden');
    listView?.classList.remove('hidden');
    renderListView();
  }
}

/**
 * Actualiza el estado visual de los botones de vista
 */
function updateViewButtons() {
  const btnMonth = document.getElementById('btn-view-month');
  const btnList = document.getElementById('btn-view-list');
  
  btnMonth?.classList.toggle('active', CalendarState.currentView === 'month');
  btnList?.classList.toggle('active', CalendarState.currentView === 'list');
}

/**
 * Navega al mes anterior o siguiente
 */
function navigateMonth(direction) {
  CalendarState.currentDate.setMonth(CalendarState.currentDate.getMonth() + direction);
  renderCalendar();
}

/**
 * Va al mes actual
 */
function goToToday() {
  CalendarState.currentDate = new Date();
  renderCalendar();
}

/**
 * Actualiza la etiqueta del mes actual
 */
function updateMonthLabel() {
  const label = document.getElementById('current-month-label');
  if (label) {
    const month = MONTHS_ES[CalendarState.currentDate.getMonth()];
    const year = CalendarState.currentDate.getFullYear();
    label.textContent = `${month} ${year}`;
  }
}

/**
 * Abre el modal con detalles de un evento
 */
function openEventModal(eventId) {
  const event = CalendarState.events.find(e => e.id === eventId);
  if (!event) return;
  
  const modal = document.getElementById('event-modal');
  if (!modal) return;
  
  // Rellenar datos del modal
  const eventType = categorizeEvent(event);
  
  // Determinar el tipo y título según sea reunión de comisión o proyecto
  let typeLabel = getEventTypeLabel(eventType);
  let modalTitle = event.titulo;
  
  if (event.es_comision) {
    if (event.es_proyecto && event.project_name) {
      typeLabel = 'Reunión de Proyecto';
      modalTitle = `${event.titulo} - ${event.project_name}`;
    } else if (event.commission_name) {
      typeLabel = `Reunión de Comisión ${event.commission_name}`;
      modalTitle = event.titulo;
    } else {
      typeLabel = 'Reunión de Comisión';
    }
  }
  
  document.getElementById('modal-event-type').textContent = typeLabel;
  document.getElementById('modal-event-title').textContent = modalTitle;
  
  // Fecha
  const startDate = new Date(event.inicio);
  document.getElementById('modal-event-date').textContent = formatDateLong(startDate);
  
  // Hora
  const timeContainer = document.getElementById('modal-time-container');
  if (event.todo_el_dia) {
    timeContainer.style.display = 'none';
  } else {
    timeContainer.style.display = 'flex';
    const timeStr = formatEventTime(event);
    document.getElementById('modal-event-time').textContent = 
      timeStr.end ? `${timeStr.start} – ${timeStr.end}` : timeStr.start;
  }
  
  // Ubicación
  const locationContainer = document.getElementById('modal-location-container');
  if (event.ubicacion) {
    locationContainer.style.display = 'flex';
    document.getElementById('modal-event-location').textContent = event.ubicacion;
  } else {
    locationContainer.style.display = 'none';
  }
  
  // Descripción
  const description = document.getElementById('modal-event-description');
  description.textContent = event.descripcion || '';
  
  // Mostrar modal
  modal.classList.remove('hidden');
  document.body.style.overflow = 'hidden';

  // Marcar como visto SOLO al abrir detalle (modal) y solo para eventos (no comisiones)
  if (!event.es_comision) {
    markSeenEventId(eventId);
  }
  
  // Focus trap para accesibilidad
  modal.querySelector('.event-modal-close')?.focus();
}

/**
 * Cierra el modal de evento
 */
function closeEventModal() {
  const modal = document.getElementById('event-modal');
  if (modal) {
    modal.classList.add('hidden');
    document.body.style.overflow = '';
  }
}

/**
 * Maneja atajos de teclado
 */
function handleKeyboard(event) {
  // Cerrar modal con Escape
  if (event.key === 'Escape') {
    closeEventModal();
  }
  
  // Navegación con flechas cuando no hay modal abierto
  const modal = document.getElementById('event-modal');
  if (modal && !modal.classList.contains('hidden')) return;
  
  if (event.key === 'ArrowLeft') {
    navigateMonth(-1);
  } else if (event.key === 'ArrowRight') {
    navigateMonth(1);
  }
}

// ==================== FUNCIONES AUXILIARES ====================

/**
 * Obtiene eventos para una fecha específica
 */
function getEventsForDate(date) {
  const dateStr = formatDateISO(date);
  return CalendarState.events.filter(event => {
    const eventDate = formatDateISO(new Date(event.inicio));
    return eventDate === dateStr;
  });
}

/**
 * Categoriza un evento según su título/descripción
 */
function categorizeEvent(event) {
  const title = (event.titulo || '').toLowerCase();
  const desc = (event.descripcion || '').toLowerCase();
  const text = title + ' ' + desc;
  const category = (event.categoria || event.category || '').toLowerCase();

  // Primero verificar si es reunión de proyecto
  if (event.es_comision && event.es_proyecto) {
    return 'project';
  }

  if (category.includes('reunion')) {
    return 'meeting';
  }
  if (category.includes('taller') || category.includes('actividad')) {
    return 'activity';
  }
  if (category.includes('festivo') || category.includes('vacacion')) {
    return 'holiday';
  }

  if (event.es_comision) {
    return 'meeting';
  }
  
  if (text.includes('reunión') || text.includes('reunion') || text.includes('asamblea') || text.includes('junta')) {
    return 'meeting';
  }
  if (text.includes('taller') || text.includes('actividad') || text.includes('excursión') || text.includes('excursion')) {
    return 'activity';
  }
  if (text.includes('festivo') || text.includes('vacaciones') || text.includes('fiesta') || text.includes('navidad')) {
    return 'holiday';
  }
  return 'event';
}

/**
 * Obtiene la etiqueta de tipo de evento
 */
function getEventTypeLabel(type) {
  const labels = {
    'event': 'Evento',
    'meeting': 'Reunión de Comisión General',
    'project': 'Reunión de Proyecto',
    'activity': 'Actividad',
    'holiday': 'Festivo'
  };
  return labels[type] || 'Evento';
}

/**
 * Formatea una fecha a formato ISO (YYYY-MM-DD)
 */
function formatDateISO(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/**
 * Formatea una fecha en formato largo español
 */
function formatDateLong(date) {
  const dayName = DAYS_ES[date.getDay()];
  const day = date.getDate();
  const month = MONTHS_ES[date.getMonth()];
  const year = date.getFullYear();
  return `${dayName}, ${day} de ${month} de ${year}`;
}

/**
 * Formatea una hora (HH:MM)
 */
function formatTime(date) {
  return date.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
}

/**
 * Formatea el rango de tiempo de un evento
 */
function formatEventTime(event) {
  const start = new Date(event.inicio);
  const end = event.fin ? new Date(event.fin) : null;
  
  return {
    start: formatTime(start),
    end: end && end.getTime() !== start.getTime() ? formatTime(end) : null
  };
}

/**
 * Escapa caracteres HTML
 */
function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ==================== FUNCIONES DE UI ====================

function showLoading(show) {
  const status = document.getElementById('calendar-status');
  const loading = document.getElementById('calendar-loading');
  const main = document.querySelector('.calendar-main');
  
  if (show) {
    status?.classList.remove('hidden');
    loading?.classList.remove('hidden');
    main?.classList.add('hidden');
  } else {
    loading?.classList.add('hidden');
  }
}

function showError(message) {
  const status = document.getElementById('calendar-status');
  const error = document.getElementById('calendar-error');
  const errorMsg = document.getElementById('error-message');
  const main = document.querySelector('.calendar-main');
  
  status?.classList.remove('hidden');
  error?.classList.remove('hidden');
  if (errorMsg) errorMsg.textContent = message;
  main?.classList.add('hidden');
}

function showEmpty() {
  const status = document.getElementById('calendar-status');
  const empty = document.getElementById('calendar-empty');
  
  status?.classList.remove('hidden');
  empty?.classList.remove('hidden');
}

function hideAllStatus() {
  const status = document.getElementById('calendar-status');
  const loading = document.getElementById('calendar-loading');
  const error = document.getElementById('calendar-error');
  const empty = document.getElementById('calendar-empty');
  const main = document.querySelector('.calendar-main');
  
  status?.classList.add('hidden');
  loading?.classList.add('hidden');
  error?.classList.add('hidden');
  empty?.classList.add('hidden');
  main?.classList.remove('hidden');
}

// Exportar funciones para uso global
window.loadCalendarEvents = loadCalendarEvents;
window.switchView = switchView;
window.navigateMonth = navigateMonth;
window.goToToday = goToToday;
window.openEventModal = openEventModal;
window.closeEventModal = closeEventModal;
