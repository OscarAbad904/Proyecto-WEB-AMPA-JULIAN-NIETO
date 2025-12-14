/**
 * JavaScript para el Gestor de Configuración AMPA
 * Maneja la lógica del panel de administración de variables de entorno
 */

document.addEventListener('DOMContentLoaded', function() {
    // Referencias DOM
    const envForm = document.getElementById('envForm');
    const saveBtn = document.getElementById('saveBtn');
    const setupDriveFoldersBtn = document.getElementById('setupDriveFoldersBtn');
    const testDbBtn = document.getElementById('testDbBtn');
    const forceDbBackupBtn = document.getElementById('forceDbBackupBtn');
    const restoreDbBtn = document.getElementById('restoreDbBtn');
    const testCalendarBtn = document.getElementById('testCalendarBtn');
    const changePasswordBtn = document.getElementById('changePasswordBtn');
    const helpModal = document.getElementById('helpModal');
    const passwordModal = document.getElementById('passwordModal');
    const restoreDbModal = document.getElementById('restoreDbModal');
    const navItems = document.querySelectorAll('.nav-item');
    
    // Cargar ENV_VARIABLES desde data attribute
    const envDataEl = document.getElementById('envData');
    window.ENV_VARIABLES = envDataEl ? JSON.parse(envDataEl.dataset.env || '{}') : {};
    
    // Estado
    let currentEnv = {};
    let isDirty = false;
    
    // ============================================
    // Inicialización
    // ============================================
    
    init();
    
    async function init() {
        await loadEnvVariables();
        setupEventListeners();
        highlightActiveSection();
    }
    
    // ============================================
    // Carga de variables
    // ============================================
    
    async function loadEnvVariables() {
        try {
            const response = await fetch('/api/env');
            const data = await response.json();
            
            if (data.ok) {
                currentEnv = data.env;
                populateForm(data.env);
            } else {
                showToast('error', 'Error', data.error || 'No se pudieron cargar las variables');
            }
        } catch (error) {
            showToast('error', 'Error de conexión', 'No se pudo conectar con el servidor');
            console.error('Error loading env:', error);
        }
    }
    
    function populateForm(env) {
        for (const [key, value] of Object.entries(env)) {
            const field = document.getElementById(`field_${key}`);
            if (field) {
                field.value = value || '';
            }
        }
    }
    
    // ============================================
    // Event Listeners
    // ============================================
    
    function setupEventListeners() {
        // Guardar cambios
        saveBtn.addEventListener('click', saveChanges);

        // Configurar Drive (carpetas + IDs)
        if (setupDriveFoldersBtn) {
            setupDriveFoldersBtn.addEventListener('click', setupDriveFolders);
        }
        
        // Probar BD
        testDbBtn.addEventListener('click', testDatabase);

        // Forzar backup BD
        if (forceDbBackupBtn) {
            forceDbBackupBtn.addEventListener('click', forceDbBackup);
        }

        // Restaurar BD
        if (restoreDbBtn) {
            restoreDbBtn.addEventListener('click', openRestoreDbModal);
        }
        
        // Probar Calendario
        testCalendarBtn.addEventListener('click', testCalendar);
        
        // Probar Correo
        const testMailBtn = document.getElementById('testMailBtn');
        if (testMailBtn) {
            testMailBtn.addEventListener('click', testMail);
        }
        
        // Cambiar contraseña
        changePasswordBtn.addEventListener('click', () => openModal(passwordModal));
        
        // Formulario de contraseña
        document.getElementById('passwordForm').addEventListener('submit', handlePasswordChange);
        
        // Botones de ayuda
        document.querySelectorAll('.btn-help').forEach(btn => {
            btn.addEventListener('click', () => showHelp(btn.dataset.var));
        });
        
        // Cerrar modales
        document.querySelectorAll('.modal-close, .modal-overlay').forEach(el => {
            el.addEventListener('click', closeAllModals);
        });
        
        // Toggle visibilidad de campos sensibles
        document.querySelectorAll('.toggle-visibility').forEach(btn => {
            btn.addEventListener('click', () => toggleFieldVisibility(btn.dataset.target));
        });
        
        // Navegación
        navItems.forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const target = document.querySelector(item.getAttribute('href'));
                if (target) {
                    target.scrollIntoView({ behavior: 'smooth' });
                    updateActiveNav(item);
                }
            });
        });
        
        // Detectar cambios
        envForm.addEventListener('input', () => {
            isDirty = true;
            saveBtn.classList.add('has-changes');
        });
        
        // Scroll tracking
        window.addEventListener('scroll', highlightActiveSection);
        
        // Atajos de teclado
        document.addEventListener('keydown', (e) => {
            // Ctrl+S para guardar
            if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                e.preventDefault();
                saveChanges();
            }
            // Escape para cerrar modales
            if (e.key === 'Escape') {
                closeAllModals();
            }
        });
        
        // Advertir antes de salir con cambios pendientes
        window.addEventListener('beforeunload', (e) => {
            if (isDirty) {
                e.preventDefault();
                e.returnValue = '';
            }
        });
    }
    
    // ============================================
    // Guardar configuración
    // ============================================
    
    async function saveChanges() {
        const formData = new FormData(envForm);
        const env = {};
        
        for (const [key, value] of formData.entries()) {
            env[key] = value;
        }
        
        // Mostrar estado de carga
        saveBtn.classList.add('loading');
        saveBtn.disabled = true;
        
        try {
            const response = await fetch('/api/env', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ env })
            });
            
            const data = await response.json();
            
            if (data.ok) {
                isDirty = false;
                saveBtn.classList.remove('has-changes');
                
                let message = data.message;
                if (data.files_created && data.files_created.length > 0) {
                    message += `\nArchivos generados: ${data.files_created.join(', ')}`;
                }
                
                showToast('success', 'Guardado', message);
                
                if (data.errors && data.errors.length > 0) {
                    showToast('warning', 'Advertencias', data.errors.join('\n'));
                }
            } else {
                showToast('error', 'Error', data.error || 'No se pudo guardar');
            }
        } catch (error) {
            showToast('error', 'Error de conexión', 'No se pudo conectar con el servidor');
            console.error('Error saving:', error);
        } finally {
            saveBtn.classList.remove('loading');
            saveBtn.disabled = false;
        }
    }
    
    // ============================================
    // Pruebas de conexión
    // ============================================
    
    async function testDatabase() {
        testDbBtn.disabled = true;
        testDbBtn.innerHTML = `
            <svg class="spinner" viewBox="0 0 24 24" style="width:18px;height:18px">
                <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-dasharray="31.4" stroke-dashoffset="10"></circle>
            </svg>
            Probando...
        `;
        
        try {
            const response = await fetch('/api/test-db');
            const data = await response.json();
            
            if (data.ok) {
                showToast('success', 'Base de datos', data.message);
            } else {
                showToast('error', 'Error de BD', data.error);
            }
        } catch (error) {
            showToast('error', 'Error', 'No se pudo realizar la prueba');
        } finally {
            testDbBtn.disabled = false;
            testDbBtn.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <ellipse cx="12" cy="5" rx="9" ry="3"></ellipse>
                    <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path>
                    <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path>
                </svg>
                Probar BD
            `;
        }
    }

    async function setupDriveFolders() {
        setupDriveFoldersBtn.disabled = true;
        setupDriveFoldersBtn.innerHTML = `
            <svg class="spinner" viewBox="0 0 24 24" style="width:18px;height:18px">
                <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-dasharray="31.4" stroke-dashoffset="10"></circle>
            </svg>
            Configurando...
        `;

        try {
            const response = await fetch('/api/setup-drive-folders', { method: 'POST' });
            const data = await response.json();

            if (data.ok) {
                showToast('success', 'Google Drive', data.message || 'Carpetas configuradas');
                await loadEnvVariables();
            } else {
                showToast('error', 'Google Drive', data.error || 'No se pudo configurar Drive');
            }
        } catch (error) {
            showToast('error', 'Google Drive', 'No se pudo realizar la operacion');
        } finally {
            setupDriveFoldersBtn.disabled = false;
            setupDriveFoldersBtn.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                    <polyline points="7 10 12 15 17 10"></polyline>
                    <line x1="12" y1="15" x2="12" y2="3"></line>
                </svg>
                Configurar Drive
            `;
        }
    }
    
    async function forceDbBackup() {
        forceDbBackupBtn.disabled = true;
        forceDbBackupBtn.innerHTML = `
            <svg class="spinner" viewBox="0 0 24 24" style="width:18px;height:18px">
                <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-dasharray="31.4" stroke-dashoffset="10"></circle>
            </svg>
            Creando copia...
        `;

        try {
            const response = await fetch('/api/force-db-backup', { method: 'POST' });
            const data = await response.json();

            if (data.ok) {
                let msg = data.message || 'Copia creada correctamente';
                if (data.drive_file_id) {
                    msg += ` (Drive file: ${data.drive_file_id})`;
                }
                showToast('success', 'Backup BD', msg);
            } else {
                showToast('error', 'Backup BD', data.error || 'No se pudo crear la copia');
            }
        } catch (error) {
            showToast('error', 'Backup BD', 'No se pudo realizar la operacion');
        } finally {
            forceDbBackupBtn.disabled = false;
            forceDbBackupBtn.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 2v6"></path>
                    <path d="M9 5l3 3 3-3"></path>
                    <rect x="4" y="10" width="16" height="12" rx="2"></rect>
                    <path d="M8 14h8"></path>
                    <path d="M8 18h5"></path>
                </svg>
                Forzar copia BD
            `;
        }
    }

    async function openRestoreDbModal() {
        const select = document.getElementById('restoreBackupSelect');
        const confirmInput = document.getElementById('restoreConfirmInput');
        const confirmBtn = document.getElementById('restoreDbConfirmBtn');

        if (!select || !confirmInput || !confirmBtn) return;

        select.innerHTML = '';
        confirmInput.value = '';
        confirmBtn.disabled = true;
        confirmBtn.textContent = 'Cargando backups...';

        openModal(restoreDbModal);

        try {
            const response = await fetch('/api/db-backups');
            const data = await response.json();

            if (!data.ok) {
                showToast('error', 'Backups', data.error || 'No se pudo listar backups');
                closeAllModals();
                return;
            }

            const files = Array.isArray(data.files) ? data.files : [];
            if (files.length === 0) {
                select.innerHTML = '<option value="">(No hay backups)</option>';
                confirmBtn.disabled = true;
                confirmBtn.textContent = 'Restaurar';
                return;
            }

            files.forEach((f) => {
                const opt = document.createElement('option');
                opt.value = f.id;
                const created = f.createdTime ? ` - ${f.createdTime}` : '';
                opt.textContent = `${f.name}${created}`;
                select.appendChild(opt);
            });

            confirmBtn.disabled = false;
            confirmBtn.textContent = 'Restaurar';

            confirmBtn.onclick = async () => {
                const fileId = select.value;
                const confirm = (confirmInput.value || '').trim();
                if (!fileId) {
                    showToast('warning', 'Restaurar BD', 'Selecciona un backup');
                    return;
                }
                if (confirm.toUpperCase() !== 'RESTAURAR') {
                    showToast('warning', 'Restaurar BD', 'Escribe RESTAURAR para confirmar');
                    return;
                }

                confirmBtn.disabled = true;
                confirmBtn.textContent = 'Restaurando...';
                try {
                    const res = await fetch('/api/restore-db-backup', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ file_id: fileId, confirm: confirm }),
                    });
                    const payload = await res.json();
                    if (payload.ok) {
                        showToast('success', 'Restaurar BD', payload.message || 'Restauración completada');
                        closeAllModals();
                    } else {
                        showToast('error', 'Restaurar BD', payload.error || 'No se pudo restaurar');
                    }
                } catch (err) {
                    showToast('error', 'Restaurar BD', 'No se pudo realizar la operacion');
                } finally {
                    confirmBtn.disabled = false;
                    confirmBtn.textContent = 'Restaurar';
                }
            };
        } catch (error) {
            showToast('error', 'Backups', 'No se pudo listar backups');
            closeAllModals();
        }
    }
    
    async function testCalendar() {
        testCalendarBtn.disabled = true;
        testCalendarBtn.innerHTML = `
            <svg class="spinner" viewBox="0 0 24 24" style="width:18px;height:18px">
                <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-dasharray="31.4" stroke-dashoffset="10"></circle>
            </svg>
            Probando...
        `;
        
        try {
            const response = await fetch('/api/test-calendar');
            const data = await response.json();
            
            if (data.ok) {
                const count = data.events ? data.events.length : 0;
                showToast('success', 'Calendario OK', `Se encontraron ${count} eventos próximos`);
            } else {
                showToast('error', 'Error de Calendario', data.error);
            }
        } catch (error) {
            showToast('error', 'Error', 'No se pudo realizar la prueba');
        } finally {
            testCalendarBtn.disabled = false;
            testCalendarBtn.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
                    <line x1="16" y1="2" x2="16" y2="6"></line>
                    <line x1="8" y1="2" x2="8" y2="6"></line>
                    <line x1="3" y1="10" x2="21" y2="10"></line>
                </svg>
                Probar Calendario
            `;
        }
    }
    
    async function testMail() {
        const testMailBtn = document.getElementById('testMailBtn');
        testMailBtn.disabled = true;
        testMailBtn.innerHTML = `
            <svg class="spinner" viewBox="0 0 24 24" style="width:18px;height:18px">
                <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-dasharray="31.4" stroke-dashoffset="10"></circle>
            </svg>
            Enviando...
        `;
        
        try {
            const response = await fetch('/api/test-mail');
            const data = await response.json();
            
            if (data.ok) {
                showToast('success', 'Correo enviado', data.message);
            } else {
                showToast('error', 'Error de correo', data.error);
            }
        } catch (error) {
            showToast('error', 'Error', 'No se pudo realizar la prueba');
        } finally {
            testMailBtn.disabled = false;
            testMailBtn.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path>
                    <polyline points="22,6 12,13 2,6"></polyline>
                </svg>
                Probar Correo
            `;
        }
    }
    
    // ============================================
    // Cambio de contraseña
    // ============================================
    
    async function handlePasswordChange(e) {
        e.preventDefault();
        
        const newPassword = document.getElementById('newPassword').value;
        const confirmPassword = document.getElementById('confirmPassword').value;
        const errorEl = document.getElementById('passwordError');
        
        if (newPassword !== confirmPassword) {
            errorEl.textContent = 'Las contraseñas no coinciden';
            errorEl.classList.remove('hidden');
            return;
        }
        
        errorEl.classList.add('hidden');
        
        try {
            const response = await fetch('/api/change-password', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ password: newPassword })
            });
            
            const data = await response.json();
            
            if (data.ok) {
                showToast('success', 'Contraseña actualizada', data.message);
                closeAllModals();
                document.getElementById('passwordForm').reset();
            } else {
                errorEl.textContent = data.error;
                errorEl.classList.remove('hidden');
            }
        } catch (error) {
            errorEl.textContent = 'Error de conexión';
            errorEl.classList.remove('hidden');
        }
    }
    
    // ============================================
    // Sistema de ayuda
    // ============================================
    
    function showHelp(varName) {
        // Buscar la info de la variable en ENV_VARIABLES
        let helpInfo = null;
        let varLabel = varName;
        
        for (const group of Object.values(window.ENV_VARIABLES)) {
            if (group.vars && group.vars[varName]) {
                const varConfig = group.vars[varName];
                helpInfo = varConfig.help;
                varLabel = varConfig.label;
                break;
            }
        }
        
        if (!helpInfo) {
            showToast('info', 'Sin ayuda', 'No hay información de ayuda para esta variable');
            return;
        }
        
        // Rellenar modal
        document.getElementById('helpModalTitle').textContent = `${varLabel} (${varName})`;
        document.getElementById('helpDescription').textContent = helpInfo.description || 'Sin descripción';
        document.getElementById('helpHowTo').textContent = helpInfo.how_to_get || 'Sin instrucciones';
        document.getElementById('helpExample').textContent = helpInfo.example || 'Sin ejemplo';
        
        const warningSection = document.getElementById('helpWarningSection');
        const warningText = document.getElementById('helpWarning');
        
        if (helpInfo.warning) {
            warningText.textContent = helpInfo.warning;
            warningSection.classList.remove('hidden');
        } else {
            warningSection.classList.add('hidden');
        }
        
        openModal(helpModal);
    }
    
    // ============================================
    // Modales
    // ============================================
    
    function openModal(modal) {
        modal.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
    }
    
    function closeAllModals() {
        document.querySelectorAll('.modal').forEach(m => m.classList.add('hidden'));
        document.body.style.overflow = '';
    }
    
    // ============================================
    // Toggle visibilidad de campos
    // ============================================
    
    function toggleFieldVisibility(targetId) {
        const field = document.getElementById(targetId);
        if (!field) return;
        
        if (field.type === 'password') {
            field.type = 'text';
        } else if (field.type === 'text' && field.classList.contains('sensitive-field')) {
            field.type = 'password';
        } else if (field.tagName === 'TEXTAREA') {
            field.classList.toggle('visible');
            // Para textareas sensibles, podríamos usar CSS para ocultar
        }
    }
    
    // ============================================
    // Navegación
    // ============================================
    
    function updateActiveNav(activeItem) {
        navItems.forEach(item => item.classList.remove('active'));
        activeItem.classList.add('active');
    }
    
    function highlightActiveSection() {
        const sections = document.querySelectorAll('.config-section');
        const headerOffset = 100;
        
        let currentSection = sections[0];
        
        sections.forEach(section => {
            const rect = section.getBoundingClientRect();
            if (rect.top <= headerOffset) {
                currentSection = section;
            }
        });
        
        if (currentSection) {
            navItems.forEach(item => {
                const href = item.getAttribute('href');
                if (href === `#${currentSection.id}`) {
                    item.classList.add('active');
                } else {
                    item.classList.remove('active');
                }
            });
        }
    }
    
    // ============================================
    // Sistema de Toast
    // ============================================
    
    function showToast(type, title, message) {
        const container = document.getElementById('toastContainer');
        
        const icons = {
            success: '✅',
            error: '❌',
            warning: '⚠️',
            info: 'ℹ️'
        };
        
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `
            <span class="toast-icon">${icons[type] || 'ℹ️'}</span>
            <div class="toast-content">
                <div class="toast-title">${escapeHtml(title)}</div>
                ${message ? `<div class="toast-message">${escapeHtml(message)}</div>` : ''}
            </div>
            <button class="toast-close" aria-label="Cerrar">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
            </button>
        `;
        
        const closeBtn = toast.querySelector('.toast-close');
        closeBtn.addEventListener('click', () => removeToast(toast));
        
        container.appendChild(toast);
        
        // Auto-remove después de 5 segundos
        setTimeout(() => removeToast(toast), 5000);
    }
    
    function removeToast(toast) {
        toast.style.animation = 'toastOut 0.3s ease-out forwards';
        setTimeout(() => toast.remove(), 300);
    }
    
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
});

// Añadir animación de salida para toasts
const style = document.createElement('style');
style.textContent = `
    @keyframes toastOut {
        to {
            opacity: 0;
            transform: translateX(100%);
        }
    }
    
    .btn-primary.has-changes {
        animation: pulse 2s infinite;
    }
    
    @keyframes pulse {
        0%, 100% { box-shadow: 0 0 0 0 rgba(79, 70, 229, 0.4); }
        50% { box-shadow: 0 0 0 8px rgba(79, 70, 229, 0); }
    }
`;
document.head.appendChild(style);
