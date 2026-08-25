"""full sms modules: walk-ins, packages, products, payments, commissions, history

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-11 09:00:00.000000

Adds the remaining Salon Management System entities on top of the
initial appointments schema (0001):

- service_categories + services.category_id
- walk_in_customers + customer_preferences
- specialists + specialist_specialties
- service_packages + service_package_items
- products + product_usage
- appointment_services (authoritative list of rendered services)
- payments, commissions, service_history
- appointments: walk_in_id / package_id / package_price_cents /
  total_cents / discount_cents columns, service_id made nullable, and a
  CHECK enforcing exactly one of client_id / walk_in_id.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Enums ---------------------------------------------------------
    payment_method = sa.Enum("cash", "card", "ewallet", name="payment_method")
    payment_status = sa.Enum("pending", "paid", "refunded", name="payment_status")
    payment_method.create(op.get_bind(), checkfirst=True)
    payment_status.create(op.get_bind(), checkfirst=True)
    # The same types are reused as column types below; don't let SQLAlchemy
    # re-emit CREATE TYPE when the payments table is created.
    payment_method_col = postgresql.ENUM(
        "cash", "card", "ewallet", name="payment_method", create_type=False
    )
    payment_status_col = postgresql.ENUM(
        "pending", "paid", "refunded", name="payment_status", create_type=False
    )

    # --- Service categories ---------------------------------------------
    op.create_table(
        "service_categories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "name", name="uq_service_categories_org_name"),
    )
    op.create_index("ix_service_categories_organization_id", "service_categories", ["organization_id"], unique=False)
    op.add_column(
        "services",
        sa.Column("category_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key("fk_services_category_id", "services", "service_categories", ["category_id"], ["id"])
    op.create_index("ix_services_category_id", "services", ["category_id"], unique=False)

    # --- Walk-ins & preferences ------------------------------------------
    op.create_table(
        "walk_in_customers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("full_name", sa.String(length=160), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("converted_client_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["converted_client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_walk_ins_organization_id", "walk_in_customers", ["organization_id"], unique=False)
    op.create_index("ix_walk_ins_org_phone", "walk_in_customers", ["organization_id", "phone"], unique=False)

    op.create_table(
        "customer_preferences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("preferred_specialist_id", sa.UUID(), nullable=True),
        sa.Column("allergies", sa.Text(), nullable=True),
        sa.Column("product_sensitivities", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["preferred_specialist_id"], ["staff.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "client_id", name="uq_customer_preferences_client"),
    )
    op.create_index("ix_customer_preferences_organization_id", "customer_preferences", ["organization_id"], unique=False)

    # --- Specialists ------------------------------------------------------
    op.create_table(
        "specialists",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("staff_id", sa.UUID(), nullable=False),
        sa.Column("default_commission_rate_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("default_commission_rate_pct >= 0", name="ck_specialists_rate_nonnegative"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["staff_id"], ["staff.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "staff_id", name="uq_specialists_staff"),
    )
    op.create_index("ix_specialists_organization_id", "specialists", ["organization_id"], unique=False)

    op.create_table(
        "specialist_specialties",
        sa.Column("specialist_id", sa.UUID(), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["service_categories.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["specialist_id"], ["specialists.id"]),
        sa.PrimaryKeyConstraint("specialist_id", "category_id"),
    )
    op.create_index("ix_specialist_specialties_organization_id", "specialist_specialties", ["organization_id"], unique=False)

    # --- Packages -----------------------------------------------------------
    op.create_table(
        "service_packages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("price_cents >= 0", name="ck_packages_price_nonnegative"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_packages_organization_id", "service_packages", ["organization_id"], unique=False)
    op.create_index("ix_packages_org_active", "service_packages", ["organization_id", "active"], unique=False)

    op.create_table(
        "service_package_items",
        sa.Column("package_id", sa.UUID(), nullable=False),
        sa.Column("service_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["package_id"], ["service_packages.id"]),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"]),
        sa.PrimaryKeyConstraint("package_id", "service_id"),
    )
    op.create_index("ix_package_items_organization_id", "service_package_items", ["organization_id"], unique=False)

    # --- Products -----------------------------------------------------------
    op.create_table(
        "products",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("sku", sa.String(length=80), nullable=True),
        sa.Column("category", sa.String(length=60), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("stock_quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("reorder_level", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("price_cents >= 0", name="ck_products_price_nonnegative"),
        sa.CheckConstraint("stock_quantity >= 0", name="ck_products_stock_nonnegative"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_organization_id", "products", ["organization_id"], unique=False)
    op.create_index("ix_products_org_active", "products", ["organization_id", "active"], unique=False)

    # --- Appointments alterations -------------------------------------------
    op.add_column("appointments", sa.Column("walk_in_id", sa.UUID(), nullable=True))
    op.add_column("appointments", sa.Column("package_id", sa.UUID(), nullable=True))
    op.add_column("appointments", sa.Column("package_price_cents", sa.Integer(), nullable=True))
    op.add_column(
        "appointments",
        sa.Column("total_cents", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "appointments",
        sa.Column("discount_cents", sa.Integer(), server_default="0", nullable=False),
    )

    op.create_foreign_key("fk_appointments_walk_in_id", "appointments", "walk_in_customers", ["walk_in_id"], ["id"])
    op.create_foreign_key("fk_appointments_package_id", "appointments", "service_packages", ["package_id"], ["id"])
    op.create_index("ix_appointments_org_walkin", "appointments", ["organization_id", "walk_in_id"], unique=False)
    op.create_index("ix_appointments_org_start", "appointments", ["organization_id", "start_time"], unique=False)

    # Existing single-service bookings keep their service_id reference.
    op.execute(
        """
        UPDATE appointments
        SET total_cents = services.price_cents
        FROM services
        WHERE appointments.service_id = services.id
        """
    )
    op.alter_column("appointments", "service_id", existing_type=sa.UUID(), nullable=True)

    op.create_check_constraint(
        "ck_appointments_client_or_walkin",
        "appointments",
        "(client_id IS NOT NULL AND walk_in_id IS NULL) OR (client_id IS NULL AND walk_in_id IS NOT NULL)",
    )
    op.create_check_constraint("ck_appointments_discount_nonnegative", "appointments", "discount_cents >= 0")
    op.create_check_constraint("ck_appointments_total_nonnegative", "appointments", "total_cents >= 0")

    # --- Appointment services (rendered lines) ------------------------------
    op.create_table(
        "appointment_services",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("appointment_id", sa.UUID(), nullable=False),
        sa.Column("service_id", sa.UUID(), nullable=True),
        sa.Column("service_name", sa.String(length=120), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("commission_rate_pct", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("price_cents >= 0", name="ck_appt_services_price_nonnegative"),
        sa.CheckConstraint("quantity > 0", name="ck_appt_services_quantity_positive"),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_appointment_services_organization_id", "appointment_services", ["organization_id"], unique=False)
    op.create_index("ix_appointment_services_appointment_id", "appointment_services", ["appointment_id"], unique=False)

    # Backfill appointment_services for pre-existing single-service bookings.
    op.execute(
        """
        INSERT INTO appointment_services (
            id, organization_id, appointment_id, service_id, service_name,
            duration_minutes, price_cents, quantity, created_by, updated_by
        )
        SELECT
            gen_random_uuid(), a.organization_id, a.id, a.service_id, s.name,
            s.duration_minutes, s.price_cents, 1, a.created_by, a.updated_by
        FROM appointments a
        JOIN services s ON s.id = a.service_id
        """
    )

    # --- Product usage -------------------------------------------------------
    op.create_table(
        "product_usage",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("appointment_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=True),
        sa.Column("product_name", sa.String(length=160), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("unit_cost_cents", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("quantity > 0", name="ck_product_usage_quantity_positive"),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_usage_organization_id", "product_usage", ["organization_id"], unique=False)
    op.create_index("ix_product_usage_appointment_id", "product_usage", ["appointment_id"], unique=False)
    op.create_index("ix_product_usage_product_id", "product_usage", ["product_id"], unique=False)

    # --- Payments -------------------------------------------------------------
    op.create_table(
        "payments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("appointment_id", sa.UUID(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("method", payment_method_col, nullable=False),
        sa.Column("status", payment_status_col, nullable=False),
        sa.Column("tip_cents", sa.Integer(), nullable=False),
        sa.Column("discount_cents", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_cents >= 0", name="ck_payments_amount_nonnegative"),
        sa.CheckConstraint("discount_cents >= 0", name="ck_payments_discount_nonnegative"),
        sa.CheckConstraint("tip_cents >= 0", name="ck_payments_tip_nonnegative"),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payments_organization_id", "payments", ["organization_id"], unique=False)
    op.create_index("ix_payments_appointment_id", "payments", ["appointment_id"], unique=False)
    op.create_index("ix_payments_status", "payments", ["organization_id", "status"], unique=False)

    # --- Commissions ------------------------------------------------------------
    op.create_table(
        "commissions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("appointment_id", sa.UUID(), nullable=False),
        sa.Column("specialist_id", sa.UUID(), nullable=True),
        sa.Column("service_name", sa.String(length=120), nullable=False),
        sa.Column("rate_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_cents >= 0", name="ck_commissions_amount_nonnegative"),
        sa.CheckConstraint("rate_pct >= 0", name="ck_commissions_rate_nonnegative"),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["specialist_id"], ["specialists.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_commissions_organization_id", "commissions", ["organization_id"], unique=False)
    op.create_index("ix_commissions_appointment_id", "commissions", ["appointment_id"], unique=False)
    op.create_index("ix_commissions_specialist_id", "commissions", ["specialist_id"], unique=False)
    op.create_index("ix_commissions_org_specialist_created", "commissions", ["organization_id", "specialist_id", "created_at"], unique=False)

    # --- Service history -----------------------------------------------------------
    op.create_table(
        "service_history",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("appointment_id", sa.UUID(), nullable=True),
        sa.Column("service_id", sa.UUID(), nullable=True),
        sa.Column("specialist_id", sa.UUID(), nullable=True),
        sa.Column("service_name", sa.String(length=120), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["specialist_id"], ["specialists.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_service_history_organization_id", "service_history", ["organization_id"], unique=False)
    op.create_index("ix_service_history_client_id", "service_history", ["client_id"], unique=False)
    op.create_index("ix_service_history_client_completed", "service_history", ["client_id", "completed_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_service_history_client_completed", table_name="service_history")
    op.drop_index("ix_service_history_client_id", table_name="service_history")
    op.drop_index("ix_service_history_organization_id", table_name="service_history")
    op.drop_table("service_history")

    op.drop_index("ix_commissions_org_specialist_created", table_name="commissions")
    op.drop_index("ix_commissions_specialist_id", table_name="commissions")
    op.drop_index("ix_commissions_appointment_id", table_name="commissions")
    op.drop_index("ix_commissions_organization_id", table_name="commissions")
    op.drop_table("commissions")

    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index("ix_payments_appointment_id", table_name="payments")
    op.drop_index("ix_payments_organization_id", table_name="payments")
    op.drop_table("payments")

    op.drop_index("ix_product_usage_product_id", table_name="product_usage")
    op.drop_index("ix_product_usage_appointment_id", table_name="product_usage")
    op.drop_index("ix_product_usage_organization_id", table_name="product_usage")
    op.drop_table("product_usage")

    op.drop_index("ix_appointment_services_appointment_id", table_name="appointment_services")
    op.drop_index("ix_appointment_services_organization_id", table_name="appointment_services")
    op.drop_table("appointment_services")

    op.drop_constraint("ck_appointments_total_nonnegative", "appointments")
    op.drop_constraint("ck_appointments_discount_nonnegative", "appointments")
    op.drop_constraint("ck_appointments_client_or_walkin", "appointments")
    op.alter_column("appointments", "service_id", existing_type=sa.UUID(), nullable=False)
    op.drop_index("ix_appointments_org_start", table_name="appointments")
    op.drop_index("ix_appointments_org_walkin", table_name="appointments")
    op.drop_constraint("fk_appointments_package_id", "appointments", type_="foreignkey")
    op.drop_constraint("fk_appointments_walk_in_id", "appointments", type_="foreignkey")
    op.drop_column("appointments", "discount_cents")
    op.drop_column("appointments", "total_cents")
    op.drop_column("appointments", "package_price_cents")
    op.drop_column("appointments", "package_id")
    op.drop_column("appointments", "walk_in_id")

    op.drop_index("ix_products_org_active", table_name="products")
    op.drop_index("ix_products_organization_id", table_name="products")
    op.drop_table("products")

    op.drop_index("ix_package_items_organization_id", table_name="service_package_items")
    op.drop_table("service_package_items")
    op.drop_index("ix_packages_org_active", table_name="service_packages")
    op.drop_index("ix_packages_organization_id", table_name="service_packages")
    op.drop_table("service_packages")

    op.drop_index("ix_specialist_specialties_organization_id", table_name="specialist_specialties")
    op.drop_table("specialist_specialties")
    op.drop_index("ix_specialists_organization_id", table_name="specialists")
    op.drop_table("specialists")

    op.drop_index("ix_customer_preferences_organization_id", table_name="customer_preferences")
    op.drop_table("customer_preferences")

    op.drop_index("ix_walk_ins_org_phone", table_name="walk_in_customers")
    op.drop_index("ix_walk_ins_organization_id", table_name="walk_in_customers")
    op.drop_table("walk_in_customers")

    op.drop_index("ix_services_category_id", table_name="services")
    op.drop_constraint("fk_services_category_id", "services", type_="foreignkey")
    op.drop_column("services", "category_id")
    op.drop_index("ix_service_categories_organization_id", table_name="service_categories")
    op.drop_table("service_categories")

    payment_status = sa.Enum("pending", "paid", "refunded", name="payment_status")
    payment_method = sa.Enum("cash", "card", "ewallet", name="payment_method")
    payment_status.drop(op.get_bind(), checkfirst=True)
    payment_method.drop(op.get_bind(), checkfirst=True)
