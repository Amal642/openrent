"""
Compatibility shim for the old WhatsApp Playwright worker.

WhatsApp automation is now fully handled through Kapso. Keep this module so
existing imports such as app.whatsapp.browser_worker.get_worker continue to work.
"""
from app.whatsapp.kapso_worker import (
    KapsoWhatsAppWorker,
    get_worker,
    start_whatsapp_worker,
    stop_whatsapp_worker,
)

WhatsAppWebWorker = KapsoWhatsAppWorker
