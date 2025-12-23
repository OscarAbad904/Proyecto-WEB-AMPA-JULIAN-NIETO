# Sistema de Personalización Visual (Estilos)

Este documento describe el sistema de personalización visual de la web AMPA, que permite
a los administradores crear y gestionar perfiles de estilo (CSS + imágenes) almacenados
en Google Drive.

## Índice

1. [Arquitectura General](#arquitectura-general)
2. [Estructura en Google Drive](#estructura-en-google-drive)
3. [Archivos Clave por Estilo](#archivos-clave-por-estilo)
4. [Configuración](#configuración)
5. [Comandos CLI](#comandos-cli)
6. [Endpoints de Estilo](#endpoints-de-estilo)
7. [Sistema de Caché](#sistema-de-caché)
8. [Fallback a Assets Locales](#fallback-a-assets-locales)
9. [API de Administración](#api-de-administración)
10. [Uso en Plantillas](#uso-en-plantillas)
11. [Permisos](#permisos)

---

## Arquitectura General

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Google Drive   │────▶│   style_service  │────▶│   Cache Local   │
│  (Estilos/*)    │     │                  │     │ (cache/styles/) │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌──────────────────┐
                        │   style.py       │
                        │   (Blueprint)    │
                        └──────────────────┘
                               │
                               ▼
                        ┌──────────────────┐
                        │   Plantillas     │
                        │   (style_urls)   │
                        └──────────────────┘
```

## Estructura en Google Drive

```
WEB Ampa/                           # Carpeta raíz (GOOGLE_DRIVE_ROOT_FOLDER_ID)
├── Estilos/                        # Carpeta de estilos (creada automáticamente)
│   ├── Navidad/                    # Perfil de estilo "Navidad"
│   │   ├── style.css               # CSS personalizado
│   │   ├── logo_header.png         # Logo del header (cabecera)
│   │   ├── logo_hero.png           # Logo del hero (página principal)
│   │   └── placeholder.png         # Imagen placeholder para contenido
│   │
│   ├── General/                    # Perfil de estilo "General"
│   │   ├── style.css
│   │   ├── logo_header.png
│   │   ├── logo_hero.png
│   │   └── placeholder.png
│   │
│   └── [Otros estilos]/            # Estilos personalizados adicionales
│       └── ...
│
├── Noticias/                       # Otras carpetas existentes
├── Eventos/
└── Documentos/
```

## Archivos Clave por Estilo

| Archivo           | Descripción                                          | Uso                              |
|-------------------|------------------------------------------------------|----------------------------------|
| `style.css`       | Hoja de estilos CSS del perfil                       | Cargada en `<head>` de layout    |
| `logo_header.png` | Logo mostrado en el header/navbar                    | Header de todas las páginas      |
| `logo_hero.png`   | Logo grande para la sección hero                     | Página principal (index.html)    |
| `placeholder.png` | Imagen por defecto para contenido sin imagen         | Noticias, eventos sin portada    |

> **Nota**: Las extensiones pueden variar (.jpg, .webp, etc.). El sistema busca por nombre base.

## Configuración

### Variables de Entorno Requeridas

```env
# Ya existentes (necesarias para Drive)
GOOGLE_DRIVE_ROOT_FOLDER_ID=<id_carpeta_raiz>
GOOGLE_DRIVE_TOKEN_JSON=<token_oauth_cifrado>
FERNET_KEY=<clave_fernet>

# Opcional: timeout de caché en segundos (default: 3600)
STYLE_CACHE_TTL=3600
```

### Configuración en Base de Datos

El estilo activo se almacena en la tabla `site_settings`:

```sql
SELECT * FROM site_settings WHERE key = 'active_style';
-- value: 'Navidad'
```

## Comandos CLI

### Inicializar Estilos por Defecto

Crea los estilos "Navidad" y "General" en Drive usando los assets locales:

```bash
flask init-styles

# Sobrescribir si ya existen:
flask init-styles --force
```

### Listar Estilos Disponibles

```bash
flask list-styles
```

Salida ejemplo:
```
🎨 Estilos disponibles en Google Drive:

   • Navidad ← ACTIVO
     - style.css
     - logo_header.png
     - logo_hero.png
     - placeholder.png
   • General
     - style.css
     - logo_header.png

   Total: 2 estilo(s)
```

## Endpoints de Estilo

El blueprint `style` expone los siguientes endpoints bajo `/style/`:

| Endpoint                          | Descripción                                      |
|-----------------------------------|--------------------------------------------------|
| `/style/current/style.css`        | CSS del estilo activo                            |
| `/style/current/<filename>`       | Archivo del estilo activo                        |
| `/style/<name>/<filename>`        | Archivo de un estilo específico                  |
| `/style/logo/header`              | Logo del header (redirect/proxy)                 |
| `/style/logo/hero`                | Logo del hero (redirect/proxy)                   |
| `/style/logo/placeholder`         | Imagen placeholder (redirect/proxy)              |
| `/style/info`                     | JSON con información del estilo activo           |

### Headers de Respuesta

- `Cache-Control`: Cacheo del navegador (1 hora por defecto)
- `ETag`: Para validación condicional
- `Content-Type`: MIME type apropiado según extensión

## Sistema de Caché

### Ubicación

```
cache/
└── styles/
    ├── Navidad/
    │   ├── _metadata.json      # Metadatos y timestamps
    │   ├── style.css
    │   ├── logo_header.png
    │   └── ...
    └── General/
        └── ...
```

### Metadatos (`_metadata.json`)

```json
{
  "style_name": "Navidad",
  "cached_at": "2024-12-15T10:30:00Z",
  "files": {
    "style.css": {
      "drive_id": "abc123...",
      "cached_at": "2024-12-15T10:30:00Z",
      "size": 4521
    }
  }
}
```

### Invalidación de Caché

Desde la UI de administración o programáticamente:

```python
from app.services.style_service import invalidate_style_cache

# Invalidar un estilo específico
invalidate_style_cache("Navidad")

# Invalidar todos los estilos
invalidate_style_cache()
```

## Fallback a Assets Locales

Si Google Drive no está disponible o un archivo no existe, el sistema usa assets locales:

| Archivo Estilo    | Fallback Local                           |
|-------------------|------------------------------------------|
| `style.css`       | `/static/css/AMPA.css`                   |
| `logo_header.png` | `/static/images/navidad/Logo_AMPA.png`   |
| `logo_hero.png`   | `/static/images/navidad/Logo_AMPA.png`   |
| `placeholder.png` | `/static/images/navidad/Logo_AMPA.png`   |

El fallback es automático y transparente para el usuario.

## API de Administración

Endpoints bajo `/admin/personalizacion/`:

| Método | Endpoint                              | Descripción                          |
|--------|---------------------------------------|--------------------------------------|
| GET    | `/personalizacion`                    | Página de gestión de estilos         |
| GET    | `/personalizacion/crear`              | Formulario de nuevo estilo           |
| POST   | `/personalizacion/crear`              | Crear nuevo estilo                   |
| POST   | `/personalizacion/api/style/<n>/activate` | Activar estilo                   |
| GET    | `/personalizacion/api/style/<n>/files`    | Listar archivos del estilo       |
| GET    | `/personalizacion/api/style/<n>/css`      | Obtener CSS del estilo           |
| POST   | `/personalizacion/api/style/<n>/css`      | Actualizar CSS del estilo        |
| POST   | `/personalizacion/api/style/<n>/upload`   | Subir archivo al estilo          |
| POST   | `/personalizacion/api/style/<n>/duplicate`| Duplicar estilo                  |
| DELETE | `/personalizacion/api/style/<n>/delete`   | Eliminar estilo                  |
| POST   | `/personalizacion/api/initialize`         | Inicializar estilos por defecto  |

## Uso en Plantillas

El context processor inyecta `style_urls` en todas las plantillas:

```jinja2
{# CSS dinámico en <head> #}
<link rel="stylesheet" href="{{ style_urls.style_css }}">

{# Logo del header #}
<img src="{{ style_urls.logo_header }}" alt="AMPA Logo">

{# Logo del hero #}
<img src="{{ style_urls.logo_hero }}" alt="AMPA">

{# Imagen placeholder para contenido sin imagen #}
<img src="{{ post.image_url or style_urls.placeholder }}" alt="{{ post.title }}">
```

### Variables Disponibles

| Variable                  | Descripción                              |
|---------------------------|------------------------------------------|
| `style_urls.style_css`    | URL del CSS del estilo activo            |
| `style_urls.logo_header`  | URL del logo del header                  |
| `style_urls.logo_hero`    | URL del logo del hero                    |
| `style_urls.placeholder`  | URL de la imagen placeholder             |
| `style_urls.active_style` | Nombre del estilo activo                 |

## Permisos

El permiso `manage_styles` controla el acceso a la personalización:

```python
# En permission_registry.py
{
    "key": "manage_styles",
    "name": "Gestionar estilos visuales",
    "description": "Crear, editar y activar perfiles de estilo visual de la web.",
    "section": "Sistema"
}
```

### Verificación en Plantillas

```jinja2
{% if can_manage_styles %}
<a href="{{ url_for('admin.personalizacion') }}">🎨 Estilos</a>
{% endif %}
```

### Verificación en Rutas

```python
from app.utils import permission_required

@bp.route("/personalizacion")
@login_required
@permission_required("manage_styles")
def personalizacion():
    ...
```

---

## Troubleshooting

### El estilo no se carga

1. Verifica que Drive esté configurado: `flask setup-drive-folders`
2. Inicializa estilos: `flask init-styles`
3. Comprueba los logs en `logs/app.log`

### Las imágenes no aparecen

1. Verifica que los archivos existen en Drive
2. Limpia la caché desde Admin > Personalización
3. Comprueba que el estilo activo tiene los archivos requeridos

### CSS no actualiza

1. El navegador puede tener caché - haz hard refresh (Ctrl+F5)
2. Invalida la caché del servidor desde Admin > Personalización
3. Verifica que el CSS se guardó correctamente en Drive

---

## Archivos del Sistema

| Archivo                              | Descripción                           |
|--------------------------------------|---------------------------------------|
| `app/services/style_service.py`      | Servicio principal de estilos         |
| `app/routes/style.py`                | Blueprint para servir assets          |
| `app/routes/admin.py`                | Rutas de administración               |
| `templates/admin/personalizacion.html`| UI de administración                 |
| `app/models.py` (SiteSetting)        | Modelo para configuración             |
| `cache/styles/`                      | Directorio de caché local             |
