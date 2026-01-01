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
    const html = eventos.map((evento, index) => {
      const startDate = new Date(evento.inicio);
      const day = startDate.getDate();
      const month = MONTHS_ES[startDate.getMonth()];
      const time = startDate.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
      
      // Determinar color basado en categoría
      const colorClass = CATEGORY_COLORS[evento.categoria] || '';
      
      return `
        <div class="event-item">
          <div class="event-date">
            <div class="event-date-day ${colorClass}">${day}</div>
            <div class="event-date-month">${month}</div>
          </div>
          <div class="event-info">
            <div class="event-info-title">${escapeHtml(evento.titulo)}</div>
            <div class="event-info-desc">${time}${evento.ubicacion ? ' - ' + escapeHtml(evento.ubicacion) : ''}</div>
          </div>
        </div>
      `;
    }).join('');

    container.innerHTML = html;
  }

  /**
   * Escapa HTML para prevenir XSS
   * @param {string} text - Texto a escapar
   * @returns {string} - Texto escapado
   */
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // Inicializar cuando el DOM esté listo
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadUpcomingEvents);
  } else {
    loadUpcomingEvents();
  }
})();
