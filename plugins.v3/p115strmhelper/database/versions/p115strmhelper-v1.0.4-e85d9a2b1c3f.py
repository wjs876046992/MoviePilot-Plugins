"""1.0.4

Revision ID: e85d9a2b1c3f
Revises: c76c9a1f52dc
Create Date: 2026-10-08 20:10:00.000000

将全部 115 64位 ID 字段从 32位 Integer 扩展为 BigInteger，
解决 PostgreSQL 环境下 19 位 ID 溢出 (NumericValueOutOfRange / 9h9h) 的问题。
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
db_version = "1.0.4"
revision = "e85d9a2b1c3f"
down_revision = "c76c9a1f52dc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("life_event", schema=None) as batch_op:
        batch_op.alter_column("id", type_=sa.BigInteger(), existing_type=sa.Integer())
        batch_op.alter_column("file_id", type_=sa.BigInteger(), existing_type=sa.Integer())
        batch_op.alter_column("parent_id", type_=sa.BigInteger(), existing_type=sa.Integer())

    with op.batch_alter_table("files", schema=None) as batch_op:
        batch_op.alter_column("id", type_=sa.BigInteger(), existing_type=sa.Integer())
        batch_op.alter_column("parent_id", type_=sa.BigInteger(), existing_type=sa.Integer())

    with op.batch_alter_table("folders", schema=None) as batch_op:
        batch_op.alter_column("id", type_=sa.BigInteger(), existing_type=sa.Integer())
        batch_op.alter_column("parent_id", type_=sa.BigInteger(), existing_type=sa.Integer())

    with op.batch_alter_table("open_files", schema=None) as batch_op:
        batch_op.alter_column("id", type_=sa.BigInteger(), existing_type=sa.Integer())
        batch_op.alter_column("parent_id", type_=sa.BigInteger(), existing_type=sa.Integer())

    with op.batch_alter_table("open_folders", schema=None) as batch_op:
        batch_op.alter_column("id", type_=sa.BigInteger(), existing_type=sa.Integer())
        batch_op.alter_column("parent_id", type_=sa.BigInteger(), existing_type=sa.Integer())


def downgrade() -> None:
    with op.batch_alter_table("open_folders", schema=None) as batch_op:
        batch_op.alter_column("parent_id", type_=sa.Integer(), existing_type=sa.BigInteger())
        batch_op.alter_column("id", type_=sa.Integer(), existing_type=sa.BigInteger())

    with op.batch_alter_table("open_files", schema=None) as batch_op:
        batch_op.alter_column("parent_id", type_=sa.Integer(), existing_type=sa.BigInteger())
        batch_op.alter_column("id", type_=sa.Integer(), existing_type=sa.BigInteger())

    with op.batch_alter_table("folders", schema=None) as batch_op:
        batch_op.alter_column("parent_id", type_=sa.Integer(), existing_type=sa.BigInteger())
        batch_op.alter_column("id", type_=sa.Integer(), existing_type=sa.BigInteger())

    with op.batch_alter_table("files", schema=None) as batch_op:
        batch_op.alter_column("parent_id", type_=sa.Integer(), existing_type=sa.BigInteger())
        batch_op.alter_column("id", type_=sa.Integer(), existing_type=sa.BigInteger())

    with op.batch_alter_table("life_event", schema=None) as batch_op:
        batch_op.alter_column("parent_id", type_=sa.Integer(), existing_type=sa.BigInteger())
        batch_op.alter_column("file_id", type_=sa.Integer(), existing_type=sa.BigInteger())
        batch_op.alter_column("id", type_=sa.Integer(), existing_type=sa.BigInteger())
