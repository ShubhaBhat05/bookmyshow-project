from celery import shared_task
from django.db import transaction
from django.utils import timezone
from io import BytesIO

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage
from django.conf import settings
from reportlab.lib.utils import ImageReader

from .models import Payment
from .models import Seat


@shared_task
def release_expired_seats(seat_ids, user_id):
    with transaction.atomic():
        seats = Seat.objects.select_for_update().filter(
            id__in=seat_ids,
            reserved_by_id=user_id,
        )

        now = timezone.now()

        for seat in seats:
            if seat.reserved_until and seat.reserved_until <= now:
                seat.reserved_by = None
                seat.reserved_until = None
                seat.save(
                    update_fields=[
                        'reserved_by',
                        'reserved_until',
                    ]
                )

@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def generate_and_email_ticket(self, payment_id):
    payment = Payment.objects.select_related(
        "user",
        "movie",
        "theater",
    ).prefetch_related(
        "seats"
    ).get(id=payment_id)

    seats = list(payment.seats.all())

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)

    width, height = A4

    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(50, height - 60, "Movie Ticket")

    pdf.setFont("Helvetica", 11)

    y = height - 100

    ticket_details = [
        ("Movie", payment.movie.name),
        ("Theater", payment.theater.name),
        ("City", payment.theater.city),
        ("Screen", payment.theater.screen),
        ("Show Time", payment.theater.time.strftime("%d %b %Y, %I:%M %p")),
        ("Booking ID", str(payment.id)),
        ("Payment Reference", payment.razorpay_payment_id or payment.transaction_id or "N/A"),
        ("Seats", ", ".join(seat.seat_number for seat in seats)),
        ("Amount", f"INR{payment.amount}"),
    ]

    for label, value in ticket_details:
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(50, y, f"{label}:")
        pdf.setFont("Helvetica", 11)
        pdf.drawString(170, y, str(value))
        y -= 25

    qr_data = (
        f"Booking ID: {payment.id}\n"
        f"Movie: {payment.movie.name}\n"
        f"Seats: {', '.join(seat.seat_number for seat in seats)}"
    )

    qr = qrcode.make(qr_data)

    qr_buffer = BytesIO()
    qr.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)

    pdf.drawImage(
        ImageReader(qr_buffer),
        width - 180,
        height - 270,
        width=120,
        height=120,
        preserveAspectRatio=True,
        mask="auto",
    )

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(
        50,
        60,
        "Please present this QR code for ticket verification."
    )

    pdf.save()

    buffer.seek(0)

    filename = f"ticket_{payment.id}.pdf"

    payment.ticket_pdf.save(
        filename,
        ContentFile(buffer.getvalue()),
        save=True,
    )

    email = EmailMessage(
        subject=f"Your Movie Ticket - {payment.movie.name}",
        body=(
            f"Hello {payment.user.username},\n\n"
            f"Your booking for {payment.movie.name} has been confirmed.\n"
            f"Your ticket is attached to this email.\n\n"
            f"Booking ID: {payment.id}\n\n"
            f"Thank you for booking with us."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[payment.user.email],
    )

    email.attach(
        filename,
        buffer.getvalue(),
        "application/pdf",
    )

    email.send(fail_silently=False)
