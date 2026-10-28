from django.core.management.base import BaseCommand, CommandError

from orders.ai import AIServiceError
from orders.knowledge import index_playbooks


class Command(BaseCommand):
    help = "Create or refresh the Gemini embedding index for the generic operations playbooks."

    def handle(self, *args, **options):
        try:
            count = index_playbooks()
        except AIServiceError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Indexed {count} operations playbook entries."))
