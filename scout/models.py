"""Domain model. See PLAN.md section 3.

User -> Product -> Model -> Offer -> PriceObservation
Every user-owned root (Product, Settings) carries `user` so the service can go multi-user later.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class Product(models.Model):
    """Top-level thing the user wants, e.g. "Zenbook Duo"."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="products")
    name = models.CharField(max_length=200)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["user", "name"], name="uniq_product_per_user")]

    def __str__(self):
        return self.name


class ProductModel(models.Model):
    """An exact variant of a product, e.g. UX8407AA-SN515X. Named ProductModel to avoid clashing with models.Model."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    code = models.CharField(max_length=100, help_text="Manufacturer model code, e.g. UX8407AA-SN515X")
    ean = models.CharField(max_length=14, blank=True, help_text="EAN/GTIN barcode, used for matching")
    specs = models.JSONField(default=dict, blank=True, help_text="Key specs (cpu, ram, ssd, os...) for matching")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "model"
        constraints = [models.UniqueConstraint(fields=["product", "code"], name="uniq_model_code_per_product")]

    def __str__(self):
        return self.code


class Offer(models.Model):
    """One observed URL for a model. For aggregators (Ceneo) one check yields the cheapest valid sub-offer."""

    class Kind(models.TextChoices):
        SINGLE = "single"
        AGGREGATOR = "aggregator"

    class Status(models.TextChoices):
        OK = "ok"
        BROKEN = "broken"  # failed N runs in a row
        GONE = "gone"  # 404 / listing removed
        BLOCKED = "blocked"  # last check blocked by anti-bot on every tier
        SUSPICIOUS = "suspicious"  # last price failed the outlier guard
        NEEDS_REVIEW = "needs_review"  # matcher could not confirm the model

    model = models.ForeignKey(ProductModel, on_delete=models.CASCADE, related_name="offers")
    shop = models.CharField(max_length=50, help_text="Shop class key, e.g. 'xkom'")
    url = models.URLField(max_length=1000)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.SINGLE)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OK)
    active = models.BooleanField(default=True, help_text="Paused offers are not checked")
    consecutive_failures = models.PositiveIntegerField(default=0)
    match_confirmed = models.BooleanField(
        default=False, help_text="The page was confirmed to be this model (by code/EAN or by the user)"
    )
    last_checked_at = models.DateTimeField(null=True, blank=True)
    next_check_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["model", "shop"]
        constraints = [models.UniqueConstraint(fields=["model", "url"], name="uniq_offer_url_per_model")]

    def __str__(self):
        return f"{self.model.code} @ {self.shop}"


class PriceObservation(models.Model):
    """Every price ever fetched (spec point 8)."""

    class Condition(models.TextChoices):
        NEW = "new"
        USED = "used"
        REFURBISHED = "refurbished"
        UNKNOWN = "unknown"

    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name="observations")
    fetched_at = models.DateTimeField(default=timezone.now, db_index=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="PLN")
    seller = models.CharField(max_length=200, blank=True, help_text="Aggregators: the seller of the cheapest offer")
    seller_url = models.URLField(max_length=1000, blank=True)
    condition = models.CharField(max_length=20, choices=Condition.choices, default=Condition.NEW)
    in_stock = models.BooleanField(null=True)
    tier_used = models.PositiveSmallIntegerField()
    suspicious = models.BooleanField(default=False, help_text="Failed the outlier guard; excluded from alerts")
    snapshot_path = models.CharField(max_length=500, blank=True, help_text="Saved HTML, for debugging parsers")

    class Meta:
        ordering = ["-fetched_at"]
        indexes = [models.Index(fields=["offer", "-fetched_at"])]

    def __str__(self):
        return f"{self.price} {self.currency} ({self.offer})"


class CheckFailure(models.Model):
    class Reason(models.TextChoices):
        BLOCKED = "blocked"
        CAPTCHA = "captcha"
        HTTP_ERROR = "http_error"
        NOT_FOUND = "not_found"
        PARSE_ERROR = "parse_error"
        NO_MATCH = "no_match"
        TIMEOUT = "timeout"

    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name="failures")
    at = models.DateTimeField(default=timezone.now, db_index=True)
    reason = models.CharField(max_length=20, choices=Reason.choices)
    tier = models.PositiveSmallIntegerField()
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    detail = models.TextField(blank=True)
    reported = models.BooleanField(default=False, help_text="Already included in a summary email")

    class Meta:
        ordering = ["-at"]


class MatchReview(models.Model):
    """A candidate listing the matcher could not confirm; the user decides."""

    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name="reviews")
    candidate_title = models.CharField(max_length=500)
    candidate_url = models.URLField(max_length=1000)
    reason = models.TextField(blank=True)
    decision = models.BooleanField(null=True, help_text="True = same model, False = different, null = pending")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class DiscoveryRun(models.Model):
    """Background discovery job behind the add-product wizard's live progress page."""

    class Status(models.TextChoices):
        PENDING = "pending"
        RUNNING = "running"
        DONE = "done"
        FAILED = "failed"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="discovery_runs")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    progress_log = models.JSONField(default=list, blank=True)
    results = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class Settings(models.Model):
    """Per-user configuration (spec: Configuration)."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="scout_settings")
    check_interval_hours = models.PositiveIntegerField(default=4)
    summary_interval_hours = models.PositiveIntegerField(default=24)
    notify_email = models.EmailField(blank=True)
    outlier_pct = models.PositiveSmallIntegerField(default=40, help_text="Max % deviation from recent median")
    broken_after_failures = models.PositiveSmallIntegerField(default=3)
    last_summary_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "settings"

    def __str__(self):
        return f"Settings for {self.user}"


class ShopState(models.Model):
    """Per-shop runtime state shared by all workers: request spacing and the fetch tier that last worked."""

    key = models.CharField(max_length=50, unique=True)
    last_request_at = models.DateTimeField(null=True, blank=True)
    preferred_tier = models.PositiveSmallIntegerField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.key
