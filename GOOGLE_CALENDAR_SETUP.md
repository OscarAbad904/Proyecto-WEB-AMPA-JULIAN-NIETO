# Configuración de Google Calendar para AMPA

Este documento explica cómo configurar la integración con Google Calendar para la web del AMPA Julián Nieto.

## Requisitos Previos

1. Una cuenta de Google con acceso al Google Cloud Console
2. Las credenciales OAuth ya configuradas para Google Drive (archivo `credentials_drive_oauth.json`)
3. Acceso al calendario de Google del AMPA

## Arquitectura de la Integración

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│    Frontend     │────▶│   Backend API   │────▶│ Google Calendar │
│  (calendario.js)│     │   (/api/...)    │     │      API        │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                      │
         │                      ▼
         │              ┌─────────────────┐
         │              │  Cache Interna  │
         │              │  (10-15 min)    │
         │              └─────────────────┘
         │
         ▼
  ┌─────────────────┐
  │  Cache Browser  │
  │    (1 min)      │
  └─────────────────┘
```

## Paso 1: Ampliar Scopes de OAuth

El sistema ya tiene configurado OAuth para Google Drive. Para añadir Calendar:

### 1.1 Regenerar el Token

En tu entorno **local**, ejecuta:

```bash
flask regenerate-google-token
```

Este comando:
- Elimina el token actual (`token_drive.json`)
- Abre el navegador para autorización
- Solicita permisos para:
  - `https://www.googleapis.com/auth/drive.file` (Drive)
  - `https://www.googleapis.com/auth/calendar.events.readonly` (Calendar)
- Genera un nuevo token con ambos permisos

### 1.2 Autorizar en Google

Cuando se abra el navegador:
1. Selecciona la cuenta de Google del AMPA
2. **Autoriza TODOS los permisos** solicitados
3. El token se guardará automáticamente

## Paso 2: Obtener el Calendar ID

El Calendar ID es el identificador único del calendario del AMPA. Puede ser:

- **Calendario principal**: `primary` (la cuenta de correo del usuario)
- **Calendario específico**: `correo@gmail.com` o un ID largo como `abc123...@group.calendar.google.com`

### Para encontrar el Calendar ID:

1. Ve a [Google Calendar](https://calendar.google.com)
2. En la barra lateral, busca el calendario del AMPA
3. Haz clic en los tres puntos → "Configuración y uso compartido"
4. Baja hasta "Integrar el calendario"
5. Copia el "ID del calendario"

## Paso 3: Configurar Variables de Entorno

### Variables Nuevas para Calendar

```env
# ID del calendario de Google (obligatorio)
GOOGLE_CALENDAR_ID=correo-del-ampa@gmail.com

# Tiempo de cache en segundos (opcional, por defecto 600 = 10 min)
GOOGLE_CALENDAR_CACHE_TTL=600
```

### Variables OAuth Existentes (ya configuradas)

```env
# Credenciales OAuth encriptadas
GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON=gAAAAABp...

# Token OAuth encriptado (debe regenerarse con los nuevos scopes)
GOOGLE_DRIVE_TOKEN_JSON=gAAAAABp...
```

## Paso 4: Desplegar en Render

### 4.1 Preparar el Token

1. Lee el contenido del nuevo `token_drive.json`
2. Encríptalo con tu clave Fernet:

```python
from config import encrypt_value

with open('token_drive.json', 'r') as f:
    token_content = f.read()

encrypted = encrypt_value(token_content)
print(encrypted)  # Copia este valor
```

### 4.2 Actualizar Variables en Render

En el dashboard de Render, añade/actualiza:

| Variable | Valor |
|----------|-------|
| `GOOGLE_CALENDAR_ID` | El ID del calendario |
| `GOOGLE_CALENDAR_CACHE_TTL` | `600` (opcional) |
| `GOOGLE_DRIVE_TOKEN_JSON` | El token encriptado nuevo |

### 4.3 Redesplegar

Render debería redesplegar automáticamente. Si no, hazlo manualmente.

## Paso 5: Probar la Integración

### Test desde CLI

```bash
flask test-calendar
```

Esto mostrará:
- Estado de la conexión
- Nombre del calendario
- Próximos eventos

### Test desde el Navegador

1. Accede a `/calendario` en tu web
2. Deberías ver la vista de calendario con eventos

### Test de la API

```bash
curl https://tu-dominio.onrender.com/api/calendario/eventos
```

Respuesta esperada:
```json
{
  "ok": true,
  "eventos": [...],
  "total": 5,
  "desde": "2025-11-30T00:00:00Z",
  "hasta": "2026-05-30T00:00:00Z",
  "cached": false
}
```

## Parámetros del Endpoint

### GET `/api/calendario/eventos`

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `rango_inicial` | string | Fecha inicial (YYYY-MM-DD) |
| `rango_final` | string | Fecha final (YYYY-MM-DD) |
| `limite` | int | Número máximo de eventos (default: 50) |

Ejemplos:
```
/api/calendario/eventos
/api/calendario/eventos?rango_inicial=2025-12-01&rango_final=2025-12-31
/api/calendario/eventos?limite=10
```

### POST `/api/calendario/limpiar-cache`

Requiere autenticación. Limpia la cache del calendario.

## Sistema de Cache

### Cache del Servidor (Backend)

- **TTL por defecto**: 10 minutos
- **Configurable**: Variable `GOOGLE_CALENDAR_CACHE_TTL`
- **Fallback**: Si la API falla, devuelve cache aunque esté expirada

### Cache del Cliente (Frontend)

- **TTL**: 1 minuto
- **Propósito**: Evitar llamadas excesivas al cambiar de vista

## Formato de Eventos

Cada evento tiene la siguiente estructura:

```json
{
  "id": "abc123...",
  "titulo": "Reunión de padres",
  "descripcion": "Descripción del evento...",
  "inicio": "2025-12-15T18:00:00+01:00",
  "fin": "2025-12-15T19:30:00+01:00",
  "ubicacion": "Sala de reuniones",
  "url": "https://www.google.com/calendar/event?eid=...",
  "todo_el_dia": false,
  "color": "",
  "organizador": "AMPA"
}
```

## Solución de Problemas

### Error: "Servicio de Google Calendar no disponible"

1. Verifica que el token tenga permisos de Calendar
2. Regenera el token: `flask regenerate-google-token`
3. Actualiza `GOOGLE_DRIVE_TOKEN_JSON` en Render

### Error: "Calendar not found" (404)

1. Verifica el `GOOGLE_CALENDAR_ID`
2. Asegúrate de que el calendario es accesible para la cuenta OAuth
3. Si es un calendario compartido, acepta la invitación

### No se muestran eventos

1. Verifica que el calendario tiene eventos
2. Comprueba el rango de fechas (por defecto: hoy + 6 meses)
3. Mira los logs del servidor

### Token expirado frecuentemente

- El token se refresca automáticamente si tiene `refresh_token`
- Si el problema persiste, regenera el token completamente

## Seguridad

- Las credenciales están encriptadas con Fernet
- El token se almacena de forma segura
- Solo lectura de eventos (no escritura)
- No se expone información sensible en el frontend

## Mantenimiento

### Renovar Token (si caduca)

1. Ejecuta localmente: `flask regenerate-google-token`
2. Encripta el nuevo token
3. Actualiza en Render

### Cambiar de Calendario

1. Actualiza `GOOGLE_CALENDAR_ID` en Render
2. Limpia la cache: POST a `/api/calendario/limpiar-cache`

---

## Contacto

Para problemas con la integración, contacta al administrador técnico del AMPA.
