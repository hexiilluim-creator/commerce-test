"""0006_appointments_module — Tables RDV (BusinessConfig, Service, Availability, Appointment)

Revision ID: 0006
Revises: 0005_structured_agent_fields
Create Date: 2026-04-23

Compatibility (P0):
  - down_revision corrigée vers "0005_structured_agent_fields" (au lieu de "0005").
  - Suppression des `CREATE TYPE ... AS ENUM` bruts (PostgreSQL-only)
    qui cassaient SQLite avec une OperationalError.
  - Création des enums via `sa.Enum(..., native_enum=...)` :
      • PostgreSQL : enums natifs (comportement d'origine).
      • SQLite / autres : fallback CHECK-based (non natif).
  - Downgrade rendu propre (drop des index avant drop des tables).
"""
import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005_structured_agent_fields"
branch_labels = None
depends_on = None


# ── Listes des valeurs (uniques sources de vérité pour les enums) ─────────────
_BUSINESS_TYPES = ("ecommerce", "appointments", "hybrid")
_APPT_STATUSES = ("pending", "confirmed", "cancelled", "completed", "no_show")
_SERVICE_CATEGORIES = ("medical", "beauty", "legal", "fitness", "restaurant", "auto", "other")
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _is_postgres() -> bool:
    bind = op.get_bind()
    try:
        return bind.dialect.name == "postgresql"
    except Exception:
        return False


def _enum(values, name: str) -> sa.Enum:
    """
    Construit un sa.Enum approprié au dialecte courant :
      - PostgreSQL : native_enum=True (CREATE TYPE auto)
      - autres     : native_enum=False (fallback portable, e.g. SQLite via CHECK)
    """
    # P0 FIX: native_enum=False évite les DuplicateObjectError sur PostgreSQL lors des migrations automatiques
    return sa.Enum(*values, name=name, native_enum=False)


def upgrade() -> None:
    is_pg = _is_postgres()

    # ── Enums (création explicite côté PostgreSQL pour éviter les "CREATE TYPE
    #    inline" lors de chaque create_table) ──────────────────────────────────
    if is_pg:
        for enum_name, values in (
            ("businesstype", _BUSINESS_TYPES),
            ("appointmentstatus", _APPT_STATUSES),
            ("servicecategory", _SERVICE_CATEGORIES),
            ("dayofweek", _DAYS),
        ):
            sa.Enum(*values, name=enum_name).create(op.get_bind(), checkfirst=True)

    # ── business_configs ──────────────────────────────────────────────────────
    op.create_table(
        "business_configs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "store_id",
            sa.Integer,
            sa.ForeignKey("stores.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "business_type",
            _enum(_BUSINESS_TYPES, "businesstype"),
            nullable=False,
            server_default="ecommerce",
        ),
        sa.Column(
            "service_category",
            _enum(_SERVICE_CATEGORIES, "servicecategory"),
            nullable=True,
        ),
        sa.Column("default_slot_duration_min", sa.Integer, nullable=False, server_default="30"),
        sa.Column("appointment_confirm_msg", sa.Text, nullable=True),
        sa.Column("appointment_reminder_msg", sa.Text, nullable=True),
        sa.Column("booking_lead_time_hours", sa.Integer, nullable=False, server_default="1"),
        sa.Column("max_appointments_per_day", sa.Integer, nullable=True),
        sa.Column("address", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_business_configs_store_id", "business_configs", ["store_id"])

    # ── services ──────────────────────────────────────────────────────────────
    op.create_table(
        "services",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "business_config_id",
            sa.Integer,
            sa.ForeignKey("business_configs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("store_id", sa.Integer, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("duration_min", sa.Integer, nullable=False, server_default="30"),
        sa.Column("price", sa.Float, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1") if not is_pg else sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_services_store_id", "services", ["store_id"])
    op.create_index("ix_services_business_config_id", "services", ["business_config_id"])

    # ── availability_rules ────────────────────────────────────────────────────
    op.create_table(
        "availability_rules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "business_config_id",
            sa.Integer,
            sa.ForeignKey("business_configs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("store_id", sa.Integer, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("day_of_week", _enum(_DAYS, "dayofweek"), nullable=False),
        sa.Column("start_time", sa.String(5), nullable=False),
        sa.Column("end_time", sa.String(5), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1") if not is_pg else sa.text("true")),
    )
    op.create_index("ix_availability_rules_store_id", "availability_rules", ["store_id"])

    # ── availability_exceptions ───────────────────────────────────────────────
    op.create_table(
        "availability_exceptions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("is_closed", sa.Boolean, nullable=False, server_default=sa.text("1") if not is_pg else sa.text("true")),
        sa.Column("reason", sa.String(255), nullable=True),
    )
    op.create_index("ix_availability_exceptions_store_id", "availability_exceptions", ["store_id"])

    # ── appointments ──────────────────────────────────────────────────────────
    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("customer_id", sa.Integer, sa.ForeignKey("customers.id"), nullable=False),
        sa.Column(
            "service_id",
            sa.Integer,
            sa.ForeignKey("services.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            _enum(_APPT_STATUSES, "appointmentstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_min", sa.Integer, nullable=False, server_default="30"),
        sa.Column("patient_name", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("reminder_sent", sa.Boolean, nullable=False, server_default=sa.text("0") if not is_pg else sa.text("false")),
        sa.Column("wa_confirm_msg_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "store_id", "scheduled_at", "service_id",
            name="uq_appointments_store_slot_service",
        ),
    )
    op.create_index("ix_appointments_store_id", "appointments", ["store_id"])
    op.create_index("ix_appointments_customer_id", "appointments", ["customer_id"])
    op.create_index("ix_appointments_scheduled_at", "appointments", ["scheduled_at"])


def downgrade() -> None:
    is_pg = _is_postgres()

    # ── Drop indexes & tables (ordre inverse, avec table_name explicite) ──────
    op.drop_index("ix_appointments_scheduled_at", table_name="appointments")
    op.drop_index("ix_appointments_customer_id", table_name="appointments")
    op.drop_index("ix_appointments_store_id", table_name="appointments")
    op.drop_table("appointments")

    op.drop_index("ix_availability_exceptions_store_id", table_name="availability_exceptions")
    op.drop_table("availability_exceptions")

    op.drop_index("ix_availability_rules_store_id", table_name="availability_rules")
    op.drop_table("availability_rules")

    op.drop_index("ix_services_business_config_id", table_name="services")
    op.drop_index("ix_services_store_id", table_name="services")
    op.drop_table("services")

    op.drop_index("ix_business_configs_store_id", table_name="business_configs")
    op.drop_table("business_configs")

    # ── Drop enums (PostgreSQL uniquement) ────────────────────────────────────
    if is_pg:
        for enum_name in ("dayofweek", "servicecategory", "appointmentstatus", "businesstype"):
            sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
