from fastapi import FastAPI, HTTPException
from fastapi import Request, Header
from fastapi.responses import Response
import os
import logging
from chainlit.utils import mount_chainlit
import stripe
from license_management import update_paid_amount
from stripe import SignatureVerificationError


app = FastAPI()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

@app.post("/stripe_webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    payload = await request.body()
    event = None
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header.")

    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, os.environ['STRIPE_WEBHOOK_SIGNING_KEY']
        )
    except SignatureVerificationError as e:
        print(f"Signature verification failed: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid signature.")
    except Exception as e:
        print(f"Error constructing event: {str(e)}")
        raise HTTPException(status_code=400, detail="Error processing webhook.")

    if not event:
        raise HTTPException(status_code=400, detail="Invalid event.")

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        client_reference_id = session.get('client_reference_id')
        payment_link_id = session.get('payment_link')
        amount = 0
        if payment_link_id == os.environ['PAYMENT_LINK_ID_25']:
            amount = 25
        if client_reference_id and amount:
            logger.info(f"Client reference ID: {client_reference_id}, Amount: {amount}")
            await update_paid_amount(client_reference_id, amount)
        else:
            logger.error(f"Invalid client reference ID or amount: {client_reference_id}, {amount}")


mount_chainlit(app=app, target="app.py", path="/")

