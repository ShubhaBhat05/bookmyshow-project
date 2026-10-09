from decimal import Decimal
from urllib.parse import urlparse, parse_qs

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, URLValidator
from django.db import models
from django.db.models import Avg
from django.utils import timezone


class Genre(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Language(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Movie(models.Model):
    CERTIFICATION_CHOICES = [
        ("U", "U"),
        ("UA", "UA"),
        ("A", "A"),
        ("S", "S"),
    ]

    name = models.CharField(max_length=255)
    image = models.ImageField(upload_to="movies/")
    rating = models.DecimalField(
        max_digits=3,
        decimal_places=1,
        default=Decimal("0.0"),
        validators=[
            MinValueValidator(Decimal("0.0")),
            MaxValueValidator(Decimal("5.0")),
        ],
    )

    genres = models.ManyToManyField(
        Genre,
        related_name="movies",
        blank=True,
    )

    languages = models.ManyToManyField(
        Language,
        related_name="movies",
        blank=True,
    )

    cast = models.TextField()
    description = models.TextField(blank=True, null=True)

    certification = models.CharField(
        max_length=2,
        choices=CERTIFICATION_CHOICES,
        default="U",
    )

    duration_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    trailer_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        validators=[
            URLValidator(schemes=["http", "https"])
        ],
    )

    release_date = models.DateField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-release_date", "-created_at"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()

        if self.trailer_url:
            parsed_url = urlparse(self.trailer_url)
            allowed_hosts = {
                "youtube.com",
                "www.youtube.com",
                "m.youtube.com",
                "youtu.be",
                "www.youtu.be",
            }

            if parsed_url.netloc.lower() not in allowed_hosts:
                raise ValidationError({
                    "trailer_url": "Only YouTube trailer URLs are allowed."
                })

    @property
    def trailer_embed_url(self):
        if not self.trailer_url:
            return None

        parsed_url = urlparse(self.trailer_url)
        hostname = parsed_url.netloc.lower()

        video_id = None

        if hostname in {"youtu.be", "www.youtu.be"}:
            video_id = parsed_url.path.strip("/").split("/")[0]

        elif hostname in {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
        }:
            if parsed_url.path == "/watch":
                video_id = parse_qs(parsed_url.query).get("v", [None])[0]

            elif parsed_url.path.startswith("/embed/"):
                video_id = parsed_url.path.split("/embed/")[1].split("/")[0]

            elif parsed_url.path.startswith("/shorts/"):
                video_id = parsed_url.path.split("/shorts/")[1].split("/")[0]

        if not video_id:
            return None

        return "https://www.youtube-nocookie.com/embed/{}".format(video_id)


class MoviePoster(models.Model):
    movie = models.ForeignKey(
        Movie,
        on_delete=models.CASCADE,
        related_name="posters",
    )
    image = models.ImageField(upload_to="movies/posters/")
    caption = models.CharField(
        max_length=255,
        blank=True,
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return "{} poster".format(self.movie.name)


class Theater(models.Model):
    name = models.CharField(max_length=255)
    city = models.CharField(max_length=100, blank=True, default="", db_index=True)
    screen = models.CharField(max_length=50, default="Screen 1")
    movie = models.ForeignKey(Movie,on_delete=models.CASCADE,related_name="theaters")

    time = models.DateTimeField()
    ticket_price = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=200.00,
    )

    class Meta:
        ordering = ["time"]

    def __str__(self):
        return "{} - {} at {}".format(
            self.name,
            self.movie.name,
            self.time,
        )


class Seat(models.Model):
    theater = models.ForeignKey(
        Theater,
        on_delete=models.CASCADE,
        related_name="seats",
    )

    seat_number = models.CharField(max_length=10)

    is_booked = models.BooleanField(default=False)
    reserved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reserved_seats",
    )

    reserved_until = models.DateTimeField(
        null=True,
        blank=True,
    )
    def __str__(self):
        return "{} in {}".format(
            self.seat_number,
            self.theater.name,
        )


class Booking(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="bookings",
    )

    seat = models.OneToOneField(
        Seat,
        on_delete=models.CASCADE,
    )

    movie = models.ForeignKey(
        Movie,
        on_delete=models.CASCADE,
        related_name="bookings",
    )

    theater = models.ForeignKey(
        Theater,
        on_delete=models.CASCADE,
        related_name="bookings",
    )
    payment = models.ForeignKey(
        "Payment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bookings",
    )
    booked_at = models.DateTimeField(auto_now_add=True)
    history_hidden = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["movie", "booked_at"]),
            models.Index(fields=["user", "movie"]),
            models.Index(fields=["booked_at"]),

        ]

    def __str__(self):
        return "Booking by {} for {} at {}".format(
            self.user.username,
            self.seat.seat_number,
            self.theater.name,
        )

    @property
    def show_has_finished(self):
        return self.theater.time <= timezone.now()


class Review(models.Model):
    movie = models.ForeignKey(
        Movie,
        on_delete=models.CASCADE,
        related_name="reviews",
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="movie_reviews",
    )

    rating = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(1),
            MaxValueValidator(5),
        ]
    )

    title = models.CharField(
        max_length=200,
        blank=True,
    )

    comment = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["movie", "user"],
                name="unique_movie_review_per_user",
            )
        ]
        indexes = [
            models.Index(fields=["movie", "created_at"]),
            models.Index(fields=["movie", "rating"]),
        ]

    def __str__(self):
        return "{} - {} - {}".format(
            self.movie.name,
            self.user.username,
            self.rating,
        )

    @property
    def is_verified_viewer(self):
        return Booking.objects.filter(
            user=self.user,
            movie=self.movie,
            theater__time__lte=timezone.now(),
        ).exists()

    def save(self, *args, **kwargs):
        movie = self.movie

        super().save(*args, **kwargs)

        average = Review.objects.filter(
            movie=movie
        ).aggregate(
            average_rating=Avg("rating")
        )["average_rating"]

        movie.rating = (
            Decimal(str(average)).quantize(Decimal("0.1"))
            if average is not None
            else Decimal("0.0")
        )

        Movie.objects.filter(pk=movie.pk).update(
            rating=movie.rating
        )

    def delete(self, *args, **kwargs):
        movie = self.movie

        result = super().delete(*args, **kwargs)

        if Movie.objects.filter(pk=movie.pk).exists():
            average = Review.objects.filter(
                movie=movie
            ).aggregate(
                average_rating=Avg("rating")
            )["average_rating"]

            movie.rating = (
                Decimal(str(average)).quantize(Decimal("0.1"))
                if average is not None
                else Decimal("0.0")
            )

            Movie.objects.filter(pk=movie.pk).update(
                rating=movie.rating
            )

        return result


class ReviewReport(models.Model):
    REASON_CHOICES = [
        ("spam", "Spam"),
        ("offensive", "Offensive content"),
        ("misleading", "Misleading information"),
        ("other", "Other"),
    ]

    review = models.ForeignKey(
        Review,
        on_delete=models.CASCADE,
        related_name="reports",
    )

    reported_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="review_reports",
    )

    reason = models.CharField(
        max_length=30,
        choices=REASON_CHOICES,
    )

    details = models.TextField(
        blank=True,
    )

    is_resolved = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["review", "reported_by"],
                name="unique_review_report_per_user",
            )
        ]

    def __str__(self):
        return "Report by {} on review {}".format(
            self.reported_by.username,
            self.review.id,
        )

class Payment(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ("pay_now", "Pay Now"),
        ("wallet", "Wallet"),
        ("pay_later", "Pay Later"),
    ]

    STATUS_CHOICES = [
        ("created", "Created"),
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
        ("refunded", "Refunded"),
    ]
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="payments",
    )

    movie = models.ForeignKey(
        Movie,
        on_delete=models.CASCADE,
        related_name="payments",
    )

    theater = models.ForeignKey(
        Theater,
        on_delete=models.CASCADE,
        related_name="payments",
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default="pay_now",
    )

    razorpay_order_id = models.CharField(
        max_length=255,
        unique=True,
    )

    razorpay_payment_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
    )

    transaction_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
    )

    ticket_pdf = models.FileField(
    upload_to="tickets/",
    blank=True,
    null=True,
)

    razorpay_signature = models.CharField(
        max_length=500,
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="created",
    )
    history_hidden = models.BooleanField(default=False)
    seats = models.ManyToManyField(
        Seat,
        related_name="payments",
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "{} - {} - {}".format(
            self.user.username,
            self.razorpay_order_id,
            self.status,
        )
    class Meta:
        indexes = [
            models.Index(
                fields=["status", "created_at"],
                name="payment_status_created_idx",
            ),
        ]
class Wallet(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="wallet",
    )

    balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return f"{self.user.username} - ₹{self.balance}"