
import asyncio
import os
import sys

# Setup environment
os.environ["ENV"] = "production"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://autocommerce:autocommerce_pass@localhost/autocommerce"

# Add current directory to path
sys.path.append(os.getcwd())

from services.ai_guardrails import check_tenant_credit, deduct_tenant_credit, get_tenant_credit_stats


async def run_test():
    STORE_ID = 3 # Demo store ID from seed
    
    print(f"--- Testing AI Credit Fallback for Store {STORE_ID} ---")
    
    # 1. Initial stats
    stats = await get_tenant_credit_stats(STORE_ID)
    print(f"Initial stats: {stats}")
    
    # 2. Consume credits until 0
    remaining = stats['remaining']
    print(f"Consuming {remaining} credits...")
    await deduct_tenant_credit(STORE_ID, cost=remaining)
    
    # 3. Check if blocked
    stats = await get_tenant_credit_stats(STORE_ID)
    print(f"Stats after consumption: {stats}")
    
    can_use = await check_tenant_credit(STORE_ID, cost=1)
    print(f"Can use 1 more credit? {can_use}")
    
    if not can_use:
        print("✅ SUCCESS: AI is blocked when credits are exhausted (Memory Fallback works)")
    else:
        print("❌ FAILURE: AI is NOT blocked even when credits are exhausted")

if __name__ == "__main__":
    asyncio.run(run_test())
