import asyncio
import logging
import os
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from models.database import Customer, Order, OrderStatus, Product, Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s [seed_full] %(message)s")
log = logging.getLogger("seed_full")

RAW_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://autocommerce:autocommerce_pass@localhost/autocommerce",
)


def _to_async_url(url: str) -> str:
    """V8 FIX : réécrit automatiquement les drivers sync vers async.

    Le projet est passé à ``asyncpg``. Si l'opérateur a laissé
    ``postgresql+psycopg2://`` ou ``postgresql+psycopg://`` dans son ``.env``,
    ``create_async_engine`` lève une erreur. On force ici le driver async**avant**
    de tenter la création du moteur.
    """
    replacements = (
        ("postgresql+psycopg2", "postgresql+asyncpg"),
        ("postgresql+psycopg", "postgresql+asyncpg"),
        # postgres:// (libpq url without driver) → assume asyncpg
        # only if no driver prefix is present already
    )
    new = url
    for src, dst in replacements:
        if new.startswith(src):
            new = dst + new[len(src):]
            break
    if new.startswith("postgres://"):
        new = "postgresql+asyncpg://" + new[len("postgres://"):]
    elif new.startswith("postgresql://") and "+" not in new.split("://", 1)[0]:
        new = "postgresql+asyncpg://" + new[len("postgresql://"):]
    return new


DATABASE_URL = _to_async_url(RAW_DATABASE_URL)
if DATABASE_URL != RAW_DATABASE_URL:
    log.warning(
        "rewrote DATABASE_URL: %s -> %s (driver migration psycopg2 → asyncpg)",
        RAW_DATABASE_URL.split("@")[-1],
        DATABASE_URL.split("@")[-1],
    )
log.info("Using async driver: asyncpg (%s)", DATABASE_URL.split("@")[-1])


async def seed():
    # V8 FIX : driver asyncpg garanti (cf. _to_async_url).
    engine = create_async_engine(DATABASE_URL, echo=False, future=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # 1. Récupérer la boutique
        result = await session.execute(select(Store).where(Store.slug == "demo-store"))
        store = result.scalar_one_or_none()
        if not store:
            print("Store demo-store not found. Please run seed_production.py first.")
            return

        # 2. Ajouter des produits
        products_data = [
            {"name": "iPhone 15 Pro", "price": 4500.0, "category": "Électronique", "stock_qty": 10},
            {"name": "MacBook Air M2", "price": 3800.0, "category": "Électronique", "stock_qty": 5},
            {"name": "AirPods Pro 2", "price": 850.0, "category": "Accessoires", "stock_qty": 20},
            {"name": "Samsung S24 Ultra", "price": 4200.0, "category": "Électronique", "stock_qty": 8},
            {"name": "Coque iPhone", "price": 50.0, "category": "Accessoires", "stock_qty": 50},
        ]
        
        for p_data in products_data:
            result = await session.execute(select(Product).where(Product.name == p_data["name"], Product.store_id == store.id))
            if not result.scalar_one_or_none():
                product = Product(
                    store_id=store.id,
                    name=p_data["name"],
                    price=p_data["price"],
                    category=p_data["category"],
                    stock_qty=p_data["stock_qty"],
                    is_active=True
                )
                session.add(product)
        
        # 3. Ajouter des clients
        customers_data = [
            {"name": "Ahmed Ben Salem", "phone": "21698765432"},
            {"name": "Sonia Mansour", "phone": "21655123456"},
            {"name": "Yassine Dridi", "phone": "21622333444"},
        ]
        
        customers = []
        for c_data in customers_data:
            result = await session.execute(select(Customer).where(Customer.whatsapp_phone == c_data["phone"], Customer.store_id == store.id))
            customer = result.scalar_one_or_none()
            if not customer:
                customer = Customer(
                    store_id=store.id,
                    whatsapp_phone=c_data["phone"],
                    name=c_data["name"],
                    channel="whatsapp"
                )
                session.add(customer)
                await session.flush()
            customers.append(customer)

        # 4. Ajouter des commandes
        if customers:
            orders_data = [
                {"customer": customers[0], "status": OrderStatus.PAID, "total": 4550.0},
                {"customer": customers[1], "status": OrderStatus.PENDING, "total": 850.0},
                {"customer": customers[2], "status": OrderStatus.DELIVERED, "total": 3800.0},
            ]
            
            for o_data in orders_data:
                order = Order(
                    store_id=store.id,
                    customer_id=o_data["customer"].id,
                    status=o_data["status"],
                    total_amount=o_data["total"],
                    items=[{"product_id": 1, "name": "Test Item", "qty": 1, "unit_price": o_data["total"]}],
                    created_at=datetime.now() - timedelta(days=2)
                )
                session.add(order)

        await session.commit()
        print("Full seeding completed successfully.")
    
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(seed())
