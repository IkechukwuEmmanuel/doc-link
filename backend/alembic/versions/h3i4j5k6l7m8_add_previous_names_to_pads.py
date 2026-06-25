"""add_previous_names_to_pads

Revision ID: h3i4j5k6l7m8
Revises: g2h3i4j5k6l7
Create Date: 2026-06-24 16:35:00.000000

Add previous_names JSON array to pads table to track old names for redirects.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'h3i4j5k6l7m8'
down_revision: Union[str, None] = 'g2h3i4j5k6l7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add previous_names column to pads table
    op.add_column(
        'pads',
        sa.Column('previous_names', sa.JSON(), server_default=sa.text("'[]'"), nullable=False)
    )


def downgrade() -> None:
    # Remove previous_names column
    op.drop_column('pads', 'previous_names')
