from email.message import EmailMessage
import smtplib

from flask import current_app, render_template


class EmailService:
    @staticmethod
    def send_email(subject: str, recipients: list[str], template: str, **context) -> None:
        body = render_template(template, **context)
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = current_app.config["MAIL_DEFAULT_SENDER"]
        message["To"] = ", ".join(recipients)
        message.set_content(body, subtype="html")

        try:
            with smtplib.SMTP(
                current_app.config["MAIL_SERVER"], current_app.config["MAIL_PORT"]
            ) as sock:
                if current_app.config["MAIL_USE_TLS"]:
                    sock.starttls()
                username = current_app.config["MAIL_USERNAME"]
                password = current_app.config["MAIL_PASSWORD"]
                if username and password:
                    sock.login(username, password)
                sock.send_message(message)
        except Exception as exc:  # pragma: no cover
            current_app.logger.error("EmailService failed: %s", exc)
