from core.events.dispatcher import register
from inventory.events.handlers.delivery import handle_picking_cancelled, handle_picking_confirmed

from inventory.events.types import InventoryEventType



def register_handlers():

    register(
        InventoryEventType.PICKING_CANCELLED,
        handle_picking_cancelled,
    )

    register(
        InventoryEventType.PICKING_CONFIRMED,
    handle_picking_confirmed,
    )

