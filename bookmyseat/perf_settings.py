
from .settings import *
from decouple import config

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("PERF_DB_NAME", default="bookmyshow_perf_test"),
        "USER": config("PERF_DB_USER", default="postgres"),
        "PASSWORD": config("PERF_DB_PASSWORD"),
        "HOST": config("PERF_DB_HOST", default="localhost"),
        "PORT": config("PERF_DB_PORT", default="5432"),
        "CONN_MAX_AGE": 0,
    }
}

