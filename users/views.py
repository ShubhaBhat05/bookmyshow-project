from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from .forms import UserRegisterForm, UserUpdateForm
from django.shortcuts import render,redirect
from django.contrib.auth import login,authenticate
from django.contrib.auth.decorators import login_required
from movies.models import Movie , Booking,Payment,Wallet

def home(request):
    movies = Movie.objects.all()

    if request.user.is_authenticated:
        booked_movie_ids = Booking.objects.filter(
            user=request.user
        ).values_list('movie_id', flat=True).distinct()

        recently_viewed_ids = request.session.get('recently_viewed', [])

        recommended_movies = Movie.objects.filter(
            id__in=list(booked_movie_ids) + recently_viewed_ids
        ).exclude(
            id__in=recently_viewed_ids[:0]
        ).order_by('-rating')[:4]

        if not recommended_movies.exists():
            recommended_movies = Movie.objects.order_by('-rating')[:4]
    else:
        recently_viewed_ids = request.session.get('recently_viewed', [])

        recommended_movies = Movie.objects.filter(
            id__in=recently_viewed_ids
        ).order_by('-rating')[:4]

        if not recommended_movies.exists():
            recommended_movies = Movie.objects.order_by('-rating')[:4]

    return render(
        request,
        'home.html',
        {
            'movies': movies,
            'recommended_movies': recommended_movies,
        }
    )
def register(request):
    if request.method == 'POST':
        form=UserRegisterForm(request.POST)
        if form.is_valid():
            form.save()
            username=form.cleaned_data.get('username')
            password=form.cleaned_data.get('password1')
            user=authenticate(username=username,password=password)
            login(request,user)
            return redirect('profile')
    else:
        form=UserRegisterForm()
    return render(request,'users/register.html',{'form':form})

def login_view(request):
    if request.method == 'POST':
        form=AuthenticationForm(request,data=request.POST)
        if form.is_valid():
            user=form.get_user()
            login(request,user)
            return redirect('/')
    else:
        form=AuthenticationForm()
    return render(request,'users/login.html',{'form':form})

@login_required
def profile(request):
    bookings = Booking.objects.filter(
    user=request.user,
    history_hidden=False
).select_related(
        'movie',
        'theater',
        'seat',
        'payment',
    ).order_by('-booked_at')

    payments = Payment.objects.filter(
    user=request.user,
    history_hidden=False
).prefetch_related(
        'seats',
    ).order_by('-created_at')
    try:
        wallet = request.user.wallet
    except Wallet.DoesNotExist:
        wallet = None
    if request.method == 'POST':
        u_form = UserUpdateForm(request.POST, instance=request.user)
        if u_form.is_valid():
            u_form.save()
            return redirect('profile')
    else:
        u_form = UserUpdateForm(instance=request.user)

    return render(
    request,
    'users/profile.html',
    {
        'u_form': u_form,
        'bookings': bookings,
        'payments': payments,
        'wallet': wallet,
    }
)

@login_required
def reset_password(request):
    if request.method == 'POST':
        form=PasswordChangeForm(user=request.user,data=request.POST)
        if form.is_valid():
            form.save()
            return redirect('login')
    else:
        form=PasswordChangeForm(user=request.user)
    return render(request,'users/reset_password.html',{'form':form})

@login_required
def clear_booking_history(request):
    if request.method == 'POST':
        Booking.objects.filter(
            user=request.user
        ).update(
            history_hidden=True
        )

    return redirect('profile')


@login_required
def clear_payment_history(request):
    if request.method == 'POST':
        Payment.objects.filter(
            user=request.user
        ).update(
            history_hidden=True
        )

    return redirect('profile')