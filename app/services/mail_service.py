"""
Servicio de correo electrónico para la web del AMPA.

Toda la gestión de envío se realiza mediante Gmail API (OAuth 2.0).
Reutiliza el token OAuth unificado (Drive/Calendar/Gmail) configurado con:
- GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON / GOOGLE_DRIVE_OAUTH_CREDENTIALS_FILE
- GOOGLE_DRIVE_TOKEN_JSON (debe incluir refresh_token)
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr
from typing import Any

from flask import current_app, render_template, url_for
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.services.calendar_service import get_unified_credentials

_gmail_service = None


def get_gmail_service():
    """
    Devuelve un cliente de Gmail API autenticado como usuario ("me").

    La obtención/refresco de credenciales se delega a calendar_service.get_unified_credentials()
    para reutilizar el patrón existente (token JSON en env + refresh automático).
    """
    global _gmail_service

    creds = get_unified_credentials()
    if not creds:
        return None

    if _gmail_service is None:
        # cache_discovery=False evita escrituras en disco de discovery cache.
        _gmail_service = build(
            "gmail",
            "v1",
            credentials=creds,
            cache_discovery=False,
            static_discovery=True,
        )
    return _gmail_service


def _extract_http_error_details(error: HttpError) -> tuple[int | None, str]:
    status = getattr(getattr(error, "resp", None), "status", None)
    reason = getattr(getattr(error, "resp", None), "reason", None)

    message = None
    error_reason = None
    try:
        raw = getattr(error, "content", b"") or b""
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        err = payload.get("error", {}) if isinstance(payload, dict) else {}
        message = err.get("message")
        errors = err.get("errors") or []
        if isinstance(errors, list) and errors:
            first = errors[0] if isinstance(errors[0], dict) else {}
            error_reason = first.get("reason")
    except Exception:
        pass

    parts: list[str] = []
    if status:
        parts.append(f"HTTP {status}")
    if error_reason:
        parts.append(str(error_reason))
    if reason and str(reason) not in parts:
        parts.append(str(reason))
    if message:
        parts.append(str(message))

    return status, " - ".join(parts) if parts else str(error)


def _validate_email_header(value: str, *, field_name: str) -> tuple[bool, str]:
    _name, addr = parseaddr(value or "")
    if not addr or "@" not in addr:
        return False, f"{field_name} inválido o vacío"
    return True, ""



def _build_web_subject(base_subject: str, *, section: str, category: str) -> str:
    parts = ["WEB-AMPA", section, category]
    prefix = " / ".join([part.strip() for part in parts if (part or "").strip()])
    base = (base_subject or "").strip()
    if base and prefix:
        return f"{prefix} - {base}"
    return base or prefix

def send_email_gmail_api(
    *,
    subject: str,
    body_text: str,
    recipient: str | list[str] | tuple[str, ...],
    app_config: Any,
    sender: str | None = None,
    reply_to: str | None = None,
    body_html: str | None = None,
    inline_images: list[dict[str, str]] | None = None,
    attachments: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    Envía un correo usando Gmail API (RFC822 raw).
    
    Args:
        attachments: Lista de diccionarios con 'data' (bytes o str), 'filename', 'maintype', 'subtype'

    Returns:
        {"ok": bool, "provider": "gmail_api", "id": str|None, "error": str|None}
    """
    provider = "gmail_api"

    try:
        sender_header = (sender or app_config.get("MAIL_DEFAULT_SENDER") or "").strip()
        if not sender_header:
            current_app.logger.error("No se puede enviar correo: falta MAIL_DEFAULT_SENDER (remitente).")
            return {
                "ok": False,
                "provider": provider,
                "id": None,
                "error": "Falta MAIL_DEFAULT_SENDER (remitente) para enviar correos.",
            }

        ok_from, from_err = _validate_email_header(sender_header, field_name="From")
        if not ok_from:
            current_app.logger.error("No se puede enviar correo: %s.", from_err)
            return {"ok": False, "provider": provider, "id": None, "error": from_err}

        if reply_to:
            ok_reply, reply_err = _validate_email_header(reply_to, field_name="Reply-To")
            if not ok_reply:
                current_app.logger.error("No se puede enviar correo: %s.", reply_err)
                return {"ok": False, "provider": provider, "id": None, "error": reply_err}

        if isinstance(recipient, str):
            to_header = recipient.strip()
            recipients_for_validation = [to_header]
        else:
            recipients_for_validation = [r.strip() for r in recipient if str(r).strip()]
            to_header = ", ".join(recipients_for_validation)

        if not to_header:
            current_app.logger.error("No se puede enviar correo: destinatario vacío.")
            return {"ok": False, "provider": provider, "id": None, "error": "Destinatario vacío."}

        parsed_recipients = [addr for _name, addr in getaddresses(recipients_for_validation) if addr]
        if not parsed_recipients:
            current_app.logger.error("No se puede enviar correo: destinatario inválido.")
            return {"ok": False, "provider": provider, "id": None, "error": "Destinatario inválido."}

        msg = EmailMessage()
        msg["From"] = sender_header
        msg["To"] = to_header
        msg["Subject"] = subject or ""
        if reply_to:
            msg["Reply-To"] = reply_to

        msg.set_content(body_text or "", subtype="plain", charset="utf-8")
        if body_html:
            msg.add_alternative(body_html, subtype="html", charset="utf-8")
            if inline_images:
                for img in inline_images:
                    try:
                        with open(img["path"], "rb") as f:
                            img_data = f.read()
                        msg.get_payload()[1].add_related(
                            img_data,
                            maintype="image",
                            subtype=img.get("subtype", "png"),
                            cid=f'<{img["cid"]}>',
                        )
                    except Exception as e:
                        current_app.logger.error(f"Error adjuntando imagen inline {img.get('path')}: {e}")
        
        # Añadir adjuntos generales (ej: archivos .ics)
        if attachments:
            for attachment in attachments:
                try:
                    data = attachment.get("data")
                    if isinstance(data, str):
                        data = data.encode("utf-8")
                    
                    msg.add_attachment(
                        data,
                        maintype=attachment.get("maintype", "application"),
                        subtype=attachment.get("subtype", "octet-stream"),
                        filename=attachment.get("filename", "attachment")
                    )
                except Exception as e:
                    current_app.logger.error(f"Error adjuntando archivo {attachment.get('filename')}: {e}")

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

        service = get_gmail_service()
        if service is None:
            current_app.logger.error("No se pudo inicializar Gmail API para enviar correo.")
            return {
                "ok": False,
                "provider": provider,
                "id": None,
                "error": (
                    "No se pudo inicializar Gmail API. Revisa GOOGLE_DRIVE_TOKEN_JSON "
                    "(refresh_token + scopes unificados) y GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON/FILE."
                ),
            }

        response = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )

        return {
            "ok": True,
            "provider": provider,
            "id": response.get("id"),
            "error": None,
        }

    except HttpError as exc:
        status, detail = _extract_http_error_details(exc)
        hint = ""
        if status == 403 and ("insufficientPermissions" in detail or "permission" in detail.lower()):
            hint = (
                " (Faltan permisos: asegúrate de incluir el scope "
                "'https://www.googleapis.com/auth/gmail.send' en el token.)"
            )
        if status == 400 and ("From" in detail or "from" in detail.lower()):
            hint = (
                " (Revisa MAIL_DEFAULT_SENDER: debe ser el email autenticado o un alias 'Send as' "
                "válido en Gmail.)"
            )

        current_app.logger.error("Error Gmail API enviando correo: %s%s", detail, hint)
        return {"ok": False, "provider": provider, "id": None, "error": f"{detail}{hint}"}

    except RefreshError as exc:
        current_app.logger.error(
            "Error refrescando credenciales OAuth al enviar correo (posible invalid_grant): %s",
            exc,
        )
        return {
            "ok": False,
            "provider": provider,
            "id": None,
            "error": (
                "Error de credenciales OAuth (posible token revocado/invalid_grant). "
                "Regenera GOOGLE_DRIVE_TOKEN_JSON con 'flask regenerate-google-token'."
            ),
        }

    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Error inesperado enviando correo por Gmail API", exc_info=exc)
        return {"ok": False, "provider": provider, "id": None, "error": f"Error inesperado: {type(exc).__name__}"}


def send_contact_email(datos_contacto: dict[str, str], app_config: Any) -> dict[str, Any]:
    """
    Envía un correo electrónico desde el formulario de contacto.
    """
    nombre = (datos_contacto.get("nombre") or "").strip()
    email_remitente = (datos_contacto.get("email") or "").strip()
    asunto_formulario = (datos_contacto.get("asunto") or "").strip()
    mensaje_texto = (datos_contacto.get("mensaje") or "").strip()

    mail_contact_recipient = (app_config.get("MAIL_CONTACT_RECIPIENT") or "").strip()
    if not mail_contact_recipient:
        mail_contact_recipient = (app_config.get("MAIL_AMPA_RECIPIENT") or "").strip()
    if not mail_contact_recipient:
        mail_contact_recipient = (app_config.get("MAIL_DEFAULT_SENDER") or "").strip()

    fecha_envio = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    body_text = (
        "Nuevo mensaje de contacto recibido desde la web del AMPA:\n\n"
        "----------------------------------------\n"
        "DATOS DEL REMITENTE\n"
        "----------------------------------------\n\n"
        f"Nombre:  {nombre}\n"
        f"Email:   {email_remitente}\n"
        f"Asunto:  {asunto_formulario}\n"
        f"Fecha:   {fecha_envio}\n\n"
        "----------------------------------------\n"
        "MENSAJE\n"
        "----------------------------------------\n\n"
        f"{mensaje_texto}\n\n"
        "----------------------------------------\n\n"
        "Para responder, pulsa \"Responder\" y tu respuesta llegará a:\n"
        f"{email_remitente}\n"
    )

    base_subject = " - ".join([part for part in [asunto_formulario, nombre] if part])
    subject = _build_web_subject(base_subject, section="Contacto", category="Formulario")

    return send_email_gmail_api(
        subject=subject,
        body_text=body_text,
        recipient=mail_contact_recipient,
        reply_to=email_remitente or None,
        app_config=app_config,
    )


def send_member_verification_email(
    *,
    recipient_email: str,
    verify_url: str,
    app_config: Any,
) -> dict[str, Any]:
    subject = _build_web_subject("Verifica tu correo", section="Registro", category="Verificacion")

    # Ruta física del logo para incrustarlo (CID)
    logo_path = os.path.join(current_app.static_folder, "images/current/Logo_AMPA_400x400.png")
    
    # Renderizar HTML usando el CID para la imagen
    body_html = render_template(
        "email/verification.html",
        verify_url=verify_url,
        logo_url="cid:logo_ampa"
    )

    # Definir la imagen inline
    inline_images = [
        {
            "cid": "logo_ampa",
            "path": logo_path,
            "subtype": "png"
        }
    ]

    # Texto plano como fallback
    body_text = (
        "Hola,\n\n"
        "Para completar tu alta como socio/a, verifica tu correo usando este enlace:\n\n"
        f"{verify_url}\n\n"
        "Si no has solicitado el alta, puedes ignorar este mensaje.\n"
    )
    return send_email_gmail_api(
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        inline_images=inline_images,
        recipient=recipient_email,
        app_config=app_config,
    )


def send_member_deactivation_email(
    *,
    recipient_email: str,
    app_config: Any,
) -> dict[str, Any]:
    subject = _build_web_subject(
        "Aviso: Tu cuenta ha sido desactivada",
        section="Administracion",
        category="Desactivacion",
    )
    
    logo_path = os.path.join(current_app.static_folder, "images/current/Logo_AMPA_400x400.png")
    
    body_html = render_template("email/deactivation.html")

    inline_images = [
        {
            "cid": "logo_ampa",
            "path": logo_path,
            "subtype": "png"
        }
    ]

    body_text = (
        "Hola,\n\n"
        "Tu cuenta en el AMPA Julián Nieto ha sido desactivada manualmente.\n"
        "Si crees que es un error, contacta con nosotros para reactivarla.\n\n"
        "Importante: Las cuentas inactivas por más de 30 días serán eliminadas automáticamente."
    )
    return send_email_gmail_api(
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        inline_images=inline_images,
        recipient=recipient_email,
        app_config=app_config,
    )


def send_member_reactivation_email(
    *,
    recipient_email: str,
    app_config: Any,
) -> dict[str, Any]:
    subject = _build_web_subject(
        "Tu cuenta ha sido reactivada",
        section="Administracion",
        category="Reactivacion",
    )
    
    logo_path = os.path.join(current_app.static_folder, "images/current/Logo_AMPA_400x400.png")
    login_url = url_for("public.home", _external=True)

    body_html = render_template(
        "email/reactivation.html",
        login_url=login_url
    )

    inline_images = [
        {
            "cid": "logo_ampa",
            "path": logo_path,
            "subtype": "png"
        }
    ]

    body_text = (
        "¡Hola!\n\n"
        "Tu cuenta en el AMPA Julián Nieto ha sido reactivada. Ya puedes volver a acceder:\n\n"
        f"{login_url}"
    )
    return send_email_gmail_api(
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        inline_images=inline_images,
        recipient=recipient_email,
        app_config=app_config,
    )


def send_new_member_registration_notification_to_ampa(
    *,
    member_name: str,
    member_email: str,
    member_phone: str | None,
    app_config: Any,
) -> dict[str, Any]:
    recipient = (
        (app_config.get("MAIL_AMPA_RECIPIENT") or "").strip()
        or (app_config.get("MAIL_CONTACT_RECIPIENT") or "").strip()
        or (app_config.get("MAIL_DEFAULT_SENDER") or "").strip()
    )
    subject = _build_web_subject(
        "Nuevo registro de Socio",
        section="Registro",
        category="Nuevo socio",
    )
    phone_line = member_phone.strip() if member_phone else ""
    body = (
        "Nuevo registro público de socio/a:\n\n"
        f"Nombre: {member_name}\n"
        f"Email: {member_email}\n"
        f"Teléfono: {phone_line or '(no informado)'}\n\n"
        "Accede al panel de administración para revisar y aprobar el alta.\n"
    )
    return send_email_gmail_api(
        subject=subject,
        body_text=body,
        recipient=recipient,
        app_config=app_config,
    )


def send_member_approval_email(
    *,
    recipient_email: str,
    app_config: Any,
) -> dict[str, Any]:
    subject = _build_web_subject(
        "Tu alta ha sido aprobada!",
        section="Registro",
        category="Aprobacion",
    )
    
    # Ruta física del logo para incrustarlo (CID)
    logo_path = os.path.join(current_app.static_folder, "images/current/Logo_AMPA_400x400.png")
    
    # URL de login
    login_url = url_for("public.home", _external=True)

    # Renderizar HTML
    body_html = render_template(
        "email/approval.html",
        login_url=login_url
    )

    # Definir la imagen inline
    inline_images = [
        {
            "cid": "logo_ampa",
            "path": logo_path,
            "subtype": "png"
        }
    ]

    # Texto plano como fallback
    body_text = (
        "¡Hola!\n\n"
        "Tu alta en el AMPA Julián Nieto ha sido aprobada. Ya puedes acceder a tu cuenta:\n\n"
        f"{login_url}\n\n"
        "¡Bienvenido/a!"
    )
    return send_email_gmail_api(
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        inline_images=inline_images,
        recipient=recipient_email,
        app_config=app_config,
    )


def _detect_email_provider(email: str) -> str:
    """
    Detecta el proveedor de correo basándose en el dominio del email.
    
    Retorna: 'google', 'outlook', 'yahoo', 'apple' u 'other'
    """
    if not email or "@" not in email:
        return "other"
    
    domain = email.split("@")[1].lower()
    
    # Dominios de Google
    if domain in ["gmail.com", "googlemail.com"]:
        return "google"
    
    # Dominios de Microsoft/Outlook
    if domain in ["outlook.com", "hotmail.com", "live.com", "msn.com", "hotmail.es", "outlook.es"]:
        return "outlook"
    
    # Dominios de Yahoo
    if domain in ["yahoo.com", "yahoo.es", "ymail.com"]:
        return "yahoo"
    
    # Dominios de Apple
    if domain in ["icloud.com", "me.com", "mac.com"]:
        return "apple"
    
    return "other"


def _generate_google_calendar_url(
    title: str,
    start_datetime,
    end_datetime,
    description: str = "",
    location: str = ""
) -> str:
    """
    Genera un enlace para agregar un evento a Google Calendar.
    
    Formato: https://calendar.google.com/calendar/render?action=TEMPLATE&text=...&dates=...
    """
    from urllib.parse import quote
    
    # Formatear fechas en formato YYYYMMDDTHHMMSSZ (UTC) o YYYYMMDDTHHMMSS (local)
    start_str = start_datetime.strftime("%Y%m%dT%H%M%S")
    end_str = end_datetime.strftime("%Y%m%dT%H%M%S")
    
    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{start_str}/{end_str}",
    }
    
    if description:
        params["details"] = description
    
    if location:
        params["location"] = location
    
    # Construir URL manualmente
    base_url = "https://calendar.google.com/calendar/render"
    query_parts = [f"{key}={quote(str(value))}" for key, value in params.items()]
    return f"{base_url}?{'&'.join(query_parts)}"


def _generate_outlook_calendar_url(
    title: str,
    start_datetime,
    end_datetime,
    description: str = "",
    location: str = ""
) -> str:
    """
    Genera un enlace para agregar un evento a Outlook Calendar.
    
    Formato: https://outlook.live.com/calendar/0/deeplink/compose?...
    """
    from urllib.parse import quote
    
    # Outlook usa ISO 8601
    start_str = start_datetime.strftime("%Y-%m-%dT%H:%M:%S")
    end_str = end_datetime.strftime("%Y-%m-%dT%H:%M:%S")
    
    params = {
        "subject": title,
        "startdt": start_str,
        "enddt": end_str,
        "path": "/calendar/action/compose",
        "rru": "addevent"
    }
    
    if description:
        params["body"] = description
    
    if location:
        params["location"] = location
    
    base_url = "https://outlook.live.com/calendar/0/deeplink/compose"
    query_parts = [f"{key}={quote(str(value))}" for key, value in params.items()]
    return f"{base_url}?{'&'.join(query_parts)}"


def _generate_yahoo_calendar_url(
    title: str,
    start_datetime,
    end_datetime,
    description: str = "",
    location: str = ""
) -> str:
    """
    Genera un enlace para agregar un evento a Yahoo Calendar.
    """
    from urllib.parse import quote
    
    start_str = start_datetime.strftime("%Y%m%dT%H%M%S")
    end_str = end_datetime.strftime("%Y%m%dT%H%M%S")
    
    params = {
        "v": "60",
        "title": title,
        "st": start_str,
        "et": end_str,
    }
    
    if description:
        params["desc"] = description
    
    if location:
        params["in_loc"] = location
    
    base_url = "https://calendar.yahoo.com/"
    query_parts = [f"{key}={quote(str(value))}" for key, value in params.items()]
    return f"{base_url}?{'&'.join(query_parts)}"


def _generate_ics_calendar_data(
    title: str,
    start_datetime,
    end_datetime,
    description: str = "",
    location: str = "",
    uid: str = "",
    sequence: int = 0,
    method: str = "REQUEST"
) -> str:
    """
    Genera datos iCalendar (.ics) compatibles con RFC 5545.
    
    Args:
        title: Título del evento
        start_datetime: Fecha y hora de inicio
        end_datetime: Fecha y hora de fin
        description: Descripción (puede incluir HTML, se limpiará)
        location: Ubicación del evento
        uid: UID único del evento (si no se proporciona, se genera uno)
        sequence: Número de secuencia (incrementa con cada actualización)
        method: Método iCalendar (REQUEST para invitación, CANCEL para cancelación)
    
    Returns:
        Contenido del archivo .ics como string
    """
    from datetime import datetime
    from html import unescape
    import re
    
    # Limpiar HTML de la descripción
    description_clean = re.sub(r'<[^>]+>', '', description)
    description_clean = unescape(description_clean)
    
    # Formato iCalendar: YYYYMMDDTHHMMSS
    start_str = start_datetime.strftime("%Y%m%dT%H%M%S")
    end_str = end_datetime.strftime("%Y%m%dT%H%M%S")
    now_str = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    
    # Generar UID único si no se proporciona
    uid_str = uid or f"meeting-{hash(title)}-{start_str}@ampajuliannieto.es"
    
    # Escapar caracteres especiales en iCalendar
    def escape_ics(text):
        return text.replace('\\', '\\\\').replace(',', '\\,').replace(';', '\\;').replace('\n', '\\n')
    
    title_escaped = escape_ics(title)
    description_escaped = escape_ics(description_clean)
    location_escaped = escape_ics(location)
    
    # Construir contenido iCalendar
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//AMPA Julian Nieto Tapia//Meeting Notification//ES",
        "CALSCALE:GREGORIAN",
        f"METHOD:{method}",
        "BEGIN:VEVENT",
        f"UID:{uid_str}",
        f"DTSTAMP:{now_str}",
        f"DTSTART:{start_str}",
        f"DTEND:{end_str}",
        f"SUMMARY:{title_escaped}",
    ]
    
    if description_escaped:
        ics_lines.append(f"DESCRIPTION:{description_escaped}")
    
    if location_escaped:
        ics_lines.append(f"LOCATION:{location_escaped}")
    
    ics_lines.extend([
        "STATUS:CONFIRMED",
        f"SEQUENCE:{sequence}",
        "TRANSP:OPAQUE",
        "END:VEVENT",
        "END:VCALENDAR"
    ])
    
    return "\r\n".join(ics_lines)


def send_meeting_notification(
    *,
    meeting,
    commission,
    recipient_email: str,
    recipient_name: str,
    app_config: Any,
    is_update: bool = False,
) -> dict[str, Any]:
    """
    Envía una notificación por correo sobre una nueva reunión de comisión.
    
    Args:
        meeting: Objeto CommissionMeeting
        commission: Objeto Commission
        recipient_email: Email del destinatario
        recipient_name: Nombre del destinatario
        app_config: Configuración de la aplicación
        is_update: Si es una actualización (incrementa SEQUENCE en .ics)
    
    Returns:
        dict con 'ok' (bool) y 'error' (str) si corresponde
    """
    commission_name = getattr(commission, "name", "Comisión")
    meeting_title = getattr(meeting, "title", "Reunión")
    meeting_description = getattr(meeting, "description_html", "")
    meeting_location = getattr(meeting, "location", "")
    start_at = getattr(meeting, "start_at", None)
    end_at = getattr(meeting, "end_at", None)
    meeting_id = getattr(meeting, "id", None)
    
    if not start_at or not end_at:
        return {"ok": False, "error": "Fechas de reunión no válidas"}
    
    # Formatear fecha y hora para mostrar
    meeting_date = start_at.strftime("%d/%m/%Y")
    meeting_time = f"{start_at.strftime('%H:%M')} - {end_at.strftime('%H:%M')}"
    
    # Generar UID único consistente basado en el ID de la reunión
    # Esto permite que las actualizaciones se sincronicen correctamente
    meeting_uid = f"commission-meeting-{meeting_id}@ampajuliannieto.es" if meeting_id else None
    
    # Generar archivo iCalendar (.ics)
    sequence = 1 if is_update else 0
    ics_content = _generate_ics_calendar_data(
        title=meeting_title,
        start_datetime=start_at,
        end_datetime=end_at,
        description=meeting_description,
        location=meeting_location,
        uid=meeting_uid,
        sequence=sequence,
        method="REQUEST"
    )
    
    # Detectar el proveedor de correo
    provider = _detect_email_provider(recipient_email)
    
    # Generar URLs de calendario (como alternativa al archivo .ics)
    google_url = _generate_google_calendar_url(
        meeting_title, start_at, end_at, meeting_description, meeting_location
    )
    outlook_url = _generate_outlook_calendar_url(
        meeting_title, start_at, end_at, meeting_description, meeting_location
    )
    yahoo_url = _generate_yahoo_calendar_url(
        meeting_title, start_at, end_at, meeting_description, meeting_location
    )
    
    # URL principal según el proveedor
    calendar_url = google_url  # Por defecto Google
    if provider == "outlook":
        calendar_url = outlook_url
    elif provider == "yahoo":
        calendar_url = yahoo_url
    elif provider == "apple":
        calendar_url = google_url
    
    # Información del proyecto si existe
    project = getattr(meeting, "project", None)
    project_title = getattr(project, "title", None) if project else None
    
    # Asunto del correo
    subject = _build_web_subject(
        meeting_title,
        section="Comisiones",
        category="Actualización de Reunión" if is_update else "Nueva Reunión",
    )
    
    # Ruta física del logo para incrustarlo (CID)
    logo_path = os.path.join(current_app.static_folder, "images/current/Logo_AMPA_400x400.png")
    
    # Renderizar HTML
    body_html = render_template(
        "email/meeting_notification.html",
        recipient_name=recipient_name,
        commission_name=commission_name,
        project_title=project_title,
        meeting_title=meeting_title,
        meeting_description=meeting_description,
        meeting_date=meeting_date,
        meeting_time=meeting_time,
        meeting_location=meeting_location,
        calendar_url=calendar_url,
        google_calendar_url=google_url,
        outlook_calendar_url=outlook_url,
        apple_calendar_url=google_url,
        is_update=is_update,
    )
    
    # Definir la imagen inline
    inline_images = [
        {
            "cid": "logo_ampa",
            "path": logo_path,
            "subtype": "png"
        }
    ]
    
    # Texto plano como fallback
    update_text = "Se ha actualizado" if is_update else "Se ha programado"
    body_text = (
        f"Hola {recipient_name},\n\n"
        f"{update_text} una reunión para {commission_name}.\n\n"
        f"Título: {meeting_title}\n"
        f"Fecha: {meeting_date}\n"
        f"Hora: {meeting_time}\n"
    )
    
    if meeting_location:
        body_text += f"Ubicación: {meeting_location}\n"
    
    body_text += (
        f"\nSe adjunta un archivo de calendario (.ics) que puedes abrir para añadir "
        f"o actualizar automáticamente el evento en tu calendario.\n\n"
        f"También puedes añadirlo manualmente: {calendar_url}\n"
    )
    
    # Preparar archivo .ics como adjunto
    attachments = [
        {
            "data": ics_content,
            "filename": f"reunion-{meeting_id}.ics" if meeting_id else "reunion.ics",
            "maintype": "text",
            "subtype": "calendar"
        }
    ]
    
    return send_email_gmail_api(
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        inline_images=inline_images,
        attachments=attachments,
        recipient=recipient_email,
        app_config=app_config,
    )


def send_meeting_cancellation_notification(
    *,
    meeting,
    commission,
    recipient_email: str,
    recipient_name: str,
    app_config: Any,
) -> dict[str, Any]:
    """
    Envía una notificación por correo sobre la cancelación de una reunión.
    
    Args:
        meeting: Objeto CommissionMeeting
        commission: Objeto Commission
        recipient_email: Email del destinatario
        recipient_name: Nombre del destinatario
        app_config: Configuración de la aplicación
    
    Returns:
        dict con 'ok' (bool) y 'error' (str) si corresponde
    """
    commission_name = getattr(commission, "name", "Comisión")
    meeting_title = getattr(meeting, "title", "Reunión")
    meeting_description = getattr(meeting, "description_html", "")
    meeting_location = getattr(meeting, "location", "")
    start_at = getattr(meeting, "start_at", None)
    end_at = getattr(meeting, "end_at", None)
    meeting_id = getattr(meeting, "id", None)
    
    if not start_at or not end_at:
        return {"ok": False, "error": "Fechas de reunión no válidas"}
    
    # Formatear fecha y hora para mostrar
    meeting_date = start_at.strftime("%d/%m/%Y")
    meeting_time = f"{start_at.strftime('%H:%M')} - {end_at.strftime('%H:%M')}"
    
    # Generar UID único consistente basado en el ID de la reunión
    # Debe ser el MISMO UID que se usó al crear/actualizar para que se cancele correctamente
    meeting_uid = f"commission-meeting-{meeting_id}@ampajuliannieto.es" if meeting_id else None
    
    # Generar archivo iCalendar (.ics) con METHOD:CANCEL
    # SEQUENCE debe ser mayor que cualquier actualización previa
    ics_content = _generate_ics_calendar_data(
        title=meeting_title,
        start_datetime=start_at,
        end_datetime=end_at,
        description=meeting_description,
        location=meeting_location,
        uid=meeting_uid,
        sequence=99,  # Alto número para asegurar que se aplique la cancelación
        method="CANCEL"
    )
    
    # Información del proyecto si existe
    project = getattr(meeting, "project", None)
    project_title = getattr(project, "title", None) if project else None
    
    # Asunto del correo
    subject = _build_web_subject(
        meeting_title,
        section="Comisiones",
        category="Cancelación de Reunión",
    )
    
    # Ruta física del logo para incrustarlo (CID)
    logo_path = os.path.join(current_app.static_folder, "images/current/Logo_AMPA_400x400.png")
    
    # Renderizar HTML
    body_html = render_template(
        "email/meeting_cancellation.html",
        recipient_name=recipient_name,
        commission_name=commission_name,
        project_title=project_title,
        meeting_title=meeting_title,
        meeting_description=meeting_description,
        meeting_date=meeting_date,
        meeting_time=meeting_time,
        meeting_location=meeting_location,
    )
    
    # Definir la imagen inline
    inline_images = [
        {
            "cid": "logo_ampa",
            "path": logo_path,
            "subtype": "png"
        }
    ]
    
    # Texto plano como fallback
    body_text = (
        f"Hola {recipient_name},\n\n"
        f"Se ha cancelado la siguiente reunión de {commission_name}:\n\n"
        f"Título: {meeting_title}\n"
        f"Fecha: {meeting_date}\n"
        f"Hora: {meeting_time}\n"
    )
    
    if meeting_location:
        body_text += f"Ubicación: {meeting_location}\n"
    
    body_text += (
        f"\nSe adjunta un archivo de calendario (.ics) que puedes abrir para eliminar "
        f"automáticamente el evento de tu calendario.\n\n"
        f"Si añadiste el evento manualmente, por favor elimínalo de tu calendario.\n"
    )
    
    # Preparar archivo .ics como adjunto
    attachments = [
        {
            "data": ics_content,
            "filename": f"cancelacion-reunion-{meeting_id}.ics" if meeting_id else "cancelacion-reunion.ics",
            "maintype": "text",
            "subtype": "calendar"
        }
    ]
    
    return send_email_gmail_api(
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        inline_images=inline_images,
        attachments=attachments,
        recipient=recipient_email,
        app_config=app_config,
    )
