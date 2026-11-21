"""Strict full-description contract for explicit MATSim 15 population routes.

The text includes endpoints; NetworkRoute.setLinkIds() has a different contract.
Legacy intermediate-only descriptions are rejected, never guessed or repaired.
"""


def validate_link_route(route, expected, *, origin, destination, vehicle_id):
    path = (route.text or '').split() if route is not None else []
    if (not path or route.get('type') != 'links' or path != expected or
            route.get('start_link') != path[0] or route.get('end_link') != path[-1] or
            origin != path[0] or destination != path[-1] or
            route.get('vehicleRefId') != vehicle_id):
        raise ValueError('Explicit links XML differs from full route/activities/vehicle identity')
    return path
