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
from datetime import datetime
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr
from typing import Any

from flask import current_app
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


def send_email_gmail_api(
    *,
    subject: str,
    body_text: str,
    recipient: str | list[str] | tuple[str, ...],
    app_config: Any,
    sender: str | None = None,
    reply_to: str | None = None,
    body_html: str | None = None,
) -> dict[str, Any]:
    """
    Envía un correo usando Gmail API (RFC822 raw).

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

    subject = f"[Web AMPA] {asunto_formulario} - {nombre}".strip()

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
    subject = "Verifica tu correo"
    body = (
        "Hola,\n\n"
        "Para completar tu alta como socio/a, verifica tu correo usando este enlace:\n\n"
        f"{verify_url}\n\n"
        "Si no has solicitado el alta, puedes ignorar este mensaje.\n"
    )
    return send_email_gmail_api(
        subject=subject,
        body_text=body,
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
    subject = "Nuevo registro de Socio"
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


def send_set_password_email(
    *,
    recipient_email: str,
    set_password_url: str,
    app_config: Any,
) -> dict[str, Any]:
    subject = "Establece tu contraseña"
    body = (
        "Hola,\n\n"
        "Tu alta ha sido aprobada. Para acceder al área de socios, establece tu contraseña aquí:\n\n"
        f"{set_password_url}\n\n"
        "Este enlace caduca. Si no has solicitado el alta, puedes ignorar este mensaje.\n"
    )
    return send_email_gmail_api(
        subject=subject,
        body_text=body,
        recipient=recipient_email,
        app_config=app_config,
    )
