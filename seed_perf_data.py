
import os
import time
import django

os.environ["DJANGO_SETTINGS_MODULE"] = "bookmyseat.perf_settings"
django.setup()

from django.db import connection, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from movies.models import Movie, Theater, Seat, Booking, Payment

BOOKING_COUNT = 100_000
BATCH_SIZE = 5_000
USER_COUNT = 100
THEATER_COUNT = 100


def main():
    if connection.settings_dict["NAME"] != "bookmyshow_perf_test":
        raise RuntimeError("Wrong database. Stopping for safety.")

    if Booking.objects.exists():
        raise RuntimeError(
            "The test database already contains bookings. Stopping to avoid duplicates."
        )

    start_time = time.time()
    now = timezone.now()

    with transaction.atomic():
        users = []
        for i in range(USER_COUNT):
            users.append(
                User(
                    username=f"perf_user_{i}",
                    email=f"perf_user_{i}@example.com",
                )
            )
        User.objects.bulk_create(users, batch_size=BATCH_SIZE)
        users = list(
            User.objects.filter(username__startswith="perf_user_").order_by("username")
        )

        movie = Movie.objects.create(
            name="Performance Test Movie",
            image="movies/perf_test.jpg",
            cast="Performance Test Cast",
            description="Synthetic movie used only for database performance testing.",
            duration_minutes=120,
        )

        theaters = [
            Theater(
                name=f"Performance Theater {i:03d}",
                movie=movie,
                time=now,
                ticket_price=200,
            )
            for i in range(THEATER_COUNT)
        ]
        Theater.objects.bulk_create(theaters, batch_size=BATCH_SIZE)
        theaters = list(
            Theater.objects.filter(
                name__startswith="Performance Theater "
            ).order_by("name")
        )

        for start in range(0, BOOKING_COUNT, BATCH_SIZE):
            stop = min(start + BATCH_SIZE, BOOKING_COUNT)
            indices = range(start, stop)

            seat_numbers = [f"PERF{i:06d}" for i in indices]

            Seat.objects.bulk_create(
                [
                    Seat(
                        theater=theaters[i % THEATER_COUNT],
                        seat_number=f"PERF{i:06d}",
                        is_booked=True,
                    )
                    for i in range(start, stop)
                ],
                batch_size=BATCH_SIZE,
            )

            seat_map = {
                seat.seat_number: seat
                for seat in Seat.objects.filter(
                    seat_number__in=seat_numbers
                )
            }

            order_ids = [f"perf_order_{i}" for i in range(start, stop)]

            Payment.objects.bulk_create(
                [
                    Payment(
                        user=users[i % USER_COUNT],
                        movie=movie,
                        theater=theaters[i % THEATER_COUNT],
                        amount=200,
                        razorpay_order_id=f"perf_order_{i}",
                        status=(
                            "cancelled" if i % 1000 == 0
                            else "refunded" if i % 1000 == 1
                            else "success"
                        ),
                    )
                    for i in range(start, stop)
                ],
                batch_size=BATCH_SIZE,
            )

            payment_map = {
                payment.razorpay_order_id: payment
                for payment in Payment.objects.filter(
                    razorpay_order_id__in=order_ids
                ).only("id", "razorpay_order_id")
            }

            Booking.objects.bulk_create(
                [
                    Booking(
                        user=users[i % USER_COUNT],
                        seat=seat_map[f"PERF{i:06d}"],
                        movie=movie,
                        theater=theaters[i % THEATER_COUNT],
                        payment=payment_map[f"perf_order_{i}"],
                    )
                    for i in range(start, stop)
                ],
                batch_size=BATCH_SIZE,
            )

            print(f"Prepared {stop:,} of {BOOKING_COUNT:,} bookings")

    elapsed = time.time() - start_time

    print("\nPerformance test data created successfully.")
    print(f"Database: {connection.settings_dict['NAME']}")
    print(f"Bookings: {Booking.objects.count():,}")
    print(f"Payments: {Payment.objects.count():,}")
    print(f"Seats: {Seat.objects.count():,}")
    print(f"Elapsed time: {elapsed:.2f} seconds")


if __name__ == "__main__":
    main()