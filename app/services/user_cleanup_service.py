from datetime import datetime, timedelta
import pytz
from app.extensions import db
from app.models import User

def cleanup_deactivated_users():
    """
    Elimina usuarios que llevan desactivados más de 30 días.
    """
    # Usar datetime consciente de la zona horaria (UTC) para evitar warnings y errores de comparación
    limit_date = datetime.now(pytz.UTC) - timedelta(days=30)
    
    try:
        users_to_delete = User.query.filter(
            User.is_active == False,
            User.deactivated_at <= limit_date
        ).all()
        
        count = len(users_to_delete)
        for user in users_to_delete:
            # Nota: Si hay restricciones de clave foránea sin CASCADE, esto fallará.
            # Se asume que el modelo User tiene las relaciones configuradas con cascade="all, delete-orphan"
            db.session.delete(user)
        
        if count > 0:
            db.session.commit()
        
        return count
    except Exception:
        db.session.rollback()
        raise
