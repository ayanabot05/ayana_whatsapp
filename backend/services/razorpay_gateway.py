"""Razorpay's SDK is server-only. Signing secret never appears in API responses."""
import asyncio
import hashlib
import hmac
import os
import razorpay
from fastapi import HTTPException


def enabled():
    return os.environ.get('RAZORPAY_ENABLED','').lower()=='true'


def test_mode():
    return os.environ.get('RAZORPAY_KEY_ID','').startswith('rzp_test_')


def client():
    key, secret = os.environ.get('RAZORPAY_KEY_ID'),os.environ.get('RAZORPAY_KEY_SECRET')
    if not enabled() or not key or not secret:
        raise HTTPException(503,'Payment checkout is not configured yet.')
    if test_mode() and os.environ.get('APP_ENV')!='test':
        raise HTTPException(503,'Test payment keys cannot grant paid access in a production environment.')
    return razorpay.Client(auth=(key,secret),timeout=20)


async def create_order(amount,currency,receipt,user_id):
    return await asyncio.to_thread(client().order.create,{'amount':amount,'currency':currency,'receipt':receipt,'partial_payment':False,'notes':{'account_id':str(user_id)}})


async def fetch_payment(payment_id):
    return await asyncio.to_thread(client().payment.fetch,payment_id)


async def fetch_order(order_id):
    return await asyncio.to_thread(client().order.fetch,order_id)


async def order_payments(order_id):
    return await asyncio.to_thread(client().order.payments,order_id)


def valid_signature(order_id,payment_id,signature):
    secret = os.environ.get('RAZORPAY_KEY_SECRET')
    if not secret:
        raise HTTPException(503,'Payment verification is not configured.')
    expected = hmac.new(secret.encode(),f'{order_id}|{payment_id}'.encode(),hashlib.sha256).hexdigest()
    return bool(signature) and hmac.compare_digest(expected,signature)