"""Durable, bounded outbound Webmention planning and delivery."""

from .delivery import deliver_webmention, discover_endpoint
from .outbox import OutboundQueue
from .planning import plan_mentions
from .service import OutboundService, OutboundWorker, UnavailableOutboundService


def open_outbound_service(root, **options):
    """Open the active service without making outbox trouble an app-start failure."""
    try:
        return OutboundService(OutboundQueue(root), **options)
    except Exception as error:
        return UnavailableOutboundService(error)


__all__ = (
    "OutboundQueue",
    "OutboundService",
    "OutboundWorker",
    "deliver_webmention",
    "discover_endpoint",
    "open_outbound_service",
    "plan_mentions",
)
