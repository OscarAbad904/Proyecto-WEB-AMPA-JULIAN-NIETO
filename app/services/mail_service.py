"""Servicio de correo electrónico para el AMPA.

Este módulo proporciona funcionalidades para enviar correos electrónicos
utilizando SMTP de Gmail con contraseña de aplicación.
"""

import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Dict, Any


def _send_plain_email(
    *,
    subject: str,
    body: str,
    recipient: str,
    app_config: Any,
    reply_to: str | None = None,
) -> Dict[str, Any]:
    try:
        mail_server = app_config.get("MAIL_SERVER")
        mail_port = app_config.get("MAIL_PORT")
        mail_use_tls = app_config.get("MAIL_USE_TLS")
        mail_username = app_config.get("MAIL_USERNAME")
        mail_password = app_config.get("MAIL_PASSWORD")
        mail_default_sender = app_config.get("MAIL_DEFAULT_SENDER") or mail_username

        if not all([mail_server, mail_port, mail_username, mail_password, recipient]):
            return {"ok": False, "error": "Configuración de correo incompleta"}

        msg = MIMEMultipart()
        msg["From"] = mail_default_sender
        msg["To"] = recipient
        msg["Subject"] = subject
        if reply_to:
            msg["Reply-To"] = reply_to
        msg.attach(MIMEText(body, "plain", "utf-8"))

        ssl_context = ssl.create_default_context()
        if not mail_use_tls and int(mail_port) == 465:
            with smtplib.SMTP_SSL(mail_server, int(mail_port), context=ssl_context) as server:
                server.login(mail_username, mail_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(mail_server, int(mail_port)) as server:
                if mail_use_tls:
                    server.starttls(context=ssl_context)
                server.login(mail_username, mail_password)
                server.send_message(msg)

        return {"ok": True}

    except smtplib.SMTPAuthenticationError:
        return {
            "ok": False,
            "error": "Error de autenticación SMTP. Verifica MAIL_USERNAME y MAIL_PASSWORD",
        }

    except smtplib.SMTPException as exc:
        return {"ok": False, "error": f"Error al enviar correo: {type(exc).__name__}"}

    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Error inesperado: {type(exc).__name__}"}


def send_contact_email(datos_contacto: Dict[str, str], app_config: Any) -> Dict[str, Any]:
    """Envía un correo electrónico desde el formulario de contacto.

    Args:
        datos_contacto: Diccionario con las claves:
            - nombre (str): Nombre completo del remitente
            - email (str): Email del remitente (para Reply-To)
            - asunto (str): Asunto seleccionado en el formulario
            - mensaje (str): Mensaje completo

        app_config: Configuración de Flask (current_app.config)

    Returns:
        Diccionario con:
            - ok (bool): True si el envío fue exitoso, False en caso contrario
            - error (str, opcional): Mensaje de error si ok=False
    """
    try:
        # Leer configuración
        mail_server = app_config.get("MAIL_SERVER")
        mail_port = app_config.get("MAIL_PORT")
        mail_use_tls = app_config.get("MAIL_USE_TLS")
        mail_username = app_config.get("MAIL_USERNAME")
        mail_password = app_config.get("MAIL_PASSWORD")
        mail_default_sender = app_config.get("MAIL_DEFAULT_SENDER") or mail_username
        mail_contact_recipient = app_config.get("MAIL_CONTACT_RECIPIENT") or mail_username

        # Validar que tenemos la configuración necesaria
        if not all([mail_server, mail_port, mail_username, mail_password, mail_contact_recipient]):
            return {
                "ok": False,
                "error": "Configuración de correo incompleta"
            }

        # Extraer datos del contacto
        nombre = datos_contacto.get("nombre", "")
        email_remitente = datos_contacto.get("email", "")
        asunto_formulario = datos_contacto.get("asunto", "")
        mensaje_texto = datos_contacto.get("mensaje", "")

        # Construir el correo
        msg = MIMEMultipart()
        msg["From"] = mail_default_sender
        msg["To"] = mail_contact_recipient
        msg["Subject"] = f"[Web AMPA] {asunto_formulario} - {nombre}"
        msg["Reply-To"] = email_remitente

        # Cuerpo del mensaje
        fecha_envio = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        cuerpo = f"""
Nuevo mensaje de contacto recibido desde la web del AMPA:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DATOS DEL REMITENTE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Nombre:  {nombre}
Email:   {email_remitente}
Asunto:  {asunto_formulario}
Fecha:   {fecha_envio}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MENSAJE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{mensaje_texto}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Para responder a este mensaje, simplemente pulsa "Responder" 
y tu respuesta llegará directamente a: {email_remitente}
"""

        msg.attach(MIMEText(cuerpo, "plain", "utf-8"))

        # Conectar y enviar
        ssl_context = ssl.create_default_context()
        if not mail_use_tls and int(mail_port) == 465:
            with smtplib.SMTP_SSL(mail_server, int(mail_port), context=ssl_context) as server:
                server.login(mail_username, mail_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(mail_server, int(mail_port)) as server:
                if mail_use_tls:
                    server.starttls(context=ssl_context)

                server.login(mail_username, mail_password)
                server.send_message(msg)

        return {"ok": True}

    except smtplib.SMTPAuthenticationError as e:
        error_msg = "Error de autenticación SMTP. Verifica MAIL_USERNAME y MAIL_PASSWORD"
        return {
            "ok": False,
            "error": error_msg
        }

    except smtplib.SMTPException as e:
        error_msg = f"Error al enviar correo: {type(e).__name__}"
        return {
            "ok": False,
            "error": error_msg
        }

    except Exception as e:
        error_msg = f"Error inesperado: {type(e).__name__}"
        return {
            "ok": False,
            "error": error_msg
        }


def send_member_verification_email(
    *,
    recipient_email: str,
    verify_url: str,
    app_config: Any,
) -> Dict[str, Any]:
    subject = "Verifica tu correo"
    body = (
        "Hola,\n\n"
        "Para completar tu alta como socio/a, verifica tu correo usando este enlace:\n\n"
        f"{verify_url}\n\n"
        "Si no has solicitado el alta, puedes ignorar este mensaje.\n"
    )
    return _send_plain_email(subject=subject, body=body, recipient=recipient_email, app_config=app_config)


def send_new_member_registration_notification_to_ampa(
    *,
    member_name: str,
    member_email: str,
    member_phone: str | None,
    app_config: Any,
) -> Dict[str, Any]:
    recipient = (
        app_config.get("MAIL_AMPA_RECIPIENT")
        or app_config.get("MAIL_CONTACT_RECIPIENT")
        or app_config.get("MAIL_USERNAME")
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
    return _send_plain_email(subject=subject, body=body, recipient=recipient, app_config=app_config)


def send_set_password_email(
    *,
    recipient_email: str,
    set_password_url: str,
    app_config: Any,
) -> Dict[str, Any]:
    subject = "Establece tu contraseña"
    body = (
        "Hola,\n\n"
        "Tu alta ha sido aprobada. Para acceder al área de socios, establece tu contraseña aquí:\n\n"
        f"{set_password_url}\n\n"
        "Este enlace caduca. Si no has solicitado el alta, puedes ignorar este mensaje.\n"
    )
    return _send_plain_email(subject=subject, body=body, recipient=recipient_email, app_config=app_config)
