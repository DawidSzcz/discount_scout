"""Web UI (PLAN.md section 8). v1: localhost only, no login; everything acts as the owner."""

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from procrastinate.exceptions import AlreadyEnqueued

from .forms import OfferForm, ProductForm, ProductModelForm, SettingsForm
from .models import CheckFailure, Offer, Product, ProductModel
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
    return render(request, "scout/product_detail.html", {
        "product": product,
        "stats": stats,
        "model_form": ProductModelForm(product=product),
        "shops": sorted(all_shops(), key=lambda s: s.name),
    })


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


# --- settings ------------------------------------------------------------------------------------


def settings_view(request):
    cfg = get_owner().scout_settings
    form = SettingsForm(request.POST or None, instance=cfg)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Settings saved.")
        return redirect("settings")
    return render(request, "scout/settings.html", {"form": form})
