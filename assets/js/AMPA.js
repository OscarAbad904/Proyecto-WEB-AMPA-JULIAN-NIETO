// AMPA.js: Funciones principales para la web del AMPA Julián Nieto Tapia

// Intersection Observer para animaciones
const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
};

const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('visible');
        }
    });
}, observerOptions);

document.querySelectorAll('.fade-in').forEach(el => {
    observer.observe(el);
});

function randomizeHeroShapes() {
    const container = document.querySelector('.hero-floating-shapes');
    if (!container) return;

    if (window.__heroSpawnTimer) {
        clearInterval(window.__heroSpawnTimer);
    }

    const baseSize = 5;            // rem
    const variance = 0.2;          // +/-20%
    const spawnGapMs = 1000;       // ms between spawns (fixed 1s)
    const leftRange = [8, 32];     // keep gap for center/logo
    const rightRange = [68, 92];
    let sideToggle = 0;

    const rand = (min, max) => Math.random() * (max - min) + min;

    const createShape = () => {
        const shape = document.createElement('div');
        shape.className = `hero-shape ${Math.random() > 0.5 ? 'hero-shape--orange' : 'hero-shape--green'}`;

        const sizeFactor = 1 - variance + Math.random() * (variance * 2);
        const size = baseSize * sizeFactor;
        shape.style.width = `${size}rem`;
        shape.style.height = `${size}rem`;

        const topStart = rand(110, 135);
        const topEnd = rand(-140, -110);
        const range = (sideToggle++ % 2 === 0) ? leftRange : rightRange;
        const leftPos = rand(range[0], range[1]);

        shape.style.left = `${leftPos}%`;
        shape.style.setProperty('--hero-start-top', `${topStart}%`);
        shape.style.setProperty('--hero-end-top', `${topEnd}%`);

        const rotation = rand(-10, 10);
        shape.style.transform = `translate(-50%, -50%) rotate(${rotation}deg)`;

        const duration = rand(11, 16);
        shape.style.setProperty('--hero-duration', `${duration}s`);

        shape.style.animation = `rise var(--hero-duration, 12s) linear 1 forwards`;
        shape.classList.add('ready');
        shape.style.visibility = 'visible';

        shape.addEventListener('animationend', () => shape.remove());
        container.appendChild(shape);
    };

    // start immediately and then every second
    createShape();
    window.__heroSpawnTimer = setInterval(createShape, spawnGapMs);
}

window.addEventListener('DOMContentLoaded', () => {
    randomizeHeroShapes();
    window.addEventListener('resize', randomizeHeroShapes);
});

// Mobile menu toggle
function toggleMobileMenu() {
    const menu = document.getElementById('mobile-menu');
    if (!menu) return;
    menu.classList.toggle('open');
    document.body.classList.toggle('menu-open', menu.classList.contains('open'));
}

// News filtering
function filterNews(category) {
    const items = document.querySelectorAll('.news-item');
    const buttons = document.querySelectorAll('button[onclick^="filterNews"]');
    
    buttons.forEach(btn => {
        btn.classList.remove('bg-blue-600', 'text-white');
        btn.classList.add('bg-slate-700', 'text-gray-300');
    });
    
    event.target.classList.remove('bg-slate-700', 'text-gray-300');
    event.target.classList.add('bg-blue-600', 'text-white');
    
    items.forEach(item => {
        if (category === 'all' || item.dataset.category === category) {
            item.style.display = 'block';
        } else {
            item.style.display = 'none';
        }
    });
}

// Form handlers
// El formulario de contacto ahora se envía de forma tradicional al backend
// (sin preventDefault) para que el servidor maneje el envío de correo

function handleEventForm(event) {
    event.preventDefault();
    alert('Tu inscripción ha sido registrada correctamente. Recibirás un email de confirmación.');
}

// Document downloads
function downloadDocument(type) {
    const messages = {
        'estatutos': 'Descargando Estatutos del AMPA...',
        'actas': 'Descargando Actas de Reuniones...',
        'formularios': 'Descargando Formularios...',
        'presupuesto': 'Descargando Presupuesto Anual...'
    };
    alert(messages[type] || 'Iniciando descarga...');
}

// Modal functions
function openModal(title, content) {
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-content').innerHTML = content;
    document.getElementById('modal').classList.remove('hidden');
    document.getElementById('modal').classList.add('flex');
    document.getElementById('close-modal-btn').style.display = '';
}

function closeModal() {
    document.getElementById('modal').classList.add('hidden');
    document.getElementById('modal').classList.remove('flex');
    document.getElementById('close-modal-btn').style.display = 'none';
}

function openVolunteerForm() {
    const content = `
        <form class="space-y-4" onsubmit="handleVolunteerForm(event)">
            <div>
                <label class="block text-sm font-medium mb-2">Nombre completo</label>
                <input type="text" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-transparent" required>
            </div>
            <div>
                <label class="block text-sm font-medium mb-2">Email</label>
                <input type="email" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-transparent" required>
            </div>
            <div>
                <label class="block text-sm font-medium mb-2">Teléfono</label>
                <input type="tel" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-transparent" required>
            </div>
            <div>
                <label class="block text-sm font-medium mb-2">Áreas de interés</label>
                <div class="space-y-2">
                    <label class="flex items-center">
                        <input type="checkbox" class="mr-2"> Organización de eventos
                    </label>
                    <label class="flex items-center">
                        <input type="checkbox" class="mr-2"> Comunicación y redes sociales
                    </label>
                    <label class="flex items-center">
                        <input type="checkbox" class="mr-2"> Actividades deportivas
                    </label>
                    <label class="flex items-center">
                        <input type="checkbox" class="mr-2"> Talleres educativos
                    </label>
                </div>
            </div>
            <div>
                <label class="block text-sm font-medium mb-2">Disponibilidad</label>
                <textarea rows="3" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-transparent" placeholder="Indica tu disponibilidad horaria..."></textarea>
            </div>
            <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-3 rounded-lg transition-colors">
                Enviar Solicitud
            </button>
        </form>
    `;
    openModal('Formulario de Voluntariado', content);
}

function openProposalForm() {
    const content = `
        <form class="space-y-4" onsubmit="handleProposalForm(event)">
            <div>
                <label class="block text-sm font-medium mb-2">Nombre completo</label>
                <input type="text" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-transparent" required>
            </div>
            <div>
                <label class="block text-sm font-medium mb-2">Email</label>
                <input type="email" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-transparent" required>
            </div>
            <div>
                <label class="block text-sm font-medium mb-2">Título de la propuesta</label>
                <input type="text" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-transparent" required>
            </div>
            <div>
                <label class="block text-sm font-medium mb-2">Categoría</label>
                <select class="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-transparent">
                    <option>Actividad extraescolar</option>
                    <option>Mejora de instalaciones</option>
                    <option>Evento social</option>
                    <option>Propuesta educativa</option>
                    <option>Otra</option>
                </select>
            </div>
            <div>
                <label class="block text-sm font-medium mb-2">Descripción detallada</label>
                <textarea rows="5" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-transparent" required></textarea>
            </div>
            <button type="submit" class="w-full bg-orange-600 hover:bg-orange-700 text-white font-semibold py-3 rounded-lg transition-colors">
                Enviar Propuesta
            </button>
        </form>
    `;
    openModal('Nueva Propuesta', content);
}

function openMembershipForm() {
    const content = `
        <form class="space-y-4" onsubmit="handleMembershipForm(event)">
            <div>
                <label class="block text-sm font-medium mb-2">Nombre del padre/madre</label>
                <input type="text" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-transparent" required>
            </div>
            <div>
                <label class="block text-sm font-medium mb-2">Email</label>
                <input type="email" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-transparent" required>
            </div>
            <div>
                <label class="block text-sm font-medium mb-2">Teléfono</label>
                <input type="tel" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-transparent" required>
            </div>
            <div>
                <label class="block text-sm font-medium mb-2">Nombre del hijo/a</label>
                <input type="text" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-transparent" required>
            </div>
            <div>
                <label class="block text-sm font-medium mb-2">Curso</label>
                <select class="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-transparent">
                    <option>Infantil 3 años</option>
                    <option>Infantil 4 años</option>
                    <option>Infantil 5 años</option>
                    <option>1º Primaria</option>
                    <option>2º Primaria</option>
                    <option>3º Primaria</option>
                    <option>4º Primaria</option>
                    <option>5º Primaria</option>
                    <option>6º Primaria</option>
                </select>
            </div>
            <div class="bg-slate-700 p-4 rounded-lg">
                <h4 class="font-semibold mb-2">Cuota anual: 25€</h4>
                <p class="text-sm text-gray-300">La cuota incluye participación en todas las actividades del AMPA y descuentos en eventos especiales.</p>
            </div>
            <label class="flex items-center">
                <input type="checkbox" class="mr-2" required>
                <span class="text-sm">Acepto los estatutos del AMPA y autorizo el tratamiento de mis datos personales</span>
            </label>
            <button type="submit" class="w-full bg-green-600 hover:bg-green-700 text-white font-semibold py-3 rounded-lg transition-colors">
                Enviar Solicitud de Membresía
            </button>
        </form>
    `;
    openModal('Hazte Socio del AMPA', content);
}

function handleVolunteerForm(event) {
    event.preventDefault();
    closeModal();
    alert('¡Gracias por tu interés en ser voluntario! Nos pondremos en contacto contigo pronto.');
}

function handleProposalForm(event) {
    event.preventDefault();
    closeModal();
    alert('Tu propuesta ha sido enviada correctamente. La revisaremos y te daremos una respuesta.');
}

function handleMembershipForm(event) {
    event.preventDefault();
    closeModal();
    alert('Tu solicitud de membresía ha sido enviada. Recibirás información sobre el pago de la cuota por email.');
}

// Smooth scrolling for navigation links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            target.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }
    });
});

// Close modal when clicking outside
const __modalEl = document.getElementById('modal');
if (__modalEl) {
    __modalEl.addEventListener('click', function(e) {
        if (e.target === this) {
            closeModal();
        }
    });
}

// Función para búsqueda en la página
function buscarEnPagina() {
    const input = document.getElementById('buscadorAMPA');
    const texto = input.value.trim().toLowerCase();
    // Elimina resaltados anteriores
    document.querySelectorAll('.resaltado-busqueda').forEach(el => {
        el.outerHTML = el.innerText;
    });
    if (texto.length < 2) return;
    // Busca en los elementos principales de contenido
    const secciones = document.querySelectorAll('section, article, .card-hover, .news-item');
    secciones.forEach(sec => {
        let html = sec.innerHTML;
        const regex = new RegExp(`(${texto.replace(/[.*+?^${}()|[\\]\\]/g, '\\\\$&')})`, 'gi');
        html = html.replace(regex, '<span class="resaltado-busqueda" style="background:#fde68a;color:#1e293b;">$1</span>');
        sec.innerHTML = html;
    });
}

// Añade efecto de scroll al header para sombra y fondo
window.addEventListener('scroll', function() {
    const header = document.querySelector('.header-fixed');
    if (window.scrollY > 10) {
        header.classList.add('scrolled');
    } else {
        header.classList.remove('scrolled');
    }
});

// Nota: los recursos estáticos se sirven ahora desde assets/js/AMPA.js
