"""add payment provider enum

Revision ID: 0056
Revises: 0055
Create Date: 2026-07-15 12:40:00.000000

"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0056_add_payment_provider_enum"
down_revision = "0055_ensure_multitenant_store_indexes"
branch_labels = None
depends_on = None

def upgrade():
    # Create the enum type if it doesn't exist
    payment_provider = postgresql.ENUM('flouci', 'clix', 'tnpay', 'cash', 'stripe', 'cmi', 'aliapay', 'nexus', name='paymentprovider')
    payment_provider.create(op.get_bind(), checkfirst=True)
    
    # Add indexes for multi-tenant optimization (Bloc 3 requirement)
    op.create_index('ix_orders_store_id_created_at', 'orders', ['store_id', 'created_at'])
    op.create_index('ix_conversations_store_id_created_at', 'conversation_logs', ['store_id', 'created_at'])

def downgrade():
    op.drop_index('ix_orders_store_id_created_at', table_name='orders')
    op.drop_index('ix_conversations_store_id_created_at', table_name='conversation_logs')
    # We usually don't drop types in downgrade if they might be used elsewhere, 
    # but for completeness:
    # sa.Enum(name='paymentprovider').drop(op.get_bind(), checkfirst=True)
