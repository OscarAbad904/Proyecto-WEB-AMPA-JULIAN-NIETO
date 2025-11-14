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

// Mobile menu toggle
function toggleMobileMenu() {
    const menu = document.getElementById('mobile-menu');
    menu.classList.toggle('hidden');
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
function handleContactForm(event) {
    event.preventDefault();
    alert('Gracias por tu mensaje. Nos pondremos en contacto contigo pronto.');
}

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
document.getElementById('modal').addEventListener('click', function(e) {
    if (e.target === this) {
        closeModal();
    }
});

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
        const regex = new RegExp(`(${texto.replace(/[.*+?^${}()|[\\]\\]/g, '\\$&')})`, 'gi');
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

// Navegación tipo SPA: oculta todas las secciones y muestra solo la seleccionada
function mostrarSeccion(id) {
    document.querySelectorAll('section').forEach(sec => {
        sec.style.display = 'none';
    });
    const target = document.getElementById(id);
    if (target) {
        target.style.display = '';
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
    // Quitar clase active de todos los enlaces
    document.querySelectorAll('.nav-link').forEach(link => link.classList.remove('active'));
    // Añadir clase active al enlace seleccionado
    const navLinks = document.querySelectorAll('.nav-link[href="#' + id + '"]');
    navLinks.forEach(link => link.classList.add('active'));
    // Cerrar menú móvil si está abierto
    const menu = document.getElementById('mobile-menu');
    if (menu && !menu.classList.contains('hidden')) menu.classList.add('hidden');
}
// Interceptar clicks en el menú para navegación SPA
window.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.nav-link').forEach(link => {
        const href = link.getAttribute('href');
        if (href && href.startsWith('#')) {
            link.addEventListener('click', function(e) {
                e.preventDefault();
                mostrarSeccion(href.substring(1));
            });
        }
    });
    // Mostrar solo la sección de inicio al cargar
    mostrarSeccion('inicio');
});

// Interceptar clicks en los enlaces del footer para navegación SPA
window.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.footer-link').forEach(link => {
        const href = link.getAttribute('href');
        if (href && href.startsWith('#')) {
            link.addEventListener('click', function(e) {
                e.preventDefault();
                mostrarSeccion(href.substring(1));
            });
        }
    });
});

// Nota: los recursos estáticos se sirven ahora desde assets/js/AMPA.js
