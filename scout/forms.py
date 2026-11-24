from django import forms

from .models import Offer, Product, ProductModel, Settings
from .shops import all_shops, shop_for_url


class ProductForm(forms.ModelForm):
    discover = forms.BooleanField(
        required=False, initial=True,
        label="Find models and offers automatically (Ceneo search + Gemini)",
    )

    class Meta:
        model = Product
        fields = ["name", "active"]

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if self.instance.pk:  # editing: discovery is started from the product page instead
            del self.fields["discover"]

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        dupes = Product.objects.filter(user=self.user, name__iexact=name).exclude(pk=self.instance.pk)
        if dupes.exists():
            raise forms.ValidationError("You already observe a product with this name.")
        return name


class ProductModelForm(forms.ModelForm):
    class Meta:
        model = ProductModel
        fields = ["code", "ean"]
        labels = {"code": "Model code", "ean": "EAN (optional)"}

    def __init__(self, *args, product, **kwargs):
        super().__init__(*args, **kwargs)
        self.product = product

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        if ProductModel.objects.filter(product=self.product, code=code).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This model is already on the list.")
        return code


class OfferForm(forms.ModelForm):
    url = forms.URLField(label="Offer URL", max_length=1000, assume_scheme="https")

    class Meta:
        model = Offer
        fields = ["url"]

    def __init__(self, *args, model, **kwargs):
        super().__init__(*args, **kwargs)
        self.model_obj = model
        self.shop = None

    def clean_url(self):
        url = self.cleaned_data["url"].strip()
        self.shop = shop_for_url(url)
        if self.shop is None:
            supported = ", ".join(sorted(s.name for s in all_shops()))
            raise forms.ValidationError(f"Shop not supported yet. Supported shops: {supported}.")
        if Offer.objects.filter(model=self.model_obj, url=url).exists():
            raise forms.ValidationError("This URL is already observed for this model.")
        return url

    def save(self, commit=True):
        offer = super().save(commit=False)
        offer.model = self.model_obj
        offer.shop = self.shop.key
        offer.kind = self.shop.kind
        if commit:
            offer.save()
        return offer


class SettingsForm(forms.ModelForm):
    class Meta:
        model = Settings
        fields = ["check_interval_hours", "summary_interval_hours", "notify_email", "outlier_pct", "broken_after_failures"]
        labels = {
            "check_interval_hours": "Check prices every (hours)",
            "summary_interval_hours": "Send summary every (hours)",
            "notify_email": "Send emails to",
            "outlier_pct": "Hold back prices that differ from the recent median by more than (%)",
            "broken_after_failures": "Mark an offer broken after this many failed checks in a row",
        }
        help_texts = {"notify_email": "Leave empty to use SCOUT_NOTIFY_EMAIL from .env."}

    def clean_check_interval_hours(self):
        v = self.cleaned_data["check_interval_hours"]
        if v < 1:
            raise forms.ValidationError("At least 1 hour, to stay polite to the shops.")
        return v

    def clean_summary_interval_hours(self):
        v = self.cleaned_data["summary_interval_hours"]
        if v < 1:
            raise forms.ValidationError("At least 1 hour.")
        return v
