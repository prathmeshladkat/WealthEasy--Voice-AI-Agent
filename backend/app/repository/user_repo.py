from typing import Optional 
from sqlalchemy import select
from app.database import get_db_session
from app.models import User 

async def get_user_by_phone(phone: str) -> Optional[User]:
    """
    Look up a user by their phone number.
    Returns the User object if found, None if not found
    """
    async with get_db_session() as session:
        result = await session.execute(
            select(User).where(User.phone == phone)
        )
        return result.scalar_one_or_none() 
        # return a single user object if found returns none if not found
    

async def get_user_by_phone_and_pan(phone: str, pan: str) -> Optional[User]:
    """
    Look up a user where BOTH phone AND pan match.
    Returns User if both match the same row, None otherwise.
 
    Called during VERIFY_PAN state.
    If this returns None → PAN doesn't match the phone → verification failed.
    """
    async with get_db_session() as session:
        result = await session.execute(
            select(User).where(
                User.phone == phone,
                User.pan   == pan,      # SQLAlchemy treats multiple .where() args as AND
            )
        )
        return result.scalar_one_or_none()