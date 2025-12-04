"""Servicio de correo electrónico para el AMPA.

Este módulo proporciona funcionalidades para enviar correos electrónicos
utilizando SMTP de Gmail con contraseña de aplicación.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Dict, Any


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
        with smtplib.SMTP(mail_server, mail_port) as server:
            if mail_use_tls:
                server.starttls()
            
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
