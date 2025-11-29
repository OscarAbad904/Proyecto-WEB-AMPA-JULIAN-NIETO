# Configuración de Carpetas en Google Drive

## ¿Cómo obtener los IDs de las carpetas?

Tienes **2 opciones**:

### Opción A: Automática (Recomendado)

Ejecuta el comando CLI que crea las carpetas automáticamente y te devuelve los IDs:

```bash
flask setup-drive-folders
```

Este comando:
1. Se conecta a Google Drive usando OAuth
2. Busca las carpetas "Noticias", "Eventos" y "Documentos"
3. Si no existen, las crea
4. Te muestra los IDs para que los copies a `.env`

**Resultado esperado:**
```
📁 Setting up Google Drive folders...

✅ Noticias: 1n_bnmk6DEmjJ80gpZ2sOsje_koOkGk1Y
   Add to .env: GOOGLE_DRIVE_NEWS_FOLDER_ID=1n_bnmk6DEmjJ80gpZ2sOsje_koOkGk1Y

✅ Eventos: 1aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567
   Add to .env: GOOGLE_DRIVE_EVENTS_FOLDER_ID=1aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567

✅ Documentos: 2xYzAbCdEfGhIjKlMnOpQrStUvWxYz890123
   Add to .env: GOOGLE_DRIVE_DOCS_FOLDER_ID=2xYzAbCdEfGhIjKlMnOpQrStUvWxYz890123
```

Luego copias estos IDs a tu `.env`:

```dotenv
GOOGLE_DRIVE_NEWS_FOLDER_ID=1n_bnmk6DEmjJ80gpZ2sOsje_koOkGk1Y
GOOGLE_DRIVE_EVENTS_FOLDER_ID=1aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567
GOOGLE_DRIVE_DOCS_FOLDER_ID=2xYzAbCdEfGhIjKlMnOpQrStUvWxYz890123
```

### Opción B: Manual

1. Ve a [Google Drive](https://drive.google.com)
2. Crea las carpetas si no existen: "Noticias", "Eventos", "Documentos"
3. Abre cada carpeta
4. Mira en la URL del navegador: `https://drive.google.com/drive/folders/XXXXXXXXX`
5. El ID es lo que está después de `/folders/`

Ejemplo:
- URL: `https://drive.google.com/drive/folders/1n_bnmk6DEmjJ80gpZ2sOsje_koOkGk1Y`
- ID: `1n_bnmk6DEmjJ80gpZ2sOsje_koOkGk1Y`

## Variables de entorno

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `GOOGLE_DRIVE_NEWS_FOLDER_ID` | ID de la carpeta de Noticias | `1n_bnmk6DEmjJ80gpZ2sOsje_koOkGk1Y` |
| `GOOGLE_DRIVE_NEWS_FOLDER_NAME` | Nombre de la carpeta (para buscar si no existe ID) | `Noticias` |
| `GOOGLE_DRIVE_EVENTS_FOLDER_ID` | ID de la carpeta de Eventos | `1aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567` |
| `GOOGLE_DRIVE_EVENTS_FOLDER_NAME` | Nombre de la carpeta de Eventos | `Eventos` |
| `GOOGLE_DRIVE_DOCS_FOLDER_ID` | ID de la carpeta de Documentos | `2xYzAbCdEfGhIjKlMnOpQrStUvWxYz890123` |
| `GOOGLE_DRIVE_DOCS_FOLDER_NAME` | Nombre de la carpeta de Documentos | `Documentos` |
| `GOOGLE_DRIVE_SHARED_DRIVE_ID` | (Opcional) ID de Shared Drive si usas uno | (vacío si no) |

## ¿Cómo funciona?

En tu aplicación:
- Si el ID está en `.env`, se usa directamente
- Si no hay ID pero hay nombre de carpeta, la API busca la carpeta por nombre
- Si la carpeta no existe, se crea automáticamente

## Ejemplo de flujo

1. **Primera ejecución sin IDs:**
   - `.env` tiene `GOOGLE_DRIVE_NEWS_FOLDER_ID=` (vacío)
   - `.env` tiene `GOOGLE_DRIVE_NEWS_FOLDER_NAME=Noticias`
   - La API busca una carpeta llamada "Noticias"
   - Si no existe, la crea
   - El ID se usa internamente pero NO se guarda en `.env` automáticamente

2. **Con IDs configurados:**
   - `.env` tiene `GOOGLE_DRIVE_NEWS_FOLDER_ID=1n_bnmk6DEmjJ80gpZ2sOsje_koOkGk1Y`
   - La API usa directamente este ID sin buscar
   - Es más eficiente (menos llamadas a Google Drive API)

## En Render

En producción, debes:
1. Ejecutar el comando `flask setup-drive-folders` localmente
2. Copiar los IDs que aparezcan
3. Agregarlos a las variables de entorno en Render dashboard
