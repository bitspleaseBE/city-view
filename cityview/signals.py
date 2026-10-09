"""Traffic-signal facing helpers shared by the Blender builder and roads.json export.

Street furniture in this project uses Blender ``rotation_z`` with **local +Y as the
front**. After rotating by ``yaw``, local +Y points to ``(-sin yaw, cos yaw)``.
"""

from __future__ import annotations

import math


def face_yaw(fx: float, fy: float) -> float:
    """``rotation_z`` that turns local +Y onto world ``(fx, fy)``."""
    length = math.hypot(fx, fy)
    if length < 1e-9:
        return 0.0
    return math.atan2(fy / length, fx / length) - math.pi / 2.0


def face_dir(yaw: float) -> tuple[float, float]:
    """World XY direction of local +Y after ``rotation_z = yaw``."""
    return (-math.sin(yaw), math.cos(yaw))


def vehicle_signal_yaw(tx: float, ty: float) -> float:
    """Yaw so the head faces oncoming traffic for inbound approach tangent ``(tx, ty)``.

    Drivers travel along ``(tx, ty)`` toward the junction; the lenses look back at them.
    """
    return face_yaw(-tx, -ty)


def pedestrian_signal_yaw(rx: float, ry: float, side: float) -> float:
    """Yaw so a pedestrian head on the curb faces people waiting to cross.

    ``(rx, ry)`` is the right-hand perpendicular of the inbound tangent; ``side`` is
    ``+1`` when the pole sits on that right curb (``-1`` on the left). The face looks
    across the carriageway from the curb (into the zebra).
    """
    return face_yaw(-rx * side, -ry * side)
