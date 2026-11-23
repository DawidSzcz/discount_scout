from django.urls import path

from . import views

urlpatterns = [
    path("", views.product_list, name="product_list"),
    path("products/new/", views.product_create, name="product_create"),
    path("products/<int:pk>/", views.product_detail, name="product_detail"),
    path("products/<int:pk>/edit/", views.product_edit, name="product_edit"),
    path("products/<int:pk>/delete/", views.product_delete, name="product_delete"),
    path("products/<int:pk>/models/new/", views.model_create, name="model_create"),
    path("models/<int:pk>/toggle/", views.model_toggle, name="model_toggle"),
    path("models/<int:pk>/delete/", views.model_delete, name="model_delete"),
    path("models/<int:pk>/offers/new/", views.offer_create, name="offer_create"),
    path("offers/<int:pk>/", views.offer_detail, name="offer_detail"),
    path("offers/<int:pk>/toggle/", views.offer_toggle, name="offer_toggle"),
    path("offers/<int:pk>/check/", views.offer_check, name="offer_check"),
    path("offers/<int:pk>/delete/", views.offer_delete, name="offer_delete"),
    path("settings/", views.settings_view, name="settings"),
]
