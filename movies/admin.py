from django.contrib import admin,messages
from django import forms
from django.db import transaction
from django.core.exceptions import ValidationError
from .models import Movie, Theater, Seat, Booking, Payment,Wallet
from django.utils import timezone
from datetime import timedelta
from .models import (
    Genre,
    Language,
    Movie,
    MoviePoster,
    Theater,
    Seat,
    Booking,
    Payment,
    Review,
    ReviewReport,
)


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]


class MoviePosterInline(admin.TabularInline):
    model = MoviePoster
    extra = 1


@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "rating",
        "certification",
        "duration_minutes",
        "release_date",
    ]

    list_filter = [
        "certification",
        "genres",
        "languages",
        "release_date",
    ]

    search_fields = [
        "name",
        "cast",
        "description",
    ]

    filter_horizontal = [
        "genres",
        "languages",
    ]

    inlines = [MoviePosterInline]

    readonly_fields = [
        "rating",
        "created_at",
        "updated_at",
    ]


@admin.register(MoviePoster)
class MoviePosterAdmin(admin.ModelAdmin):
    list_display = [
        "movie",
        "caption",
        "uploaded_at",
    ]

    search_fields = [
        "movie__name",
        "caption",
    ]


@admin.register(Theater)
class TheaterAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "city",
        "screen",
        "movie",
        "time",
    ]

    list_filter = [
        "city",
        "movie",
        "time",
    ]

    search_fields = [
        "name",
        "city",
        "screen",
        "movie__name",
    ]


class SeatBulkAddForm(forms.ModelForm):
    seat_prefix = forms.CharField(
        max_length=5,
        label="Seat prefix",
        help_text="Example: A, B, C",
    )

    seat_count = forms.IntegerField(
        min_value=1,
        max_value=500,
        label="Number of seats",
        help_text="Example: 10, 50, 100",
    )

    class Meta:
        model = Seat
        fields = [
            "theater",
            "seat_prefix",
            "seat_count",
        ]

    def clean_seat_prefix(self):
        prefix = self.cleaned_data["seat_prefix"].strip().upper()

        if not prefix:
            raise ValidationError("Seat prefix cannot be empty.")

        return prefix

    def clean(self):
        cleaned_data = super().clean()

        theater = cleaned_data.get("theater")
        prefix = cleaned_data.get("seat_prefix")
        count = cleaned_data.get("seat_count")

        if theater and prefix and count:
            seat_numbers = [
                f"{prefix}{number}"
                for number in range(1, count + 1)
            ]

            existing = Seat.objects.filter(
                theater=theater,
                seat_number__in=seat_numbers,
            ).values_list("seat_number", flat=True)

            if existing:
                raise ValidationError(
                    "These seats already exist for this theater: "
                    + ", ".join(existing)
                )

        return cleaned_data


@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = [
        "theater",
        "seat_number",
        "seat_status",
        "reserved_by",
        "reserved_until",
    ]

    list_filter = [
        "theater",
        "is_booked",
    ]

    search_fields = [
        "seat_number",
        "theater__name",
        "reserved_by__username",
    ]

    actions = [
        "reserve_selected_seats",
        "release_selected_reservations",
    ]

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            return SeatBulkAddForm

        return super().get_form(request, obj, **kwargs)

    def seat_status(self, obj):
        if obj.is_booked:
            return "Booked"

        if (
        obj.reserved_by
        and (
            obj.reserved_until is None
            or obj.reserved_until > timezone.now()
        )
    ):
           return "Reserved"

        return "Available"

    seat_status.short_description = "Status"

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
            return

        theater = form.cleaned_data["theater"]
        prefix = form.cleaned_data["seat_prefix"]
        count = form.cleaned_data["seat_count"]

        seats = [
            Seat(
                theater=theater,
                seat_number=f"{prefix}{number}",
                is_booked=False,
            )
            for number in range(1, count + 1)
        ]

        Seat.objects.bulk_create(seats)

        obj.pk = seats[0].pk
        obj.theater = theater
        obj.seat_number = seats[0].seat_number
        obj.is_booked = False

    @admin.action(description="Reserve selected seats")
    def reserve_selected_seats(self, request, queryset):

        booked_seats = queryset.filter(is_booked=True)

        if booked_seats.exists():
            self.message_user(
                request,
                "Booked seats cannot be reserved.",
                level=messages.ERROR,
            )
            return

        count = queryset.filter(
            is_booked=False
        ).update(
            reserved_by=request.user,
            reserved_until=None,
        )

        self.message_user(
            request,
            f"{count} seat(s) reserved by admin.",
            level=messages.SUCCESS,
        )
    

    @admin.action(description="Release selected reservations")
    def release_selected_reservations(self, request, queryset):

        count = queryset.filter(
            is_booked=False,
        ).update(
            reserved_by=None,
            reserved_until=None,
        )

        self.message_user(
            request,
            f"{count} reservation(s) released.",
            level=messages.SUCCESS,
        )

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "movie",
        "theater",
        "seat",
        "booked_at",
    ]

    list_filter = [
        "movie",
        "theater",
        "booked_at",
    ]

    search_fields = [
        "user__username",
        "movie__name",
        "theater__name",
        "seat__seat_number",
    ]

    readonly_fields = [
        "booked_at",
    ]


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = [
        "movie",
        "user",
        "rating",
        "is_verified_viewer",
        "created_at",
        "updated_at",
    ]

    list_filter = [
        "rating",
        "created_at",
        "updated_at",
    ]

    search_fields = [
        "movie__name",
        "user__username",
        "title",
        "comment",
    ]

    readonly_fields = [
        "is_verified_viewer",
        "created_at",
        "updated_at",
    ]


@admin.register(ReviewReport)
class ReviewReportAdmin(admin.ModelAdmin):
    list_display = [
        "review",
        "reported_by",
        "reason",
        "is_resolved",
        "created_at",
    ]

    list_filter = [
        "reason",
        "is_resolved",
        "created_at",
    ]

    search_fields = [
        "review__movie__name",
        "review__user__username",
        "reported_by__username",
        "details",
    ]

    readonly_fields = [
        "created_at",
    ]

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "movie",
        "theater",
        "amount",
        "status",
        "transaction_id",
        "created_at",
    ]

    list_filter = [
        "status",
        "created_at",
    ]

    search_fields = [
        "user__username",
        "movie__name",
        "theater__name",
        "transaction_id",
        "razorpay_order_id",
        "razorpay_payment_id",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
    ]

@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("user", "balance", "updated_at")
    search_fields = ("user__username", "user__email")
    list_filter = ("updated_at",)
    