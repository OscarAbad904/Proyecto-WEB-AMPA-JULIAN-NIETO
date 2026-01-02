/**
 * Mini-calendario de eventos para la página /eventos
 * Carga y muestra los próximos 5 eventos desde la API
 */

(function() {
  'use strict';

  const MONTHS_ES = ['ENE', 'FEB', 'MAR', 'ABR', 'MAY', 'JUN', 'JUL', 'AGO', 'SEP', 'OCT', 'NOV', 'DIC'];
  const CATEGORY_COLORS = {
    'actividades': '',
    'talleres': '',
    'reuniones': 'orange',
    'comunidad': 'green',
    'otro': ''
  };

  /**
   * Carga y renderiza los próximos eventos
   */
  async function loadUpcomingEvents() {
    const container = document.getElementById('eventos-mini-calendario');
    if (!container) {
      console.warn('Contenedor #eventos-mini-calendario no encontrado');
      return;
    }

    try {
      // Calcular rango de fechas: desde hoy hasta 6 meses adelante
      const today = new Date();
      const sixMonthsLater = new Date();
      sixMonthsLater.setMonth(today.getMonth() + 6);

      const rangoInicial = today.toISOString().split('T')[0];
      const rangoFinal = sixMonthsLater.toISOString().split('T')[0];

      // Llamar a la API
      const response = await fetch(`/api/calendario/eventos?rango_inicial=${rangoInicial}&rango_final=${rangoFinal}&limite=5`);
      
      if (!response.ok) {
        throw new Error(`Error al cargar eventos: ${response.status}`);
      }

      const data = await response.json();

      if (!data.ok || !data.eventos || data.eventos.length === 0) {
        container.innerHTML = '<p style="text-align: center; padding: 2rem; color: var(--color-text-secondary);">No hay eventos próximos disponibles.</p>';
        return;
      }

      // Renderizar eventos
      renderEvents(data.eventos, container);
    } catch (error) {
      console.error('Error cargando mini-calendario de eventos:', error);
      container.innerHTML = '<p style="text-align: center; padding: 2rem; color: var(--color-error);">Error al cargar los eventos. Inténtalo más tarde.</p>';
    }
  }

  /**
   * Renderiza la lista de eventos en el contenedor
   * @param {Array} eventos - Array de eventos desde la API
   * @param {HTMLElement} container - Contenedor DOM
   */
  function renderEvents(eventos, container) {
    container.innerHTML = '';

    const MONTHS_EN_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

    const toTitle = (value) => {
      const s = String(value || '').trim();
      if (!s) return 'Evento';
      return s.charAt(0).toUpperCase() + s.slice(1);
    };

    const formatDateLikeCards = (dt) => {
      const d = String(dt.getDate()).padStart(2, '0');
      const m = MONTHS_EN_SHORT[dt.getMonth()];
      const y = dt.getFullYear();
      return `${d} ${m} ${y}`;
    };

    eventos.forEach((evento) => {
      const startDate = new Date(evento.inicio);
      const day = startDate.getDate();
      const month = MONTHS_ES[startDate.getMonth()];
      const time = startDate.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
      const dateLabel = formatDateLikeCards(startDate);

      const colorClass = CATEGORY_COLORS[evento.categoria] || '';
      const categoryLabel = toTitle(evento.categoria);

      const item = document.createElement('div');
      item.className = 'event-item';
      item.setAttribute('role', 'button');
      item.setAttribute('tabindex', '0');

      const payload = {
        title: String(evento.titulo || ''),
        category: categoryLabel,
        date: dateLabel,
        time,
        location: String(evento.ubicacion || ''),
        cover: String(evento.cover_image || ''),
        contentHtml: String(evento.descripcion || ''),
      };

      const open = () => {
        if (typeof window.openEventModalFromData === 'function') {
          window.openEventModalFromData(payload);
        }
      };

      item.addEventListener('click', open);
      item.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          open();
        }
      });

      const dateWrap = document.createElement('div');
      dateWrap.className = 'event-date';

      const dayEl = document.createElement('div');
      dayEl.className = `event-date-day ${colorClass}`.trim();
      dayEl.textContent = String(day);

      const monthEl = document.createElement('div');
      monthEl.className = 'event-date-month';
      monthEl.textContent = String(month);

      dateWrap.appendChild(dayEl);
      dateWrap.appendChild(monthEl);

      const info = document.createElement('div');
      info.className = 'event-info';

      const title = document.createElement('div');
      title.className = 'event-info-title';
      title.textContent = String(evento.titulo || '');

      const desc = document.createElement('div');
      desc.className = 'event-info-desc';
      desc.textContent = `${time}${evento.ubicacion ? ' - ' + String(evento.ubicacion) : ''}`;

      info.appendChild(title);
      info.appendChild(desc);

      item.appendChild(dateWrap);
      item.appendChild(info);

      container.appendChild(item);
    });
  }

  // Nota: ya no usamos innerHTML para renderizar eventos; evitamos XSS por construcción.

  // Inicializar cuando el DOM esté listo
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadUpcomingEvents);
  } else {
    loadUpcomingEvents();
  }
})();
