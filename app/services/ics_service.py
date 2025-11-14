from datetime import timezone

from flask import current_app


class ICSService:
    @staticmethod
    def generate(event):
        start = event.start_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        end = event.end_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        uid = f"{event.id}@ampa-jnt.es"
        details = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//AMPA Julián Nieto//EN\r\n"
            "CALSCALE:GREGORIAN\r\n"
            "METHOD:PUBLISH\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            f"DTSTAMP:{start}\r\n"
            f"DTSTART:{start}\r\n"
            f"DTEND:{end}\r\n"
            f"SUMMARY:{event.title}\r\n"
            f"DESCRIPTION:{event.description_html}\r\n"
            f"LOCATION:{event.location}\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR"
        )
        return details
