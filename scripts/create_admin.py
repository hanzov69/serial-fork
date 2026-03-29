"""
Bootstrap the first Owner user by Discord ID.
Run this once after the database has been initialized.

The first user created with this script becomes the Owner (the single superuser).
If an Owner already exists, the script will refuse to create a second one.
If the target user already exists with a lower role, they are upgraded to Owner.

Usage:
    python scripts/create_admin.py <discord_id> <username>

Example:
    python scripts/create_admin.py 123456789012345678 "YourUsername"
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select

from shared.config import Settings
from shared.database import get_session, init_engine
from shared.models import User, UserRole


async def create_owner(discord_id: str, username: str) -> None:
    async with get_session() as session:
        # Check whether an owner already exists
        existing_owner = await session.scalar(
            select(User).where(User.role == UserRole.owner)
        )
        if existing_owner and existing_owner.discord_id != discord_id:
            print(
                f"Error: an Owner already exists ({existing_owner.username} / "
                f"{existing_owner.discord_id}). "
                "Use /transferownership in Discord to transfer the role."
            )
            sys.exit(1)

        result = await session.execute(
            select(User).where(User.discord_id == discord_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                discord_id=discord_id,
                username=username,
                role=UserRole.owner,
            )
            session.add(user)
            print(f"Created new Owner: {username} ({discord_id})")
        else:
            old_role = user.role
            user.role = UserRole.owner
            user.username = username
            print(f"Updated user {username} ({discord_id}): {old_role} -> owner")


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python scripts/create_admin.py <discord_id> <username>")
        sys.exit(1)

    discord_id = sys.argv[1]
    username = sys.argv[2]

    config_path = os.environ.get("CONFIG_PATH", "config.toml")
    settings = Settings.load(config_path)
    init_engine(settings.db_path)

    asyncio.run(create_owner(discord_id, username))
    print("Done.")


if __name__ == "__main__":
    main()
