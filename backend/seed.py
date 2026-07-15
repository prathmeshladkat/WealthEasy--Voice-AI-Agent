"""
seed.py — inserts demo data into the database using the ORM models.

Run this once after `alembic upgrade head`:
    python seed.py

Safe to re-run — checks if data already exists before inserting.
Keep this minimal for now, more users/funds can be added later.
"""

import asyncio
from datetime import date

from sqlalchemy import select

from app.database import async_session_factory
from app.models import CallLog, MutualFund, NavSnapshot, Portfolio, User


# ── Demo users ────────────────────────────────────────────────────────────────

USERS = [
    {"name": "Rajesh Kumar", "phone": "+919876543210", "pan": "ABCPK1234R"},
    {"name": "Priya Sharma", "phone": "+918765432109", "pan": "BCDEF5678S"},
]

# ── Demo funds ────────────────────────────────────────────────────────────────

FUNDS = [
    {
        "fund_name" : "Mirae Asset Large Cap Fund - Direct Growth",
        "short_name": "MIRAE_LC",
        "category"  : "Large Cap",
        "amc_name"  : "Mirae Asset",
        "isin"      : "INF769K01010",
    },
    {
        "fund_name" : "Parag Parikh Flexi Cap Fund - Direct Growth",
        "short_name": "PPFLEXI",
        "category"  : "Flexi Cap",
        "amc_name"  : "PPFAS",
        "isin"      : "INF879O01027",
    },
    {
        "fund_name" : "SBI Small Cap Fund - Direct Growth",
        "short_name": "SBISC",
        "category"  : "Small Cap",
        "amc_name"  : "SBI Mutual Fund",
        "isin"      : "INF200K01158",
    },
]

# ── Portfolios ─────────────────────────────────────────────────────────────────
# Format: (user_phone, fund_short_name, units, avg_nav, sip_amount, sip_date, payments_made, invested, start_date)

PORTFOLIOS = [
    # Rajesh: 2 funds
    ("+919876543210", "MIRAE_LC", 800.0000,   75.00, 5000.00, 10, 12, 60000.00, date(2024, 7, 10)),
    ("+919876543210", "PPFLEXI",  342.8571,   70.00, 3000.00,  5,  8, 24000.00, date(2024, 11, 5)),
    # Priya: 1 fund
    ("+918765432109", "SBISC",    153.8462,  130.00, 2000.00, 15, 10, 20000.00, date(2024, 9, 15)),
]

# ── NAV snapshots ──────────────────────────────────────────────────────────────
# Yesterday CLOSE + today OPEN per fund.
# Enough for the stale-NAV rule to work regardless of what time you run the demo.
# Format: (fund_short_name, nav, snapshot_type, market_date)

today     = date.today()
yesterday = date(today.year, today.month, today.day - 1) if today.day > 1 else date(today.year, today.month - 1, 28)

NAV_SNAPSHOTS = [
    ("MIRAE_LC", 89.50, "CLOSE", yesterday),
    ("MIRAE_LC", 89.80, "OPEN",  today),

    ("PPFLEXI",  79.20, "CLOSE", yesterday),
    ("PPFLEXI",  79.50, "OPEN",  today),

    ("SBISC",   148.00, "CLOSE", yesterday),
    ("SBISC",   149.00, "OPEN",  today),
]


# ── Seed functions ─────────────────────────────────────────────────────────────

async def seed():
    async with async_session_factory() as session:

        # ── Users ──────────────────────────────────────────────────────────────
        for u in USERS:
            existing = await session.scalar(select(User).where(User.phone == u["phone"]))
            if existing:
                print(f"  skip user {u['name']} (already exists)")
                continue
            session.add(User(**u))
            print(f"  added user {u['name']}")

        await session.flush()  # write users to DB so we can reference their IDs below

        # ── Funds ──────────────────────────────────────────────────────────────
        for f in FUNDS:
            existing = await session.scalar(select(MutualFund).where(MutualFund.short_name == f["short_name"]))
            if existing:
                print(f"  skip fund {f['short_name']} (already exists)")
                continue
            session.add(MutualFund(**f))
            print(f"  added fund {f['short_name']}")

        await session.flush()  # write funds before we reference their IDs in portfolios

        # ── Portfolios ─────────────────────────────────────────────────────────
        for phone, short_name, units, avg_nav, sip_amount, sip_date, payments, invested, start in PORTFOLIOS:
            user = await session.scalar(select(User).where(User.phone == phone))
            fund = await session.scalar(select(MutualFund).where(MutualFund.short_name == short_name))

            if not user or not fund:
                print(f"  skip portfolio {phone}/{short_name} (user or fund not found)")
                continue

            existing = await session.scalar(
                select(Portfolio).where(Portfolio.user_id == user.id, Portfolio.fund_id == fund.id)
            )
            if existing:
                print(f"  skip portfolio {phone}/{short_name} (already exists)")
                continue

            session.add(Portfolio(
                user_id           = user.id,
                fund_id           = fund.id,
                units_held        = units,
                avg_nav           = avg_nav,
                sip_amount        = sip_amount,
                sip_date          = sip_date,
                sip_payments_made = payments,
                invested_amount   = invested,
                start_date        = start,
            ))
            print(f"  added portfolio {phone} → {short_name}")

        # ── NAV snapshots ──────────────────────────────────────────────────────
        for short_name, nav, snap_type, market_date in NAV_SNAPSHOTS:
            fund = await session.scalar(select(MutualFund).where(MutualFund.short_name == short_name))
            if not fund:
                print(f"  skip NAV {short_name} (fund not found)")
                continue

            existing = await session.scalar(
                select(NavSnapshot).where(
                    NavSnapshot.fund_id       == fund.id,
                    NavSnapshot.market_date   == market_date,
                    NavSnapshot.snapshot_type == snap_type,
                )
            )
            if existing:
                print(f"  skip NAV {short_name} {snap_type} {market_date} (already exists)")
                continue

            session.add(NavSnapshot(
                fund_id       = fund.id,
                nav           = nav,
                snapshot_type = snap_type,
                market_date   = market_date,
            ))
            print(f"  added NAV {short_name} {snap_type} {market_date}")

        await session.commit()
        print("\nSeed complete.")


if __name__ == "__main__":
    asyncio.run(seed())