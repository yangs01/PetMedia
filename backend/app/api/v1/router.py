from fastapi import APIRouter

from app.api.v1.endpoints import (
    approvals,
    assets,
    brands,
    exports,
    health,
    products,
    reviews,
    tasks,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(products.router)
api_router.include_router(brands.router)
api_router.include_router(reviews.router)
api_router.include_router(tasks.router)
api_router.include_router(approvals.router)
api_router.include_router(assets.router)
api_router.include_router(exports.router)
