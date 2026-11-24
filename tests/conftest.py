import pytest


@pytest.fixture(autouse=True)
def _fast_and_isolated(settings, tmp_path):
    settings.SCOUT_SHOP_GAP_SECONDS = (0, 0)
    settings.SCOUT_VAR_DIR = str(tmp_path / "var")
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.GEMINI_API_KEY = ""  # never call the real API from tests
