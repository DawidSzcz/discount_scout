"""Read-side helpers that turn the price history into what the pages show."""

from dataclasses import dataclass, field

from django.db.models import Min
from django.utils import timezone

from .models import Offer, PriceObservation, Product, ProductModel, SupportingOffer
from .shops import get_shop


@dataclass
class OfferRow:
    offer: Offer
    latest: PriceObservation | None  # latest observation, suspicious or not
    is_best: bool = False


@dataclass
class ModelStats:
    model: ProductModel
    rows: list[OfferRow] = field(default_factory=list)
    best: PriceObservation | None = None  # cheapest latest valid price across active offers
    all_time_low: PriceObservation | None = None
    supporting: list[SupportingOffer] = field(default_factory=list)  # unsupported shops seen on Ceneo


def model_stats(model: ProductModel) -> ModelStats:
    stats = ModelStats(model=model)
    valid_latest = []
    for offer in model.offers.all():
        latest = offer.observations.first()
        stats.rows.append(OfferRow(offer=offer, latest=latest))
        if offer.active:
            valid = latest if latest and not latest.suspicious else offer.observations.filter(suspicious=False).first()
            if valid:
                valid_latest.append(valid)
    if valid_latest:
        stats.best = min(valid_latest, key=lambda o: o.price)
        for row in stats.rows:
            row.is_best = row.latest is not None and row.latest.pk == stats.best.pk
    stats.supporting = supporting_offers(model)
    for so in stats.supporting:
        so.is_best = stats.best is not None and so.price <= stats.best.price
    stats.all_time_low = (
        PriceObservation.objects.filter(offer__model=model, suspicious=False).order_by("price", "fetched_at").first()
    )
    return stats


def supporting_offers(model: ProductModel) -> list[SupportingOffer]:
    """Unsupported shops from the model's active aggregator listings, cheapest per seller."""
    best = {}
    for so in SupportingOffer.objects.filter(source__model=model, source__active=True).select_related("source"):
        if so.seller not in best or so.price < best[so.seller].price:
            best[so.seller] = so
    return sorted(best.values(), key=lambda so: so.price)


def product_overview(product: Product) -> list[ModelStats]:
    return [model_stats(m) for m in product.variants.prefetch_related("offers")]


def products_with_best(user):
    """For the list page: each product with its cheapest current price across its models."""
    out = []
    for product in Product.objects.filter(user=user).prefetch_related("variants"):
        models = [model_stats(m) for m in product.variants.filter(active=True)]
        bests = [s.best for s in models if s.best]
        problems = Offer.objects.filter(
            model__product=product, active=True,
            status__in=[Offer.Status.BROKEN, Offer.Status.BLOCKED, Offer.Status.GONE, Offer.Status.SUSPICIOUS],
        ).count()
        out.append({
            "product": product,
            "model_count": len(models),
            "offer_count": Offer.objects.filter(model__product=product).count(),
            "best": min(bests, key=lambda o: o.price) if bests else None,
            "all_time_low": PriceObservation.objects.filter(offer__model__product=product, suspicious=False)
            .aggregate(low=Min("price"))["low"],
            "problems": problems,
        })
    return out


def chart_data(model: ProductModel) -> dict:
    """Chart.js datasets: one stepped line per offer, points = valid observations (x in ms since
    epoch). Active offers get a final point at "now" so a price that hasn't changed still draws a line."""
    now_ms = int(timezone.now().timestamp() * 1000)
    datasets = []
    for offer in model.offers.all():
        points = [
            {"x": int(o.fetched_at.timestamp() * 1000), "y": float(o.price)}
            for o in offer.observations.filter(suspicious=False).order_by("fetched_at")
        ]
        if not points:
            continue
        if offer.active and points[-1]["x"] < now_ms:
            points.append({"x": now_ms, "y": points[-1]["y"]})
        try:
            label = get_shop(offer.shop).name
        except KeyError:
            label = offer.shop
        datasets.append({"label": label, "data": points})
    return {"datasets": datasets}
