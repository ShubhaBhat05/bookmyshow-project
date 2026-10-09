from django.urls import path
from . import views
urlpatterns=[
    path('',views.movie_list,name='movie_list'),
    path('<int:movie_id>/theaters',views.theater_list,name='theater_list'),
    path('theater/<int:theater_id>/seats/book/',views.book_seats,name='book_seats'),
    path('<int:movie_id>/details/', views.movie_detail, name='movie_detail'),
    path('<int:movie_id>/review/', views.add_review, name='add_review'),
    path('<int:movie_id>/review/edit/', views.edit_review, name='edit_review'),
    path('review/<int:review_id>/report/', views.report_review, name='report_review'),
    path(
    'theater/<int:theater_id>/seat-availability/',
    views.seat_availability,
    name='seat_availability'
),
path(
    'payment/<int:payment_id>/',
    views.payment_page,
    name='payment_page'
),
path(
    'payment/<int:payment_id>/verify/',
    views.verify_payment,
    name='verify_payment'
),
path(
    'payment/<int:payment_id>/cancel/',
    views.cancel_payment,
    name='cancel_payment'
),
path(
    'payment/<int:payment_id>/fail/',
    views.fail_payment,
    name='fail_payment'
),
path(
    'payment/<int:payment_id>/retry/',
    views.retry_payment,
    name='retry_payment'
),
path(
    'payment/webhook/',
    views.razorpay_webhook,
    name='razorpay_webhook'
),
    path(
        'admin/dashboard/export-csv/',
        views.export_dashboard_csv,
        name='export_dashboard_csv'
    ),

    path(
    "booking/<int:booking_id>/download-ticket/",
    views.download_ticket,
    name="download_ticket",
),
path(
    'payment/<int:payment_id>/test-pay/',
    views.test_pay_now,
    name='test_pay_now',
),
path(
    'payment/<int:payment_id>/pay-later/',
    views.pay_later_booking,
    name='pay_later_booking',
),
path(
    'payment/<int:payment_id>/wallet-pay/',
    views.wallet_payment,
    name='wallet_payment',
),
]