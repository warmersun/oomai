import os
from typing import Optional

import asyncpg


async def upsert_client_reference_id(client_reference_id: str,
                                     user_identifier: str) -> bool:
    """UPSERT client_reference_id for a user."""
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        row = await conn.fetchrow(
            """
          INSERT INTO license_mgmt (username, client_reference_id, paid_amount) 
          VALUES ($1, $2, 0)
          ON CONFLICT (username)
          DO UPDATE SET client_reference_id = EXCLUDED.client_reference_id
          RETURNING (xmax =0) AS inserted;
          """, user_identifier, client_reference_id)
        return row["inserted"]
    finally:
        await conn.close()


async def update_paid_amount(client_reference_id: str, amount: int) -> bool:
    """UPDATE paid amount for a client_reference_id."""
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        await conn.execute(
            """
            UPDATE license_mgmt
            SET paid_amount = paid_amount + $2
            WHERE client_reference_id = $1
            """, client_reference_id, amount)
        return True
    except Exception as e:
        print(f"Error upserting paid status: {str(e)}")
        return False
    finally:
        await conn.close()


async def get_paid_amount_left(user_identifier: str) -> Optional[int]:
    """GET paid amount left for a client_reference_id."""
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        result = await conn.fetchrow(
            "SELECT paid_amount FROM license_mgmt WHERE username = $1",
            user_identifier)
        return result["paid_amount"] if result else None
    finally:
        await conn.close()


async def use_up_paid_amount(user_identifier: str, amount: int) -> bool:
    """decrement paid amount for a user."""
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        await conn.execute(
            """
            UPDATE license_mgmt
            SET paid_amount = paid_amount - $2
            WHERE username = $1
            """, user_identifier, amount)
        return True
    except Exception as e:
        print(f"Error decrementing paid amount: {str(e)}")
        return False
    finally:
        await conn.close()
