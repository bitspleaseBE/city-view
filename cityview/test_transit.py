"""Tests for OSM transit extraction, De Lijn enrichment, and viewer export."""

from __future__ import annotations

import io
import unittest
import zipfile

from cityview.gtfs_delijn import build_gtfs_subset, enrich_layout_transit
from cityview.osm import layout_from_osm, overpass_query
from cityview.streetscape import export_transit_near_spawn


def _mini_osm() -> dict:
    """Tiny Harmonie-like tram + bus snippet around a fake origin."""
    # Origin will be 51.20, 4.41 — nodes offset by ~0.001 deg (~100 m).
    return {
        "elements": [
            {"type": "node", "id": 1, "lat": 51.2000, "lon": 4.4100},
            {"type": "node", "id": 2, "lat": 51.2005, "lon": 4.4110},
            {"type": "node", "id": 3, "lat": 51.2010, "lon": 4.4120},
            {
                "type": "node",
                "id": 10,
                "lat": 51.2005,
                "lon": 4.4110,
                "tags": {"railway": "tram_stop", "name": "Gounod", "public_transport": "stop_position"},
            },
            {
                "type": "node",
                "id": 11,
                "lat": 51.20052,
                "lon": 4.41105,
                "tags": {"public_transport": "platform", "tram": "yes", "name": "Gounod"},
            },
            {
                "type": "node",
                "id": 12,
                "lat": 51.2008,
                "lon": 4.4095,
                "tags": {"highway": "bus_stop", "name": "Van Schoonbekestraat"},
            },
            {
                "type": "way",
                "id": 100,
                "nodes": [1, 2, 3],
                "tags": {"railway": "tram"},
            },
            {
                "type": "relation",
                "id": 200,
                "members": [{"type": "way", "ref": 100, "role": ""}],
                "tags": {"type": "route", "route": "tram", "ref": "8"},
            },
            {
                "type": "relation",
                "id": 201,
                "members": [{"type": "way", "ref": 100, "role": ""}],
                "tags": {"type": "route", "route": "tram", "ref": "9"},
            },
        ]
    }


def _gtfs_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "stops.txt",
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "S1,Gounod,51.20051,4.41102\n"
            "S2,Far Away,52.0,5.0\n",
        )
        zf.writestr(
            "routes.txt",
            "route_id,route_short_name,route_type\n"
            "R8,8,0\n"
            "R21,21,3\n",
        )
        zf.writestr(
            "trips.txt",
            "route_id,service_id,trip_id,shape_id\n"
            "R8,WD,T8,SH8\n"
            "R21,WD,T21,SH21\n",
        )
        zf.writestr(
            "stop_times.txt",
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T8,08:00:00,08:00:00,S1,1\n"
            "T21,08:05:00,08:05:00,S1,1\n",
        )
        zf.writestr(
            "shapes.txt",
            "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n"
            "SH8,51.2000,4.4100,1\n"
            "SH8,51.2005,4.4110,2\n"
            "SH8,51.2010,4.4120,3\n"
            "SH21,51.2008,4.4090,1\n"
            "SH21,51.2008,4.4105,2\n"
            "SH21,51.2008,4.4120,3\n",
        )
    return buf.getvalue()


class OverpassTransitQueryTests(unittest.TestCase):
    def test_query_includes_transit(self):
        q = overpass_query(51.19, 4.40, 51.21, 4.42)
        self.assertIn('way["railway"="tram"]', q)
        self.assertIn('node["highway"="bus_stop"]', q)
        self.assertIn('relation["route"~"^(tram|bus|subway|light_rail)$"]', q)


class OsmTransitLayoutTests(unittest.TestCase):
    def test_extracts_tram_line_and_stops(self):
        layout = layout_from_osm(_mini_osm(), (51.20, 4.41))
        lines = layout.get("transit_lines") or []
        stops = layout.get("transit_stops") or []
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["mode"], "tram")
        self.assertIn("8", lines[0]["refs"])
        self.assertIn("9", lines[0]["refs"])
        # Gounod stop_position + platform should dedupe to one named stop.
        gounod = [s for s in stops if s.get("name") == "Gounod"]
        self.assertEqual(len(gounod), 1)
        bus = [s for s in stops if s.get("mode") == "bus"]
        self.assertEqual(len(bus), 1)
        self.assertEqual(bus[0]["name"], "Van Schoonbekestraat")


class GtfsEnrichTests(unittest.TestCase):
    def test_enrich_attaches_delijn_lines(self):
        origin = (51.20, 4.41)
        bbox = (51.199, 4.408, 51.202, 4.413)
        layout = layout_from_osm(_mini_osm(), origin)
        subset = build_gtfs_subset(_gtfs_zip_bytes(), bbox, origin)
        self.assertGreaterEqual(len(subset["stops"]), 1)
        enrich_layout_transit(
            layout,
            origin,
            bbox,
            cache_path=__import__("pathlib").Path("/tmp/unused_gtfs_cache.json"),
            gtfs=subset,
        )
        gounod = next(s for s in layout["transit_stops"] if s.get("name") == "Gounod")
        self.assertEqual(gounod.get("delijn_stop_id"), "S1")
        self.assertTrue(any("8" in str(x) for x in gounod.get("lines") or []))
        # Bus shape should appear as a transit line.
        bus_paths = [ln for ln in layout["transit_lines"] if ln.get("mode") == "bus"]
        self.assertGreaterEqual(len(bus_paths), 1)


class ExportTransitTests(unittest.TestCase):
    def test_radius_filter(self):
        layout = {
            "transit_lines": [
                {
                    "id": 1,
                    "mode": "tram",
                    "lines": ["8"],
                    "points": [[0.0, 0.0], [40.0, 0.0]],
                },
                {
                    "id": 2,
                    "mode": "bus",
                    "lines": ["bus 21"],
                    "points": [[500.0, 500.0], [520.0, 500.0]],
                },
            ],
            "transit_stops": [
                {"id": 10, "mode": "tram", "name": "Near", "lines": ["8"], "x": 5.0, "y": 0.0},
                {"id": 11, "mode": "bus", "name": "Far", "lines": ["bus 21"], "x": 500.0, "y": 500.0},
            ],
        }
        payload = export_transit_near_spawn(layout, {"x": 0.0, "y": 0.0}, radius=100.0)
        self.assertEqual(len(payload["paths"]), 1)
        self.assertEqual(payload["paths"][0]["id"], 1)
        self.assertEqual(len(payload["stops"]), 1)
        self.assertEqual(payload["stops"][0]["name"], "Near")


if __name__ == "__main__":
    unittest.main()
