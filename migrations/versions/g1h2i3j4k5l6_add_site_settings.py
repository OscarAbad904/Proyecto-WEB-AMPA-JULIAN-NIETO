"""add site_settings table for style management

Revision ID: g1h2i3j4k5l6
Revises: 54172c430509
Create Date: 2024-12-22 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'g1h2i3j4k5l6'
down_revision = '54172c430509'
branch_labels = None
depends_on = None


def upgrade():
    # Crear tabla site_settings
    op.create_table(
        'site_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=128), nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_site_settings_key'), 'site_settings', ['key'], unique=True)
    
    # Insertar configuración por defecto del estilo activo
    op.execute("""
        INSERT INTO site_settings (key, value, description)
        VALUES ('active_style', 'Navidad', 'Estilo visual activo de la web')
    """)


def downgrade():
    op.drop_index(op.f('ix_site_settings_key'), table_name='site_settings')
    op.drop_table('site_settings')
