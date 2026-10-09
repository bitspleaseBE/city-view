/**
 * Tiny rendezvous between traffic.js (cars) and transit.js (trams / buses) so the two sims can
 * see each other without any wiring in index.html:
 *
 *   laneAt(x, z, tx, tz, out, mode = "car") -> true | false
 *       Centre of the lane a vehicle heading (tx, tz) should use on the car road nearest to
 *       (x, z), written to out.x / out.z. False when no car road runs within a few metres
 *       that the vehicle may legally drive in that direction (one-way streets; `mode` "bus"
 *       honours oneway:bus, e.g. contraflow bus lanes).
 *       Buses use it so they drive in the exact lane cars use (GTFS bus shapes sit 1-4 m off
 *       the OSM centreline, which is why oncoming buses used to clip the cars they passed).
 *   cars -> the live car list, so buses / trams brake for cars in front of them instead of
 *       driving through them.
 */
export const shared = { laneAt: null, cars: null };
