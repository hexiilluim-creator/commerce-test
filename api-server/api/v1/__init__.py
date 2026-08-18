from fastapi import APIRouter

from .ai import router as ai_router
from .analytics import router as analytics_router
from .appointments import router as appointments_router
from .auth import router as auth_router
from .b2b_portal import router as b2b_portal_router
from .billing import router as billing_router
from .blueprints import router as blueprints_router
from .conversations import router as conversations_router
from .credits import router as credits_router
from .credits_admin import router as credits_admin_router
from .dashboard_enterprise import router as dashboard_enterprise_router
from .expenses import router as expenses_router
from .integrations import router as integrations_router
from .internal_ops import router as internal_ops_router
from .loyalty_ia import router as loyalty_ia_router
from .omnicall_enterprise import router as omnicall_enterprise_router
from .omnicall_v9_admin import router as omnicall_router
from .ops_admin import router as ops_admin_router
from .orders import router as orders_router
from .payment_links import router as payment_links_router
from .payments import router as payments_router
from .predictive_restocking import router as predictive_restocking_router
from .product_images import router as product_images_router
from .promotions import router as promotions_router
from .settings import router as settings_router
from .social import router as social_router
from .social_broadcast import router as social_broadcast_router
from .social_webhooks import router as social_webhooks_router
from .stock import router as stock_router
from .storefront import router as storefront_router
from .stores import router as stores_router  # CTO audit: /stores/me
from .super_admin import router as super_admin_router
from .tax import router as tax_router
from .visual_builder import router as visual_builder_router
from .whatsapp import router as whatsapp_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(whatsapp_router)
router.include_router(payments_router)
router.include_router(orders_router)
router.include_router(stock_router)
from .stock import router_stock_alias

router.include_router(router_stock_alias)
router.include_router(ai_router)
router.include_router(settings_router)
router.include_router(conversations_router)
router.include_router(billing_router)
router.include_router(payment_links_router)
router.include_router(analytics_router)
router.include_router(appointments_router)
router.include_router(expenses_router)
router.include_router(super_admin_router)
router.include_router(social_router)
router.include_router(social_broadcast_router)
router.include_router(social_webhooks_router)
router.include_router(credits_router)
router.include_router(credits_admin_router)
router.include_router(omnicall_router)
router.include_router(ops_admin_router)
router.include_router(integrations_router)
router.include_router(internal_ops_router)
router.include_router(product_images_router)
router.include_router(promotions_router)
router.include_router(stores_router)  # CTO audit: /stores/me
router.include_router(storefront_router)
router.include_router(tax_router)
router.include_router(blueprints_router)  # FIX: was not included
router.include_router(visual_builder_router)
router.include_router(predictive_restocking_router)
router.include_router(loyalty_ia_router)
router.include_router(b2b_portal_router)
router.include_router(omnicall_enterprise_router)
router.include_router(dashboard_enterprise_router)
# NOTE: health_router est monté directement dans main.py (sans prefix /api/v1)
