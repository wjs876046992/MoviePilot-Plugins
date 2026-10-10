"""1.0.5

Revision ID: f94a8c1d2e3b
Revises: e85d9a2b1c3f
Create Date: 2026-10-09 20:30:00.000000

为 files、folders、open_files、open_folders 核心高频查询列补充 B-Tree 索引：
- files(parent_id), files(pickcode)
- folders(parent_id)
- open_files(parent_id), open_files(pick_code)
- open_folders(parent_id)
解决两万级存量数据下目录树递归与 pickcode 反查的全表扫描性能瓶颈。
"""

from alembic import op


# revision identifiers, used by Alembic
db_version = "1.0.5"
revision = "f94a8c1d2e3b"
down_revision = "e85d9a2b1c3f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("files", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_files_parent_id"), ["parent_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_files_pickcode"), ["pickcode"], unique=False)

    with op.batch_alter_table("folders", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_folders_parent_id"), ["parent_id"], unique=False)

    with op.batch_alter_table("open_files", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_open_files_parent_id"), ["parent_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_open_files_pick_code"), ["pick_code"], unique=False)

    with op.batch_alter_table("open_folders", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_open_folders_parent_id"), ["parent_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("open_folders", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_open_folders_parent_id"))

    with op.batch_alter_table("open_files", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_open_files_pick_code"))
        batch_op.drop_index(batch_op.f("ix_open_files_parent_id"))

    with op.batch_alter_table("folders", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_folders_parent_id"))

    with op.batch_alter_table("files", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_files_pickcode"))
        batch_op.drop_index(batch_op.f("ix_files_parent_id"))
