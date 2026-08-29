"""report groups table, categories.report_group -> report_group_id

Revision ID: a1b2c3d4e5f6
Revises: 8ef295c387db
Create Date: 2026-08-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '8ef295c387db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Маппинг старых строковых групп -> (имя новой группы, section, sort_order)
_GROUP_DEFS = {
    "revenue_lavka": ("Доход", "revenue", 10),
    "revenue_catering": ("Доход", "revenue", 10),
    "revenue_rent": ("Доход", "revenue", 10),
    "revenue_commission": ("Доход", "revenue", 10),
    "direct_products": ("Прямой расход", "direct", 20),
    "direct_catering_cost": ("Прямой расход", "direct", 20),
    "direct_animal_feed": ("Прямой расход", "direct", 20),
    "direct_gas": ("Прямой расход", "direct", 20),
    "direct_meals": ("Прямой расход", "direct", 20),
    "direct_wages": ("Прямой расход", "direct", 20),
    "direct_operational": ("Прямой расход", "direct", 20),
    "direct_other": ("Прямой расход", "direct", 20),
    "overhead_equaring": ("Накладные расходы", "overhead", 30),
    "overhead_delivery": ("Накладные расходы", "overhead", 30),
    "overhead_wifi": ("Накладные расходы", "overhead", 30),
    "overhead_bank": ("Накладные расходы", "overhead", 30),
    "overhead_it": ("Накладные расходы", "overhead", 30),
    "overhead_electricity": ("Накладные расходы", "overhead", 30),
    "overhead_finance": ("Накладные расходы", "overhead", 30),
    "overhead_marketing": ("Накладные расходы", "overhead", 30),
    "overhead_equipment": ("Накладные расходы", "overhead", 30),
    "overhead_rent": ("Накладные расходы", "overhead", 30),
    "overhead_other": ("Накладные расходы", "overhead", 30),
    "taxes": ("Налоги и сборы", "taxes", 40),
    "investments": ("Инвестиции", "other", 50),
}


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'report_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('section', sa.String(length=20), nullable=False, server_default='direct'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint('id'),
    )

    conn = op.get_bind()
    # Переносим старые строковые группы в таблицу report_groups
    rows = conn.execute(
        sa.text("SELECT DISTINCT report_group FROM categories WHERE report_group IS NOT NULL")
    ).fetchall()

    # name(новой группы) -> id только что вставленной строки report_groups
    group_ids: dict[str, int] = {}
    # old_key (исходное значение categories.report_group) -> id новой группы.
    # Отдельный маппинг нужен, чтобы не терять соответствие "старый ключ -> id"
    # при переносе нескольких старых ключей в одну и ту же новую группу.
    old_key_to_group_id: dict[str, int] = {}

    for (old_key,) in rows:
        name, section, sort_order = _GROUP_DEFS.get(old_key, (old_key, "other", 100))
        if name not in group_ids:
            result = conn.execute(
                sa.text(
                    "INSERT INTO report_groups (name, section, sort_order, is_active) "
                    "VALUES (:name, :section, :sort_order, 1)"
                ),
                {"name": name, "section": section, "sort_order": sort_order},
            )
            group_ids[name] = result.lastrowid
        old_key_to_group_id[old_key] = group_ids[name]

    op.add_column(
        'categories',
        sa.Column('report_group_id', sa.Integer(), nullable=True),
    )
    for old_key, gid in old_key_to_group_id.items():
        conn.execute(
            sa.text(
                "UPDATE categories SET report_group_id = :gid WHERE report_group = :key"
            ),
            {"gid": gid, "key": old_key},
        )

    op.create_foreign_key(
        'fk_categories_report_group_id',
        'categories',
        'report_groups',
        ['report_group_id'],
        ['id'],
    )
    op.drop_column('categories', 'report_group')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        'categories',
        sa.Column('report_group', sa.String(length=50), nullable=True),
    )
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT rg.id, rg.name FROM report_groups rg"
        )
    ).fetchall()
    for gid, name in rows:
        conn.execute(
            sa.text("UPDATE categories SET report_group = :name WHERE report_group_id = :gid"),
            {"name": name, "gid": gid},
        )
    op.drop_constraint('fk_categories_report_group_id', 'categories', type_='foreignkey')
    op.drop_column('categories', 'report_group_id')
    op.drop_table('report_groups')
