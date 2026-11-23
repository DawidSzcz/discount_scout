from django.contrib import admin

from . import models as m


class ProductModelInline(admin.TabularInline):
    model = m.ProductModel
    extra = 0
    fields = ("code", "ean", "active")


class OfferInline(admin.TabularInline):
    model = m.Offer
    extra = 0
    fields = ("shop", "url", "kind", "status", "active", "last_checked_at")
    readonly_fields = ("last_checked_at",)


@admin.register(m.Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "active", "created_at")
    list_filter = ("active",)
    search_fields = ("name",)
    inlines = [ProductModelInline]


@admin.register(m.ProductModel)
class ProductModelAdmin(admin.ModelAdmin):
    list_display = ("code", "product", "ean", "active")
    list_filter = ("active", "product")
    search_fields = ("code", "ean")
    inlines = [OfferInline]


@admin.register(m.Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ("model", "shop", "kind", "status", "active", "consecutive_failures", "last_checked_at")
    list_filter = ("shop", "status", "kind", "active")
    search_fields = ("url", "model__code")


@admin.register(m.PriceObservation)
class PriceObservationAdmin(admin.ModelAdmin):
    list_display = ("offer", "price", "currency", "seller", "condition", "tier_used", "suspicious", "fetched_at")
    list_filter = ("suspicious", "condition", "offer__shop")
    date_hierarchy = "fetched_at"


@admin.register(m.CheckFailure)
class CheckFailureAdmin(admin.ModelAdmin):
    list_display = ("offer", "reason", "tier", "http_status", "reported", "at")
    list_filter = ("reason", "reported", "offer__shop")


@admin.register(m.MatchReview)
class MatchReviewAdmin(admin.ModelAdmin):
    list_display = ("offer", "candidate_title", "decision", "created_at")
    list_filter = ("decision",)


@admin.register(m.DiscoveryRun)
class DiscoveryRunAdmin(admin.ModelAdmin):
    list_display = ("product", "status", "created_at", "finished_at")
    list_filter = ("status",)


@admin.register(m.Settings)
class SettingsAdmin(admin.ModelAdmin):
    list_display = ("user", "check_interval_hours", "summary_interval_hours", "notify_email")


@admin.register(m.ShopState)
class ShopStateAdmin(admin.ModelAdmin):
    list_display = ("key", "preferred_tier", "last_success_at", "last_request_at")
