import razorpay
from django.conf import settings


def get_razorpay_client():
    return razorpay.Client(
        auth=(
            settings.RAZORPAY_KEY_ID,
            settings.RAZORPAY_KEY_SECRET,
        )
    )


def create_razorpay_order(amount, receipt):
    client = get_razorpay_client()

    order = client.order.create(
        {
            "amount": int(amount * 100),
            "currency": "INR",
            "receipt": receipt,
        }
    )

    return order
def verify_payment_signature(order_id, payment_id, signature):
    client = get_razorpay_client()

    client.utility.verify_payment_signature(
        {
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        }
    )

    return True
def verify_webhook_signature(payload, signature, webhook_secret):
    client = get_razorpay_client()

    client.utility.verify_webhook_signature(
        payload,
        signature,
        webhook_secret,
    )

    return True