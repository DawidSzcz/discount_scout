from django.core.management.base import BaseCommand

from scout.notify import collect_summary, render_summary, send_summary
from scout.owner import get_owner


class Command(BaseCommand):
    help = "Send (or preview) the summary email for the owner now."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="send even if nothing changed")
        parser.add_argument("--preview", action="store_true", help="print it instead of sending")

    def handle(self, force, preview, **opts):
        cfg = get_owner().scout_settings
        if preview:
            subject, body = render_summary(collect_summary(cfg))
            self.stdout.write(f"Subject: {subject}\n\n{body}")
            return
        sent = send_summary(cfg, force=force)
        self.stdout.write("sent" if sent else "not sent (nothing changed, or no recipient configured)")
