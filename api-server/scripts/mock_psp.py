from __future__ import annotations

import hashlib
import hmac
import os

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request

app = FastAPI(title="mock-psp")
PSP_NAME = os.getenv("PSP_NAME", "generic")


@app.get("/health")
async def health():
    return {"status": "ok", "psp": PSP_NAME}


@app.post("/api/generate_payment")
async def flouci_generate():
    return {"result": {"payment_id": "fl-test-1", "link": "https://sandbox.flouci.test/checkout/fl-test-1"}}


@app.get("/api/verify_payment/{payment_ref}")
async def flouci_verify(payment_ref: str):
    return {"result": {"status": "SUCCESS", "payment_id": payment_ref}}


@app.post("/api/v2/payments/init-payment")
async def konnect_init():
    return {"paymentRef": "kn-test-1", "payUrl": "https://sandbox.konnect.test/pay/kn-test-1"}


@app.get("/api/v2/payments/{payment_ref}")
async def konnect_get(payment_ref: str):
    return {"payment": {"paymentRef": payment_ref, "status": "completed"}}


@app.post("/api/v2/payments/create")
async def paymee_create():
    return {"data": {"token": "pm-test-1", "payment_url": "https://sandbox.paymee.test/pay/pm-test-1"}}


@app.post("/sign")
async def sign(request: Request, x_secret: str | None = Header(None)):
    if not x_secret:
        raise HTTPException(status_code=400, detail="x-secret required")
    body = await request.body()
    digest = hmac.new(x_secret.encode(), body, hashlib.sha256).hexdigest()
    return {"signature": digest}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PSP_PORT", "8011")))
