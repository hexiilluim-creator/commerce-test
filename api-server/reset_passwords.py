
import asyncio
import os
import sys

# Setup environment
os.environ["ENV"] = "production"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://autocommerce:autocommerce_pass@localhost/autocommerce"

# Add current directory to path
sys.path.append(os.getcwd())

from sqlalchemy import select

from api.v1.auth import hash_password
from models.database import AsyncSessionLocal, User


async def reset():
    async with AsyncSessionLocal() as db:
        # Reset Admin
        res = await db.execute(select(User).where(User.email == 'admin@autocommerce.tn'))
        u = res.scalar_one_or_none()
        if u:
            u.hashed_password = hash_password('admin_pass_123')
            print(f"Resetting password for {u.email} to admin_pass_123")
        
        # Reset SuperAdmin
        res = await db.execute(select(User).where(User.email == 'superadmin@autocommerce.tn'))
        u = res.scalar_one_or_none()
        if u:
            u.hashed_password = hash_password('super_pass_123')
            print(f"Resetting password for {u.email} to super_pass_123")
            
        await db.commit()
        print("Password reset commit success")

if __name__ == "__main__":
    asyncio.run(reset())
