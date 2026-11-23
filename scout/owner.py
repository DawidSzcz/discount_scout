"""v1 single-user mode: there is no login, every request and job acts as the owner."""

from django.conf import settings
from django.contrib.auth import get_user_model

from .models import Settings


def get_owner():
    user, _ = get_user_model().objects.get_or_create(username=settings.SCOUT_DEFAULT_USERNAME)
    Settings.objects.get_or_create(user=user)
    return user
