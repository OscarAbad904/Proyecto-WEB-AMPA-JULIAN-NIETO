from datetime import datetime, timedelta
from app.extensions import db
from app.models import User

def cleanup_deactivated_users():
    """
    Elimina usuarios que llevan desactivados más de 30 días.
    """
    limit_date = datetime.utcnow() - timedelta(days=30)
    
    users_to_delete = User.query.filter(
        User.is_active == False,
        User.deactivated_at <= limit_date
    ).all()
    
    count = len(users_to_delete)
    for user in users_to_delete:
        # Nota: Si hay restricciones de clave foránea sin CASCADE, esto fallará.
        # Se asume que el modelo User tiene las relaciones configuradas con cascade="all, delete-orphan"
        # o que no hay restricciones que impidan la eliminación.
        db.session.delete(user)
    
    if count > 0:
        db.session.commit()
    
    return count
