from django.shortcuts import render, redirect ,get_object_or_404
from django.conf import settings
import re
from .models import Movie,Theater,Seat,Booking,Review,Payment, Genre, Language,Wallet
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.db import IntegrityError, transaction
from django.db.models import Count,Sum,Q
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from .tasks import release_expired_seats,generate_and_email_ticket
from django.db.models.functions import TruncDate,ExtractHour
from django.http import JsonResponse,HttpResponse
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.decorators import permission_required
from django.core.paginator import Paginator
from .payment_service import (
    create_razorpay_order,
    verify_payment_signature,
    verify_webhook_signature,
)
from django.views.decorators.csrf import csrf_exempt
User = get_user_model()

def movie_list(request):
    search_query = request.GET.get('search', '').strip()
    genre = request.GET.get('genre', '')
    language = request.GET.get('language', '')
    city = request.GET.get('city', '')
    theater = request.GET.get('theater', '')
    release_from = request.GET.get('release_from', '')
    release_to = request.GET.get('release_to', '')
    min_rating = request.GET.get('min_rating', '')
    show_time = request.GET.get('show_time', '')
    sort = request.GET.get('sort', '')
    genres = Genre.objects.all()
    languages = Language.objects.all()
    cities = Theater.objects.exclude(city='').values_list('city', flat=True).distinct()
    theaters = Theater.objects.all()
    movies = Movie.objects.annotate(
        booking_count=Count('bookings')
    )

    # Search by movie title
    if search_query:
        movies = movies.filter(name__icontains=search_query)

    # Filters
    if genre:
        movies = movies.filter(genres__id=genre)

    if language:
        movies = movies.filter(languages__id=language)

    if city:
        movies = movies.filter(theaters__city__iexact=city)

    if theater:
        movies = movies.filter(theaters__id=theater)

    if release_from:
        movies = movies.filter(release_date__gte=release_from)

    if release_to:
        movies = movies.filter(release_date__lte=release_to)

    if min_rating:
        movies = movies.filter(rating__gte=min_rating)

    # Show timing filter
    if show_time == 'morning':
        movies = movies.filter(theaters__time__hour__gte=6,
                               theaters__time__hour__lt=12)

    elif show_time == 'afternoon':
        movies = movies.filter(theaters__time__hour__gte=12,
                               theaters__time__hour__lt=17)

    elif show_time == 'evening':
        movies = movies.filter(theaters__time__hour__gte=17,
                               theaters__time__hour__lt=21)

    elif show_time == 'night':
        movies = movies.filter(theaters__time__hour__gte=21)

    # Sorting
    if sort == 'popularity':
        movies = movies.order_by('-booking_count', '-created_at')

    elif sort == 'newest':
        movies = movies.order_by('-release_date', '-created_at')

    elif sort == 'rating':
        movies = movies.order_by('-rating', '-created_at')

    elif sort == 'price_low':
        movies = movies.order_by('theaters__ticket_price', '-created_at')

    elif sort == 'price_high':
        movies = movies.order_by('-theaters__ticket_price', '-created_at')

    else:
        movies = movies.order_by('-release_date', '-created_at')

    movies = movies.distinct()
    movie_count = movies.count()
    paginator = Paginator(movies, 6)
    page_number = request.GET.get('page')
    movies = paginator.get_page(page_number)

    trending_movies = Movie.objects.annotate(
        booking_count=Count('bookings')
    ).order_by('-booking_count', '-created_at')[:5]

    return render(
        request,
        'movies/movie_list.html',
        {
            'movies': movies,
    'trending_movies': trending_movies,
    'genres': genres,
    'languages': languages,
    'cities': cities,
    'theaters': theaters,
    'movie_count': movie_count,
    'paginator': paginator,
        }
    )


def theater_list(request, movie_id):
    movie = get_object_or_404(Movie, id=movie_id)

    # Show only future showtimes
    theaters = Theater.objects.filter(
        movie=movie,
        time__gt=timezone.now()
    ).order_by('time')

    return render(
        request,
        'movies/theater_list.html',
        {
            'movie': movie,
            'theaters': theaters,
        }
    )




@login_required(login_url='/login/')
def book_seats(request, theater_id):
    theater = get_object_or_404(Theater, id=theater_id)
    
# Prevent access to expired showtimes
    if theater.time <= timezone.now():
        return redirect(
            'theater_list',
            movie_id=theater.movie.id
        )


    seats = list(
            Seat.objects.filter(
                theater=theater
            )
        )

    seats.sort(key=seat_sort_key)
    expired_time = timezone.now()

    Seat.objects.filter(
        theater=theater,
        reserved_until__lte=expired_time,
    ).update(
        reserved_by=None,
        reserved_until=None,
    )

    if request.method == 'POST':
        selected_seats = request.POST.getlist('seats')

        if not selected_seats:
            return render(
                request,
                'movies/seat_selection.html',
                {
                    'theater': theater,
                    'seats': seats,
                    'error': 'Please select at least one seat.',
                    'now': timezone.now(),
                },
            )

        error_seats = []

        with transaction.atomic():
            now = timezone.now()

            locked_seats = list(
                Seat.objects.select_for_update().filter(
                    theater=theater
                ).order_by('id')
            )

            selected_ids = {int(seat_id) for seat_id in selected_seats}

            # Check selected seats
            for seat in locked_seats:
                if seat.id not in selected_ids:
                    continue

                if seat.is_booked:
                    error_seats.append(seat.seat_number)

                elif (
                        seat.reserved_by_id
                        and (
                            seat.reserved_until is None
                            or seat.reserved_until > now
                        )
                        and seat.reserved_by_id != request.user.id
            ):
                    error_seats.append(seat.seat_number)

            # Update reservations only when all selected seats are available
            if not error_seats:
                for seat in locked_seats:

                    # Release seats deselected by the current user
                    if (
                        seat.reserved_by_id == request.user.id
                        and seat.id not in selected_ids
                    ):
                        seat.reserved_by = None
                        seat.reserved_until = None
                        seat.save(
                            update_fields=[
                                'reserved_by',
                                'reserved_until',
                            ]
                        )

                    # Reserve selected seats
                    elif (
                        seat.id in selected_ids
                        and not seat.is_booked
                    ):
                        seat.reserved_by = request.user
                        seat.reserved_until = now + timedelta(minutes=2)
                        seat.save(
                            update_fields=[
                                'reserved_by',
                                'reserved_until',
                            ]
                        )

        if error_seats:
            seats = list(
                    Seat.objects.filter(
                        theater=theater
                    )
                )

            seats.sort(key=seat_sort_key)

            return render(
                request,
                'movies/seat_selection.html',
                {
                    'theater': theater,
                    'seats': seats,
                    'error': (
                        'These seats are currently unavailable: '
                        + ', '.join(error_seats)
                    ),
                    'now': timezone.now(),
                },
            )
        payment_amount = theater.ticket_price * len(selected_ids)

        

        payment = Payment.objects.create(
            user=request.user,
            movie=theater.movie,
            theater=theater,
            amount=payment_amount,
            razorpay_order_id=f"pending_{request.user.id}_{theater.id}_{int(timezone.now().timestamp())}",
            payment_method="pay_now",
            status="created",
        )

        payment.seats.set(
            Seat.objects.filter(
                id__in=selected_ids,
                theater=theater,
            )
)

        release_expired_seats.apply_async(
            args=[list(selected_ids), request.user.id],
            countdown=120,
        )

        return redirect(
        'payment_page',
        payment_id=payment.id,
    )



    return render(
        request,
        'movies/seat_selection.html',
        {
            'theater': theater,
            'seats': seats,
            'now': timezone.now(),
        },
    )
def seat_sort_key(seat):
    match = re.match(r"^(.*?)(\d+)$", seat.seat_number)

    if match:
        prefix = match.group(1)
        number = int(match.group(2))
        return (prefix.lower(), number)

    return (seat.seat_number.lower(), 0)
@login_required(login_url='/login/')
def payment_page(request, payment_id):
    payment = get_object_or_404(
        Payment,
        id=payment_id,
        user=request.user,
        status='created',
    )
    if payment.theater.time <= timezone.now():
        payment.status = 'failed'
        payment.save(update_fields=['status', 'updated_at'])

        payment.seats.filter(
            reserved_by=request.user,
            is_booked=False,
        ).update(
            reserved_by=None,
            reserved_until=None,
        )

        return redirect(
            'theater_list',
            movie_id=payment.movie.id,
        )
    return render(
        request,
        'movies/payment.html',
        {
            'payment': payment,
            'razorpay_key': settings.RAZORPAY_KEY_ID,
        },
    )
def movie_detail(request, movie_id):
    movie = get_object_or_404(Movie, id=movie_id)
    recently_viewed = request.session.get('recently_viewed', [])

    if movie_id in recently_viewed:
        recently_viewed.remove(movie_id)

    recently_viewed.insert(0, movie_id)
    recently_viewed = recently_viewed[:10]

    request.session['recently_viewed'] = recently_viewed

    reviews = movie.reviews.select_related("user").order_by("-created_at")
    posters = movie.posters.all()

    similar_movies = Movie.objects.filter(
        genres__in=movie.genres.all()
    ).exclude(
        id=movie.id
    ).distinct()[:6]

    trending_movies = Movie.objects.annotate(
        booking_count=Count('bookings')
    ).filter(
        booking_count__gt=0
    ).exclude(
        id=movie.id
    ).order_by('-booking_count', '-created_at')[:6]

    recently_released_movies = Movie.objects.filter(
    release_date__isnull=False
).exclude(
    id=movie.id
).order_by('-release_date')[:4]

    return render(
        request,
        "movies/movie_detail.html",
        {
            "movie": movie,
            "reviews": reviews,
            "posters": posters,
            "similar_movies": similar_movies,
            "trending_movies": trending_movies,
            "recently_released_movies": recently_released_movies,
        },
    )
@login_required(login_url='/login/')
def add_review(request, movie_id):
    movie = get_object_or_404(Movie, id=movie_id)

    has_watched = Booking.objects.filter(
        user=request.user,
        movie=movie,
        theater__time__lte=timezone.now(),
    ).exists()

    if not has_watched:
        return redirect('movie_detail', movie_id=movie.id)

    if request.method == 'POST':
        rating = request.POST.get('rating')
        title = request.POST.get('title', '').strip()
        comment = request.POST.get('comment', '').strip()

        Review.objects.update_or_create(
            movie=movie,
            user=request.user,
            defaults={
                'rating': rating,
                'title': title,
                'comment': comment,
            },
        )

    return redirect('movie_detail', movie_id=movie.id)
@login_required(login_url='/login/')
def edit_review(request, movie_id):
    movie = get_object_or_404(Movie, id=movie_id)

    review = get_object_or_404(
        Review,
        movie=movie,
        user=request.user,
    )

    if request.method == 'POST':
        review.rating = request.POST.get('rating')
        review.title = request.POST.get('title', '').strip()
        review.comment = request.POST.get('comment', '').strip()
        review.save()

        return redirect('movie_detail', movie_id=movie.id)

    return render(
        request,
        'movies/edit_review.html',
        {
            'movie': movie,
            'review': review,
        },
    )
@login_required(login_url='/login/')
def report_review(request, review_id):
    review = get_object_or_404(Review, id=review_id)

    if request.method == 'POST':
        reason = request.POST.get('reason', '').strip()
        details = request.POST.get('details', '').strip()

        if reason:
            from .models import ReviewReport

            ReviewReport.objects.update_or_create(
                review=review,
                reported_by=request.user,
                defaults={
                    'reason': reason,
                    'details': details,
                },
            )

    return redirect('movie_detail', movie_id=review.movie.id)
def seat_availability(request, theater_id):
    theater = get_object_or_404(Theater, id=theater_id)
    if theater.time <= timezone.now():
        return JsonResponse(
            {
                'error': 'This show has already started or ended.',
                'seats': [],
            },
            status=410
        )
    now = timezone.now()

    Seat.objects.filter(
    theater=theater,
    reserved_until__isnull=False,
    reserved_until__lte=now,
).update(
    reserved_by=None,
    reserved_until=None,
)

    seats = list(
            Seat.objects.filter(
                theater=theater
            )
        )

    seats.sort(key=seat_sort_key)

    seat_data = []

    for seat in seats:
        if seat.is_booked:
            status = 'booked'
        elif (
            seat.reserved_by_id
            and (
                seat.reserved_until is None
                or seat.reserved_until > now
            )
        ):
            status = 'reserved'
        else:
            status = 'available'

        seat_data.append({
            'id': seat.id,
            'seat_number': seat.seat_number,
            'status': status,
        })

    return JsonResponse({'seats': seat_data})

@login_required(login_url='/login/')
def verify_payment(request, payment_id):
    if request.method != 'POST':
        return JsonResponse(
            {'error': 'Invalid request method.'},
            status=405,
        )

    with transaction.atomic():
        payment = get_object_or_404(
            Payment.objects.select_for_update(),
            id=payment_id,
            user=request.user,
        )

        # Prevent duplicate payment confirmation
        if payment.status == 'success':
            return JsonResponse({
                'message': 'Payment already verified.',
            })

        if payment.status != 'created':
            return JsonResponse(
                {'error': 'This payment cannot be verified.'},
                status=400,
            )

        razorpay_payment_id = request.POST.get(
            'razorpay_payment_id'
        )
        razorpay_signature = request.POST.get(
            'razorpay_signature'
        )

        if not razorpay_payment_id or not razorpay_signature:
            return JsonResponse(
                {'error': 'Payment verification data is missing.'},
                status=400,
            )
        existing_payment = Payment.objects.filter(
            razorpay_payment_id=razorpay_payment_id,
            status='success',
        ).exclude(
            id=payment.id
        ).first()

        if existing_payment:
            return JsonResponse(
                {'error': 'This payment has already been processed.'},
                status=400,
            )

        try:
            verify_payment_signature(
                payment.razorpay_order_id,
                razorpay_payment_id,
                razorpay_signature,
            )
        except Exception:
            payment.status = 'failed'
            payment.save(
                update_fields=['status', 'updated_at']
            )

            payment.seats.filter(
                reserved_by=request.user,
            ).update(
                reserved_by=None,
                reserved_until=None,
            )

            return JsonResponse(
                {'error': 'Payment verification failed.'},
                status=400,
            )

        seats = list(
            payment.seats.select_for_update().filter(
                reserved_by=request.user,
            )
        )

        if not seats:
            payment.status = 'failed'
            payment.save(
                update_fields=['status', 'updated_at']
            )

            return JsonResponse(
                {'error': 'Reserved seats are no longer available.'},
                status=400,
            )

        for seat in seats:
            if seat.is_booked:
                payment.status = 'failed'
                payment.save(
                    update_fields=['status', 'updated_at']
                )

                return JsonResponse(
                    {'error': 'One or more seats are already booked.'},
                    status=400,
                )

        try:
            confirm_payment_and_create_bookings(
                payment,
                razorpay_payment_id,
            )
        except ValueError as e:
            payment.status = 'failed'
            payment.save(
                update_fields=['status', 'updated_at']
            )

            payment.seats.filter(
                reserved_by=request.user,
            ).update(
                reserved_by=None,
                reserved_until=None,
            )

            return JsonResponse(
                {'error': str(e)},
                status=400,
            )

        payment.razorpay_signature = razorpay_signature
        payment.save(
            update_fields=[
                'razorpay_signature',
                'updated_at',
            ]
        )

    return JsonResponse({
        'message': 'Payment verified and booking confirmed.',
    })

@login_required(login_url='/login/')
def test_pay_now(request, payment_id):
    if request.method != 'POST':
        return JsonResponse(
            {'error': 'Invalid request method.'},
            status=405,
        )

    with transaction.atomic():
        payment = get_object_or_404(
            Payment.objects.select_for_update(),
            id=payment_id,
            user=request.user,
            status='created',
        )
        if payment.theater.time <= timezone.now():
            payment.status = 'failed'
            payment.save(update_fields=['status', 'updated_at'])

            payment.seats.filter(
                reserved_by=request.user,
                is_booked=False,
            ).update(
                reserved_by=None,
                reserved_until=None,
            )

            return JsonResponse(
                {
                    'error': 'This show has already started or ended.'
                },
                status=410,
            )
        if payment.payment_method != 'pay_now':
            return JsonResponse(
                {'error': 'Invalid payment method.'},
                status=400,
            )

        seats = list(
            payment.seats.select_for_update().filter(
                reserved_by=request.user,
                is_booked=False,
            )
        )

        if not seats:
            payment.status = 'failed'
            payment.save(
                update_fields=['status', 'updated_at']
            )

            return JsonResponse(
                {'error': 'Reserved seats are no longer available.'},
                status=400,
            )

        for seat in seats:
            if seat.is_booked:
                payment.status = 'failed'
                payment.save(
                    update_fields=['status', 'updated_at']
                )

                return JsonResponse(
                    {'error': 'One or more seats are already booked.'},
                    status=400,
                )

        test_payment_id = f"TESTPAY_{payment.id}_{int(timezone.now().timestamp())}"

        payment.status = 'success'
        payment.razorpay_payment_id = test_payment_id
        payment.transaction_id = test_payment_id

        payment.save(
            update_fields=[
                'status',
                'razorpay_payment_id',
                'transaction_id',
                'updated_at',
            ]
        )

        for seat in seats:

            # Prevent duplicate booking for the same seat
            if Booking.objects.filter(seat=seat).exists():
                payment.status = 'failed'
                payment.save(update_fields=['status', 'updated_at'])

                return JsonResponse(
                    {
                        'error': f'Seat {seat.seat_number} is already booked.'
                    },
                    status=400
                )

            Booking.objects.create(
                user=payment.user,
                seat=seat,
                movie=payment.movie,
                theater=payment.theater,
                payment=payment,
            )

            seat.is_booked = True
            seat.reserved_by = None
            seat.reserved_until = None
            seat.save(
                update_fields=[
                    'is_booked',
                    'reserved_by',
                    'reserved_until',
                ]
            )

            seat.is_booked = True
            seat.reserved_by = None
            seat.reserved_until = None

            seat.save(
                update_fields=[
                    'is_booked',
                    'reserved_by',
                    'reserved_until',
                ]
            )

        transaction.on_commit(
    lambda: generate_and_email_ticket.run(payment.id)
)

    return JsonResponse({
    'success': True,
    'message': 'Test payment successful.',
    'transaction_id': payment.transaction_id,
})
@login_required(login_url='/login/')
def pay_later_booking(request, payment_id):
    if request.method != 'POST':
        return JsonResponse(
            {'error': 'Invalid request method.'},
            status=405,
        )

    with transaction.atomic():
        payment = get_object_or_404(
            Payment.objects.select_for_update(),
            id=payment_id,
            user=request.user,
            status='created',
        )
        if payment.theater.time <= timezone.now():
            payment.status = 'failed'
            payment.save(update_fields=['status', 'updated_at'])

            payment.seats.filter(
                reserved_by=request.user,
                is_booked=False,
            ).update(
                reserved_by=None,
                reserved_until=None,
            )

            return JsonResponse(
                {
                    'error': 'This show has already started or ended.'
                },
                status=410,
            )
        # Mark this payment as Pay Later
        payment.payment_method = 'pay_later'

        seats = list(
            payment.seats.select_for_update().filter(
                is_booked=False,
                reserved_by=request.user,
            )
        )

        if not seats:
            payment.status = 'failed'
            payment.save(
                update_fields=[
                    'status',
                    'payment_method',
                    'updated_at',
                ]
            )

            return JsonResponse(
                {
                    'error':
                    'Reserved seats are no longer available.'
                },
                status=400,
            )

        for seat in seats:
            if seat.is_booked:
                payment.status = 'failed'
                payment.save(
                    update_fields=[
                        'status',
                        'payment_method',
                        'updated_at',
                    ]
                )

                return JsonResponse(
                    {
                        'error':
                        f'Seat {seat.seat_number} is already booked.'
                    },
                    status=400,
                )

        # Pay Later means booking is confirmed,
        # but payment is still pending.
        payment.status = 'pending'

        payment.transaction_id = (
            f'PAYLATER_{payment.id}_'
            f'{int(timezone.now().timestamp())}'
        )

        payment.save(
            update_fields=[
                'payment_method',
                'status',
                'transaction_id',
                'updated_at',
            ]
        )

        for seat in seats:
            Booking.objects.create(
                user=payment.user,
                seat=seat,
                movie=payment.movie,
                theater=payment.theater,
                payment=payment,
            )

            seat.is_booked = True
            seat.reserved_by = None
            seat.reserved_until = None

            seat.save(
                update_fields=[
                    'is_booked',
                    'reserved_by',
                    'reserved_until',
                ]
            )

    return JsonResponse({
        'success': True,
        'message': (
            'Booking confirmed. '
            'Payment will be collected later.'
        ),
        'transaction_id': payment.transaction_id,
    })

@login_required(login_url='/login/')
def wallet_payment(request, payment_id):
    if request.method != 'POST':
        return JsonResponse(
            {'error': 'Invalid request method.'},
            status=405,
        )

    with transaction.atomic():

        payment = get_object_or_404(
            Payment.objects.select_for_update(),
            id=payment_id,
            user=request.user,
            status='created',
        )
        if payment.theater.time <= timezone.now():
            payment.status = 'failed'
            payment.save(update_fields=['status', 'updated_at'])

            payment.seats.filter(
                reserved_by=request.user,
                is_booked=False,
            ).update(
                reserved_by=None,
                reserved_until=None,
            )

            return JsonResponse(
                {
                    'error': 'This show has already started or ended.'
                },
                status=410,
            )
        payment.payment_method = 'wallet'

        seats = list(
            payment.seats.select_for_update().filter(
                reserved_by=request.user,
                is_booked=False,
            )
        )

        if not seats:
            payment.status = 'failed'
            payment.save(
                update_fields=[
                    'status',
                    'payment_method',
                    'updated_at',
                ]
            )

            return JsonResponse(
                {
                    'error':
                    'Reserved seats are no longer available.'
                },
                status=400,
            )

        # Lock the user's wallet while checking/updating balance.
        wallet, created = Wallet.objects.select_for_update().get_or_create(
            user=request.user,
            defaults={'balance': 0},
        )

        if wallet.balance < payment.amount:
            return JsonResponse(
                {
                    'error': (
                        f'Insufficient wallet balance. '
                        f'Available balance: ₹{wallet.balance}'
                    )
                },
                status=400,
            )

        # Deduct the booking amount.
        wallet.balance -= payment.amount
        wallet.save(
            update_fields=[
                'balance',
                'updated_at',
            ]
        )

        # Mark payment successful.
        transaction_id = (
            f'WALLET_{payment.id}_'
            f'{int(timezone.now().timestamp())}'
        )

        payment.status = 'success'
        payment.transaction_id = transaction_id

        payment.save(
            update_fields=[
                'payment_method',
                'status',
                'transaction_id',
                'updated_at',
            ]
        )

        # Confirm the booking and book the seats.
        for seat in seats:

            Booking.objects.create(
                user=payment.user,
                seat=seat,
                movie=payment.movie,
                theater=payment.theater,
                payment=payment,
            )

            seat.is_booked = True
            seat.reserved_by = None
            seat.reserved_until = None

            seat.save(
                update_fields=[
                    'is_booked',
                    'reserved_by',
                    'reserved_until',
                ]
            )

        transaction.on_commit(
            lambda: generate_and_email_ticket.run(payment.id)
        )

    return JsonResponse({
        'success': True,
        'message': 'Wallet payment successful.',
        'transaction_id': transaction_id,
        'remaining_balance': str(wallet.balance),
    })

@login_required(login_url='/login/')
def cancel_payment(request, payment_id):
    if request.method != 'POST':
        return JsonResponse(
            {'error': 'Invalid request method.'},
            status=405,
        )

    with transaction.atomic():
        payment = get_object_or_404(
            Payment.objects.select_for_update(),
            id=payment_id,
            user=request.user,
            status='created',
        )

        payment.status = 'cancelled'
        payment.save(
            update_fields=['status', 'updated_at']
        )

        payment.seats.filter(
            reserved_by=request.user,
        ).update(
            reserved_by=None,
            reserved_until=None,
        )

    return JsonResponse({
        'message': 'Payment cancelled and seats released.',
    })
@login_required(login_url='/login/')
def fail_payment(request, payment_id):
    if request.method != 'POST':
        return JsonResponse(
            {'error': 'Invalid request method.'},
            status=405,
        )

    with transaction.atomic():
        payment = get_object_or_404(
            Payment.objects.select_for_update(),
            id=payment_id,
            user=request.user,
            status='created',
        )

        payment.status = 'failed'
        payment.save(
            update_fields=['status', 'updated_at']
        )

        payment.seats.filter(
            reserved_by=request.user,
        ).update(
            reserved_by=None,
            reserved_until=None,
        )

    return JsonResponse({
        'message': 'Payment failed and seats released.',
    })

@login_required(login_url='/login/')
def retry_payment(request, payment_id):
    old_payment = get_object_or_404(
        Payment,
        id=payment_id,
        user=request.user,
        status__in=['failed', 'cancelled'],
    )

    now = timezone.now()

    with transaction.atomic():
        seats = list(
            old_payment.seats.select_for_update().filter(
                is_booked=False,
            )
        )

        if not seats:
            return JsonResponse(
                {'error': 'The seats are no longer available.'},
                status=400,
            )

        for seat in seats:
            if (
                seat.reserved_by_id
                and seat.reserved_by_id != request.user.id
                and seat.reserved_until
                and seat.reserved_until > now
            ):
                return JsonResponse(
                    {
                        'error': (
                            f'Seat {seat.seat_number} '
                            'is currently reserved by another user.'
                        )
                    },
                    status=400,
                )

        reservation_expiry = now + timedelta(minutes=2)

        for seat in seats:
            seat.reserved_by = request.user
            seat.reserved_until = reservation_expiry

            seat.save(
                update_fields=[
                    'reserved_by',
                    'reserved_until',
                ]
            )

        payment_amount = (
            old_payment.theater.ticket_price * len(seats)
        )

        try:
            receipt = (
                f"retry_{request.user.id}_"
                f"{old_payment.id}_"
                f"{int(now.timestamp())}"
            )

            razorpay_order = create_razorpay_order(
                payment_amount,
                receipt,
            )

        except Exception:
            for seat in seats:
                seat.reserved_by = None
                seat.reserved_until = None

                seat.save(
                    update_fields=[
                        'reserved_by',
                        'reserved_until',
                    ]
                )

            return JsonResponse(
                {'error': 'Unable to create a new payment order.'},
                status=500,
            )

        new_payment = Payment.objects.create(
            user=request.user,
            movie=old_payment.movie,
            theater=old_payment.theater,
            amount=payment_amount,
            razorpay_order_id=razorpay_order['id'],
            status='created',
        )

        new_payment.seats.set(seats)

    release_expired_seats.apply_async(
        args=[
            [seat.id for seat in seats],
            request.user.id,
        ],
        countdown=120,
    )

    return redirect(
        'payment_page',
        payment_id=new_payment.id,
    )

def confirm_payment_and_create_bookings(payment, razorpay_payment_id):
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(
            id=payment.id
        )

        # If already successful, do not create duplicate bookings.
        if payment.status == 'success':
            return

        seats = list(
            payment.seats.select_for_update().filter(
                reserved_by=payment.user,
                is_booked=False,
            )
        )

        if not seats:
            raise ValueError(
                'Reserved seats are no longer available.'
            )

        for seat in seats:
            if seat.is_booked:
                raise ValueError(
                    'One or more seats are already booked.'
                )

        payment.status = 'success'
        payment.razorpay_payment_id = razorpay_payment_id
        payment.transaction_id = razorpay_payment_id

        payment.save(
            update_fields=[
                'status',
                'razorpay_payment_id',
                'transaction_id',
                'updated_at',
            ]
        )

        for seat in seats:
            Booking.objects.get_or_create(
                user=payment.user,
                seat=seat,
                movie=payment.movie,
                theater=payment.theater,
                payment=payment,
            )

            seat.is_booked = True
            seat.reserved_by = None
            seat.reserved_until = None

            seat.save(
                update_fields=[
                    'is_booked',
                    'reserved_by',
                    'reserved_until',
                ]
            )
        transaction.on_commit(
    lambda: generate_and_email_ticket.delay(payment.id)
)
@csrf_exempt
def razorpay_webhook(request):
    if request.method != 'POST':
        return HttpResponse(
            'Invalid request method.',
            status=405,
        )

    payload = request.body.decode('utf-8')
    signature = request.headers.get('X-Razorpay-Signature')

    if not signature:
        return HttpResponse(
            'Missing webhook signature.',
            status=400,
        )

    try:
        verify_webhook_signature(
            payload,
            signature,
            settings.RAZORPAY_WEBHOOK_SECRET,
        )
    except Exception:
        return HttpResponse(
            'Invalid webhook signature.',
            status=400,
        )

    try:
        import json

        data = json.loads(payload)

        event = data.get('event')

        payment_entity = (
            data.get('payload', {})
            .get('payment', {})
            .get('entity', {})
        )

        razorpay_payment_id = payment_entity.get('id')
        razorpay_order_id = payment_entity.get('order_id')

        if not razorpay_payment_id or not razorpay_order_id:
            return HttpResponse(
                'Invalid payment data.',
                status=400,
            )

        with transaction.atomic():
            payment = Payment.objects.select_for_update().filter(
                razorpay_order_id=razorpay_order_id
            ).first()

            if not payment:
                return HttpResponse(
                    'Payment record not found.',
                    status=404,
                )

            if event == 'payment.captured':
               try:
                  confirm_payment_and_create_bookings(
            payment,
            razorpay_payment_id,
        )
               except ValueError:
                  return HttpResponse(
            'Unable to confirm payment.',
            status=400,
        )

            elif event == 'payment.failed':
                if payment.status == 'created':
                    payment.status = 'failed'

                    payment.razorpay_payment_id = (
                        razorpay_payment_id
                    )

                    payment.save(
                        update_fields=[
                            'status',
                            'razorpay_payment_id',
                            'updated_at',
                        ]
                    )

                    payment.seats.filter(
                        is_booked=False,
                        reserved_by=payment.user,
                    ).update(
                        reserved_by=None,
                        reserved_until=None,
                    )

    except Exception:
        return HttpResponse(
            'Webhook processing failed.',
            status=500,
        )

    return HttpResponse(
        'Webhook processed.',
        status=200,
    )


@login_required(login_url='/admin/login/')
@user_passes_test(
    lambda user: user.is_superuser or user.has_perm("movies.view_booking"),
    login_url='/admin/login/',
)
def admin_dashboard(request):
    today = timezone.localdate()

    start_date_input = request.GET.get("start_date", "")
    end_date_input = request.GET.get("end_date", "")

    # Default to today when no date range is supplied.
    try:
        start_date = (
            timezone.datetime.strptime(start_date_input, "%Y-%m-%d").date()
            if start_date_input else today
        )
        end_date = (
            timezone.datetime.strptime(end_date_input, "%Y-%m-%d").date()
            if end_date_input else today
        )
    except ValueError:
        start_date = today
        end_date = today

    # Reject reversed date ranges.
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    start_datetime = timezone.make_aware(
        timezone.datetime.combine(
            start_date, timezone.datetime.min.time()
        )
    )

    # Exclusive end boundary: midnight after the selected end date.
    end_exclusive = timezone.make_aware(
        timezone.datetime.combine(
            end_date + timedelta(days=1),
            timezone.datetime.min.time()
        )
    )

    # All booking analytics use the selected date range.
    bookings = Booking.objects.filter(
        booked_at__gte=start_datetime,
        booked_at__lt=end_exclusive
    )

    # All payment analytics use the selected date range.
    payments = Payment.objects.filter(
        created_at__gte=start_datetime,
        created_at__lt=end_exclusive
    )
    successful_payments = payments.filter(status="success")

    
    # Revenue for the selected end date.
    daily_revenue = Payment.objects.filter(
        status="success",
        created_at__date=end_date,
    ).aggregate(total=Sum("amount"))["total"] or 0

    # Revenue for the calendar week containing the selected end date.
    week_start = end_date - timedelta(days=end_date.weekday())
    week_end = week_start + timedelta(days=6)

    weekly_revenue = Payment.objects.filter(
        status="success",
        created_at__date__gte=week_start,
        created_at__date__lte=week_end,
    ).aggregate(total=Sum("amount"))["total"] or 0

    # Revenue for the month containing the selected end date.
    monthly_revenue = Payment.objects.filter(
        status="success",
        created_at__year=end_date.year,
        created_at__month=end_date.month,
    ).aggregate(total=Sum("amount"))["total"] or 0

    # Revenue for the year containing the selected end date.
    yearly_revenue = Payment.objects.filter(
        status="success",
        created_at__year=end_date.year,
    ).aggregate(total=Sum("amount"))["total"] or 0

    total_bookings = bookings.count()

    booking_trends = (
        bookings
        .annotate(date=TruncDate("booked_at"))
        .values("date")
        .annotate(total=Count("id"))
        .order_by("date")
    )

        
    # Occupancy for each screening:
    # currently booked seats / total seats for that screening.
    theater_occupancy = Theater.objects.annotate(
        total_seats=Count("seats", distinct=True),
        booked_seats=Count(
            "seats",
            filter=Q(seats__is_booked=True),
            distinct=True,
        ),
    )

    for theater in theater_occupancy:
        if theater.total_seats:
            theater.occupancy_percentage = round(
                theater.booked_seats / theater.total_seats * 100, 2
            )
        else:
            theater.occupancy_percentage = 0

    # Most-booked movies within the selected range.
    most_booked_movies = (
        Movie.objects
        .annotate(
            total_bookings=Count(
                "bookings",
                filter=Q(
    bookings__booked_at__gte=start_datetime,
    bookings__booked_at__lt=end_exclusive
),
                distinct=True,
            )
        )
        .filter(total_bookings__gt=0)
        .order_by("-total_bookings", "name")
    )

    # Top-performing theaters within the selected range.
    top_performing_theaters = (
        Theater.objects
        .annotate(
            total_bookings=Count(
                "bookings",
                filter=Q(
                    bookings__booked_at__gte=start_datetime,
                    bookings__booked_at__lt=end_exclusive
                ),
                distinct=True,
            )
        )
        .filter(total_bookings__gt=0)
        .order_by("-total_bookings", "name")
    )

    peak_booking_hours = (
        bookings
        .annotate(hour=ExtractHour("booked_at"))
        .values("hour")
        .annotate(total=Count("id"))
        .order_by("-total", "hour")
    )

    cancellation_statistics = payments.filter(
        status="cancelled"
    ).count()

    refund_statistics = payments.filter(
        status="refunded"
    ).count()

    # New users registered during the selected range.
    users_in_range = User.objects.filter(
    date_joined__gte=start_datetime,
    date_joined__lt=end_exclusive
)

    total_users = User.objects.count()

    user_growth = (
        users_in_range
        .annotate(date=TruncDate("date_joined"))
        .values("date")
        .annotate(total=Count("id"))
        .order_by("date")
    )

    context = {
        "start_date": start_date,
        "end_date": end_date,
        "daily_revenue": daily_revenue,
        "weekly_revenue": weekly_revenue,
        "monthly_revenue": monthly_revenue,
        "yearly_revenue": yearly_revenue,
        "total_bookings": total_bookings,
        "total_users": total_users,
        "booking_trends": booking_trends,
        "theater_occupancy": theater_occupancy,
        "most_booked_movies": most_booked_movies,
        "top_performing_theaters": top_performing_theaters,
        "peak_booking_hours": peak_booking_hours,
        "cancellation_statistics": cancellation_statistics,
        "refund_statistics": refund_statistics,
        "user_growth": user_growth,
    }

    return render(
        request,
        "movies/admin_dashboard.html",
        context,
    )

@permission_required('movies.view_booking', raise_exception=True)
def export_dashboard_csv(request):
    import csv

    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")

    if not start_date or not end_date:
        return HttpResponse(
            "Please select a start date and end date.",
            status=400,
        )

    try:
        start_date = timezone.datetime.strptime(
            start_date, "%Y-%m-%d"
        ).date()

        end_date = timezone.datetime.strptime(
            end_date, "%Y-%m-%d"
        ).date()
    except ValueError:
        return HttpResponse("Invalid date format.", status=400)

    if start_date > end_date:
        return HttpResponse(
            "Start date must be before or equal to end date.",
            status=400,
        )

    start_datetime = timezone.make_aware(
        timezone.datetime.combine(
            start_date,
            timezone.datetime.min.time(),
        )
    )

    end_exclusive = timezone.make_aware(
        timezone.datetime.combine(
            end_date + timedelta(days=1),
            timezone.datetime.min.time()
        )
    )

    bookings = Booking.objects.filter(
        booked_at__gte=start_datetime,
          booked_at__lt=end_exclusive
    ).select_related(
        "user", "movie", "theater", "seat", "payment"
    ).order_by("booked_at")

    response = HttpResponse(
        content_type="text/csv; charset=utf-8"
    )
    response["Content-Disposition"] = (
        'attachment; filename="booking_report.csv"'
    )

    writer = csv.writer(response)

    writer.writerow([
        "Booking ID",
        "User",
        "Movie",
        "Theater",
        "Seat",
        "Booking Date",
        "Payment Status",
        "Transaction ID",
    ])

    for booking in bookings.iterator(chunk_size=2000):
        writer.writerow([
            booking.id,
            booking.user.username,
            booking.movie.name,
            booking.theater.name,
            booking.seat.seat_number,
            booking.booked_at,
            booking.payment.status if booking.payment else "",
            booking.payment.transaction_id if booking.payment else "",
        ])

    return response

from django.http import FileResponse
def download_ticket(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related("payment"),
        id=booking_id,
        user=request.user,
    )

    payment = booking.payment

    if not payment or not payment.ticket_pdf:
        return HttpResponse(
            "Ticket is not available yet.",
            status=404,
        )

    return FileResponse(
        payment.ticket_pdf.open("rb"),
        as_attachment=True,
        filename=f"ticket_{payment.id}.pdf",
    )