"""Web UI (PLAN.md section 8). v1: localhost only, no login; everything acts as the owner."""

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from procrastinate.exceptions import AlreadyEnqueued

from .forms import OfferForm, ProductForm, ProductModelForm, SettingsForm
from .models import CheckFailure, DiscoveryRun, MatchReview, Offer, Product, ProductModel
from .owner import get_owner
from .queries import OfferRow, chart_data, model_stats, product_overview, products_with_best
from .shops import all_shops


def _product(pk):
    return get_object_or_404(Product, pk=pk, user=get_owner())


def _model(pk):
    return get_object_or_404(ProductModel, pk=pk, product__user=get_owner())


def _offer(pk):
    return get_object_or_404(Offer, pk=pk, model__product__user=get_owner())


# --- products ------------------------------------------------------------------------------------


def product_list(request):
    return render(request, "scout/product_list.html", {"products": products_with_best(get_owner())})


def product_create(request):
    form = ProductForm(request.POST or None, user=get_owner())
    if request.method == "POST" and form.is_valid():
        product = form.save(commit=False)
        product.user = get_owner()
        product.save()
        if form.cleaned_data["discover"]:
            return redirect("discovery_detail", pk=_start_discovery(product).pk)
        messages.success(request, f"Added {product.name}. Now add the exact models you want to observe.")
        return redirect("product_detail", pk=product.pk)
    return render(request, "scout/product_form.html", {"form": form, "title": "Add product"})


def product_edit(request, pk):
    product = _product(pk)
    form = ProductForm(request.POST or None, instance=product, user=get_owner())
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("product_detail", pk=product.pk)
    return render(request, "scout/product_form.html", {"form": form, "title": f"Edit {product.name}", "product": product})


@require_POST
def product_delete(request, pk):
    product = _product(pk)
    messages.success(request, f"Deleted {product.name} and its price history.")
    product.delete()
    return redirect("product_list")


def product_detail(request, pk):
    product = _product(pk)
    stats = product_overview(product)
    for s in stats:
        s.chart = chart_data(s.model)
        s.chart_id = f"chart-{s.model.pk}"
        s.reviews = MatchReview.objects.filter(offer__model=s.model, decision__isnull=True).select_related("offer")
    return render(request, "scout/product_detail.html", {
        "product": product,
        "stats": stats,
        "model_form": ProductModelForm(product=product),
        "shops": sorted(all_shops(), key=lambda s: s.name),
    })


# --- discovery wizard ----------------------------------------------------------------------------


def _start_discovery(product) -> DiscoveryRun:
    from .tasks import discover_models_task

    run = DiscoveryRun.objects.create(product=product, query=product.name)
    with transaction.atomic():
        discover_models_task.defer(run_id=run.pk)
    return run


@require_POST
def discovery_start(request, pk):
    return redirect("discovery_detail", pk=_start_discovery(_product(pk)).pk)


def _run(pk):
    return get_object_or_404(DiscoveryRun, pk=pk, product__user=get_owner())


def _offer_rows(run):
    """Offer candidates grouped by model, with the default selection."""
    groups = []
    for code, cands in run.results.get("offers", {}).items():
        existing = Offer.objects.filter(model__product=run.product, model__code=code)
        known_urls = set(existing.values_list("url", flat=True))
        known_shops = set(existing.values_list("shop", flat=True))
        listings = [c for c in cands if c["shop"] == "ceneo"]
        main_listing = max(listings, key=lambda c: c.get("offer_count", 0), default=None)
        rows = []
        for i, c in enumerate(cands):
            observed = c["url"] in known_urls
            same_shop = not observed and c["shop"] in known_shops
            preselect = (c["verdict"] == "yes" and not observed and not same_shop
                         and (c["shop"] != "ceneo" or c is main_listing))
            rows.append({**c, "key": f"{code}|{i}", "checked": preselect, "observed": observed, "same_shop": same_shop})
        groups.append({"code": code, "rows": rows})
    return groups


def discovery_detail(request, pk):
    run = _run(pk)
    existing = set(run.product.variants.values_list("code", flat=True))
    ctx = {
        "run": run,
        "running": run.status in (DiscoveryRun.Status.PENDING, DiscoveryRun.Status.RUNNING),
        "models": [{**m, "idx": i, "exists": m["code"] in existing} for i, m in enumerate(run.results.get("models", []))],
        "offer_groups": _offer_rows(run),
        "applied": run.results.get("applied", False),
    }
    template = "scout/partials/discovery_body.html" if request.headers.get("HX-Request") else "scout/discovery.html"
    return render(request, template, ctx)


@require_POST
def discovery_models(request, pk):
    from .tasks import discover_offers_task

    run = _run(pk)
    found = run.results.get("models", [])
    selected = []
    for idx in request.POST.getlist("pick"):
        try:
            m = found[int(idx)]
        except (ValueError, IndexError):
            continue
        code = request.POST.get(f"code_{idx}", m["code"]).strip().upper() or m["code"]
        selected.append({**m, "code": code})
    if not selected:
        messages.error(request, "Pick at least one model, or add models by hand on the product page.")
        return redirect("discovery_detail", pk=run.pk)
    for m in selected:
        ProductModel.objects.get_or_create(product=run.product, code=m["code"])
    run.results = {**run.results, "selected": selected}
    run.stage, run.status = DiscoveryRun.Stage.OFFERS, DiscoveryRun.Status.PENDING
    run.save(update_fields=["results", "stage", "status"])
    run.log(f"Looking for offers for {', '.join(m['code'] for m in selected)}...")
    with transaction.atomic():
        discover_offers_task.defer(run_id=run.pk)
    return redirect("discovery_detail", pk=run.pk)


@require_POST
def discovery_offers(request, pk):
    from .shops import get_shop

    run = _run(pk)
    chosen = set(request.POST.getlist("offer"))
    created = 0
    for group in _offer_rows(run):
        model = ProductModel.objects.filter(product=run.product, code=group["code"]).first()
        if model is None:
            continue
        for row in group["rows"]:
            if row["key"] not in chosen:
                continue
            shop = get_shop(row["shop"])
            _, new = Offer.objects.get_or_create(model=model, url=row["url"], defaults={
                "shop": shop.key, "kind": shop.kind, "match_confirmed": row["verdict"] == "yes",
            })
            created += new
    run.results = {**run.results, "applied": True}
    run.save(update_fields=["results"])
    messages.success(request, f"Now observing {created} new offer(s). First checks within 5 minutes.")
    return redirect("product_detail", pk=run.product_id)


# --- models --------------------------------------------------------------------------------------


@require_POST
def model_create(request, pk):
    product = _product(pk)
    form = ProductModelForm(request.POST, product=product)
    if form.is_valid():
        model = form.save(commit=False)
        model.product = product
        model.save()
        messages.success(request, f"Added model {model.code}.")
    else:
        for errors in form.errors.values():
            for e in errors:
                messages.error(request, e)
    return redirect("product_detail", pk=product.pk)


@require_POST
def model_toggle(request, pk):
    model = _model(pk)
    model.active = not model.active
    model.save(update_fields=["active"])
    return redirect("product_detail", pk=model.product_id)


@require_POST
def model_delete(request, pk):
    model = _model(pk)
    product_id = model.product_id
    messages.success(request, f"Deleted model {model.code}.")
    model.delete()
    return redirect("product_detail", pk=product_id)


# --- offers --------------------------------------------------------------------------------------


@require_POST
def offer_create(request, pk):
    model = _model(pk)
    form = OfferForm(request.POST, model=model)
    if form.is_valid():
        offer = form.save()
        messages.success(request, f"Now observing {offer.shop} for {model.code}. First check within 5 minutes.")
    else:
        for e in form.errors.get("url", []):
            messages.error(request, e)
    return redirect("product_detail", pk=model.product_id)


def _offer_row(request, offer, note=""):
    stats = model_stats(offer.model)
    row = next((r for r in stats.rows if r.offer.pk == offer.pk), OfferRow(offer=offer, latest=None))
    return render(request, "scout/partials/offer_row.html", {"row": row, "note": note})


@require_POST
def offer_toggle(request, pk):
    offer = _offer(pk)
    offer.active = not offer.active
    if offer.active:
        offer.next_check_at = timezone.now()  # resume: check soon
    offer.save(update_fields=["active", "next_check_at"])
    return _offer_row(request, offer)


@require_POST
def offer_check(request, pk):
    from .tasks import check_offer_task

    offer = _offer(pk)
    try:
        with transaction.atomic():  # savepoint: a duplicate-lock error must not poison the outer transaction
            check_offer_task.configure(queueing_lock=f"check_offer-{offer.pk}").defer(offer_id=offer.pk)
        note = "Check queued, reload in a minute."
    except AlreadyEnqueued:
        note = "A check is already queued."
    return _offer_row(request, offer, note)


@require_POST
def offer_delete(request, pk):
    offer = _offer(pk)
    product_id = offer.model.product_id
    offer.delete()
    if request.headers.get("HX-Request"):
        return render(request, "scout/partials/empty.html")
    return redirect("product_detail", pk=product_id)


def offer_detail(request, pk):
    offer = _offer(pk)
    return render(request, "scout/offer_detail.html", {
        "offer": offer,
        "observations": offer.observations.all()[:100],
        "failures": CheckFailure.objects.filter(offer=offer)[:50],
    })


@require_POST
def review_decide(request, pk):
    review = get_object_or_404(MatchReview, pk=pk, offer__model__product__user=get_owner())
    offer = review.offer
    same = request.POST.get("decision") == "same"
    review.decision = same
    review.save(update_fields=["decision"])
    if same:
        offer.match_confirmed = True
        offer.status = Offer.Status.OK
        offer.next_check_at = timezone.now()
        messages.success(request, f"Confirmed: {offer.shop} sells {offer.model.code}. Checking it again shortly.")
    else:
        offer.active = False
        messages.success(request, f"Paused the {offer.shop} offer: it is a different model.")
    offer.save()
    return redirect("product_detail", pk=offer.model.product_id)


# --- settings ------------------------------------------------------------------------------------


def settings_view(request):
    cfg = get_owner().scout_settings
    form = SettingsForm(request.POST or None, instance=cfg)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Settings saved.")
        return redirect("settings")
    return render(request, "scout/settings.html", {"form": form})
