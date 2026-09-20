"""Regression coverage for SQL contracts + core validation invariants.

Modules/features: schema.sql + 009_care_consistency.sql + models validators.
"""

from __future__ import annotations

import os
import subprocess

import asyncpg
import pytest

from models import MedicineItem, ParentInput, ScheduleInput


@pytest.mark.asyncio
async def test_sql_contracts_consent_logs_and_billing_checks_present():
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")
    if not dsn:
        pytest.skip("DATABASE_URL/SUPABASE_DB_URL is required for SQL contract tests")

    conn = await asyncpg.connect(dsn)
    try:
        cols = await conn.fetch(
            """
            select column_name, udt_name from information_schema.columns
            where table_name='consent_logs'
            order by ordinal_position
            """
        )
        names = [r["column_name"] for r in cols]
        assert names == ["id", "user_id", "parent_id", "consent_type", "agreed", "text", "ip", "created_at"]

        has_provider_event_at = await conn.fetchval(
            """
            select exists(
                select 1 from information_schema.columns
                where table_name='billing_subscriptions' and column_name='provider_event_at'
            )
            """
        )
        assert has_provider_event_at is True

        check_def = await conn.fetchval(
            """
            select pg_get_constraintdef(oid)
            from pg_constraint
            where conrelid='billing_orders'::regclass and conname='billing_order_amount_consistent'
            """
        )
        assert check_def and "subtotal" in check_def and "credit" in check_def and "amount" in check_def
    finally:
        await conn.close()


def test_migration_009_is_idempotent_on_disposable_db():
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")
    if not dsn:
        pytest.skip("DATABASE_URL/SUPABASE_DB_URL is required for SQL migration test")

    path = "/app/backend/migrations/009_care_consistency.sql"
    for _ in range(2):
        run = subprocess.run(["/usr/lib/postgresql/15/bin/psql", dsn, "-v", "ON_ERROR_STOP=1", "-f", path], capture_output=True, text=True)
        assert run.returncode == 0, run.stderr


def test_parent_city_and_medicine_shape_color_dose_validations():
    with pytest.raises(Exception):
        ParentInput(
            name="Dad",
            relationship="father",
            phone="+919876543210",
            language="en",
            timezone="Asia/Kolkata",
            city="   ",
            medicine_list=[],
        )

    with pytest.raises(Exception):
        MedicineItem(name="Aspirin", dose="", shape="round", color="white", reminder_times=["09:00"], notes="after food")

    with pytest.raises(Exception):
        MedicineItem(name="Aspirin", dose="1 tablet", shape="triangle", color="white", reminder_times=["09:00"], notes="after food")

    with pytest.raises(Exception):
        MedicineItem(name="Aspirin", dose="1 tablet", shape="round", color="black", reminder_times=["09:00"], notes="after food")


def test_schedule_weekdays_validation_rejects_out_of_range_day():
    with pytest.raises(Exception):
        ScheduleInput(
            parent_id="new",
            mode="nitya",
            messages=[{"time": "08:00", "category": "morning_wish", "type": "checkin", "weekdays": [0, 7]}],
            active=True,
        )
