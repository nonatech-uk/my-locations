#!/usr/bin/env python3
"""
Generate a self-contained HTML visualization of location data.

Produces an interactive Leaflet map showing GPS location clusters, flight
routes, and airport visits. Cluster detection uses PostGIS ST_ClusterDBSCAN
(same algorithm as location_report.py but with a simpler threshold).

Flight route and airport data is read from /tmp/all_flights_airports.txt,
which is produced by airport_matcher.py.

The core cluster query is also available in queries.py:get_location_clusters_simple().
"""

import json
from collections import defaultdict
from db import get_connection

def get_location_clusters():
    """Get location clusters with visit counts."""
    conn = get_connection()
    cur = conn.cursor()

    # Cluster stationary points and count visits
    cur.execute("""
        WITH stationary AS (
            SELECT
                geom::geometry as geom,
                ts::date as visit_date,
                EXTRACT(YEAR FROM ts) as year
            FROM gps_points
            WHERE speed_mph IS NULL OR speed_mph <= 5
        ),
        clustered AS (
            SELECT
                ST_ClusterDBSCAN(geom, eps := 0.005, minpoints := 3) OVER() as cluster_id,
                geom,
                visit_date,
                year
            FROM stationary
        )
        SELECT
            cluster_id,
            COUNT(*) as total_points,
            COUNT(DISTINCT visit_date) as visit_days,
            AVG(ST_Y(geom)) as lat,
            AVG(ST_X(geom)) as lon,
            MIN(visit_date) as first_visit,
            MAX(visit_date) as last_visit,
            array_agg(DISTINCT year ORDER BY year) as years
        FROM clustered
        WHERE cluster_id IS NOT NULL
        GROUP BY cluster_id
        HAVING COUNT(DISTINCT visit_date) >= 2
        ORDER BY visit_days DESC
    """)

    clusters = []
    for row in cur.fetchall():
        clusters.append({
            'id': int(row[0]) if row[0] else 0,
            'points': int(row[1]),
            'visits': int(row[2]),
            'lat': float(row[3]),
            'lon': float(row[4]),
            'first': str(row[5]),
            'last': str(row[6]),
            'years': [int(y) for y in row[7]] if row[7] else []
        })

    cur.close()
    conn.close()
    return clusters

def get_flight_routes():
    """Get flight routes with frequency."""
    routes = defaultdict(lambda: {
        'count': 0,
        'start_lat': 0, 'start_lon': 0,
        'end_lat': 0, 'end_lon': 0,
        'start_code': '', 'end_code': '',
        'dates': []
    })

    with open('/tmp/all_flights_airports.txt', 'r') as f:
        for line in f:
            parts = line.strip().split('|')
            if len(parts) >= 10:
                start_code = parts[1] or f"({float(parts[2]):.1f},{float(parts[3]):.1f})"
                end_code = parts[5] or f"({float(parts[6]):.1f},{float(parts[7]):.1f})"
                key = f"{start_code}->{end_code}"

                routes[key]['count'] += 1
                routes[key]['start_lat'] = float(parts[2])
                routes[key]['start_lon'] = float(parts[3])
                routes[key]['end_lat'] = float(parts[6])
                routes[key]['end_lon'] = float(parts[7])
                routes[key]['start_code'] = start_code
                routes[key]['end_code'] = end_code
                routes[key]['distance'] = int(float(parts[8]))
                routes[key]['dates'].append(parts[0][:10])

    return [{'route': k, **v} for k, v in routes.items()]

def get_airport_visits():
    """Count visits per airport."""
    airports = defaultdict(lambda: {'arrivals': 0, 'departures': 0, 'lat': 0, 'lon': 0, 'code': ''})

    with open('/tmp/all_flights_airports.txt', 'r') as f:
        for line in f:
            parts = line.strip().split('|')
            if len(parts) >= 10:
                # Departure airport
                if parts[1]:
                    airports[parts[1]]['departures'] += 1
                    airports[parts[1]]['lat'] = float(parts[2])
                    airports[parts[1]]['lon'] = float(parts[3])
                    airports[parts[1]]['code'] = parts[1]

                # Arrival airport
                if parts[5]:
                    airports[parts[5]]['arrivals'] += 1
                    airports[parts[5]]['lat'] = float(parts[6])
                    airports[parts[5]]['lon'] = float(parts[7])
                    airports[parts[5]]['code'] = parts[5]

    return [{'code': k, 'total': v['arrivals'] + v['departures'], **v}
            for k, v in airports.items() if v['code']]

def generate_html(clusters, routes, airports):
    """Generate the visualization HTML."""

    # Sort for display
    top_airports = sorted(airports, key=lambda x: -x['total'])[:50]
    top_routes = sorted(routes, key=lambda x: -x['count'])[:100]
    top_clusters = clusters[:200]

    html = f'''<!DOCTYPE html>
<html>
<head>
    <title>My Location History</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        #map {{ position: absolute; top: 0; left: 0; right: 300px; bottom: 0; }}
        #sidebar {{ position: absolute; top: 0; right: 0; width: 300px; bottom: 0;
                   background: #1a1a2e; color: #eee; overflow-y: auto; }}
        .panel {{ padding: 15px; border-bottom: 1px solid #333; }}
        .panel h3 {{ margin-bottom: 10px; color: #4ecdc4; font-size: 14px; text-transform: uppercase; }}
        .stat {{ display: flex; justify-content: space-between; padding: 5px 0; font-size: 13px; }}
        .stat-value {{ color: #4ecdc4; font-weight: bold; }}
        .list-item {{ padding: 8px; margin: 4px 0; background: #16213e; border-radius: 4px;
                     font-size: 12px; cursor: pointer; }}
        .list-item:hover {{ background: #1f4068; }}
        .count {{ float: right; background: #4ecdc4; color: #1a1a2e; padding: 2px 8px;
                 border-radius: 10px; font-weight: bold; }}
        .controls {{ padding: 10px; background: #16213e; }}
        .controls label {{ display: block; margin: 5px 0; font-size: 12px; }}
        .controls input {{ margin-right: 8px; }}
        h2 {{ padding: 15px; background: #16213e; font-size: 16px; }}
        .legend {{ display: flex; gap: 15px; padding: 10px; font-size: 11px; flex-wrap: wrap; }}
        .legend-item {{ display: flex; align-items: center; gap: 5px; }}
        .legend-dot {{ width: 12px; height: 12px; border-radius: 50%; }}
    </style>
</head>
<body>
    <div id="map"></div>
    <div id="sidebar">
        <h2>Location History</h2>

        <div class="panel">
            <h3>Statistics</h3>
            <div class="stat"><span>Total GPS Points</span><span class="stat-value">116,203</span></div>
            <div class="stat"><span>Locations Visited</span><span class="stat-value">{len(clusters)}</span></div>
            <div class="stat"><span>Airports Used</span><span class="stat-value">{len(airports)}</span></div>
            <div class="stat"><span>Flight Routes</span><span class="stat-value">{len(routes)}</span></div>
            <div class="stat"><span>Total Flights</span><span class="stat-value">{sum(r['count'] for r in routes)}</span></div>
        </div>

        <div class="controls">
            <h3>Layers</h3>
            <label><input type="checkbox" id="showClusters" checked> Location Clusters</label>
            <label><input type="checkbox" id="showAirports" checked> Airports</label>
            <label><input type="checkbox" id="showRoutes" checked> Flight Routes</label>
        </div>

        <div class="panel">
            <div class="legend">
                <div class="legend-item"><div class="legend-dot" style="background:#ff6b6b"></div> Home bases (50+ days)</div>
                <div class="legend-item"><div class="legend-dot" style="background:#4ecdc4"></div> Regular (10-49 days)</div>
                <div class="legend-item"><div class="legend-dot" style="background:#45b7d1"></div> Visited (2-9 days)</div>
                <div class="legend-item"><div class="legend-dot" style="background:#f9ca24"></div> Airports</div>
            </div>
        </div>

        <div class="panel">
            <h3>Top Airports</h3>
            {generate_airport_list(top_airports[:15])}
        </div>

        <div class="panel">
            <h3>Top Routes</h3>
            {generate_route_list(top_routes[:15])}
        </div>
    </div>

    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
        const clusters = {json.dumps(top_clusters)};
        const routes = {json.dumps(top_routes)};
        const airports = {json.dumps(top_airports)};

        // Initialize map
        const map = L.map('map').setView([51.5, -0.1], 5);
        L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
            attribution: '&copy; OpenStreetMap, &copy; CARTO'
        }}).addTo(map);

        // Layer groups
        const clusterLayer = L.layerGroup().addTo(map);
        const airportLayer = L.layerGroup().addTo(map);
        const routeLayer = L.layerGroup().addTo(map);

        // Add clusters
        clusters.forEach(c => {{
            const color = c.visits >= 50 ? '#ff6b6b' : c.visits >= 10 ? '#4ecdc4' : '#45b7d1';
            const radius = Math.min(Math.max(Math.sqrt(c.visits) * 2, 5), 25);
            L.circleMarker([c.lat, c.lon], {{
                radius: radius,
                fillColor: color,
                color: '#fff',
                weight: 1,
                fillOpacity: 0.7
            }}).bindPopup(`<b>${{c.visits}} days</b><br>${{c.first}} to ${{c.last}}<br>${{c.points}} points`).addTo(clusterLayer);
        }});

        // Add airports
        airports.forEach(a => {{
            const radius = Math.min(Math.max(Math.sqrt(a.total) * 3, 6), 20);
            L.circleMarker([a.lat, a.lon], {{
                radius: radius,
                fillColor: '#f9ca24',
                color: '#fff',
                weight: 2,
                fillOpacity: 0.8
            }}).bindPopup(`<b>${{a.code}}</b><br>Departures: ${{a.departures}}<br>Arrivals: ${{a.arrivals}}<br>Total: ${{a.total}}`).addTo(airportLayer);
        }});

        // Add routes
        routes.forEach(r => {{
            const weight = Math.min(Math.max(r.count * 0.5, 1), 6);
            const opacity = Math.min(0.3 + r.count * 0.05, 0.8);
            L.polyline([[r.start_lat, r.start_lon], [r.end_lat, r.end_lon]], {{
                color: '#4ecdc4',
                weight: weight,
                opacity: opacity
            }}).bindPopup(`<b>${{r.start_code}} → ${{r.end_code}}</b><br>${{r.count}} flights<br>${{r.distance}} km`).addTo(routeLayer);
        }});

        // Layer toggles
        document.getElementById('showClusters').onchange = e => {{
            e.target.checked ? clusterLayer.addTo(map) : clusterLayer.remove();
        }};
        document.getElementById('showAirports').onchange = e => {{
            e.target.checked ? airportLayer.addTo(map) : airportLayer.remove();
        }};
        document.getElementById('showRoutes').onchange = e => {{
            e.target.checked ? routeLayer.addTo(map) : routeLayer.remove();
        }};

        // Click handlers for sidebar
        document.querySelectorAll('.airport-item').forEach(el => {{
            el.onclick = () => {{
                const code = el.dataset.code;
                const a = airports.find(x => x.code === code);
                if (a) map.flyTo([a.lat, a.lon], 10);
            }};
        }});
        document.querySelectorAll('.route-item').forEach(el => {{
            el.onclick = () => {{
                const route = el.dataset.route;
                const r = routes.find(x => x.route === route);
                if (r) {{
                    const bounds = L.latLngBounds([[r.start_lat, r.start_lon], [r.end_lat, r.end_lon]]);
                    map.fitBounds(bounds, {{padding: [50, 50]}});
                }}
            }};
        }});
    </script>
</body>
</html>'''
    return html

def generate_airport_list(airports):
    items = []
    for a in airports:
        items.append(f'<div class="list-item airport-item" data-code="{a["code"]}">'
                    f'{a["code"]} <span class="count">{a["total"]}</span></div>')
    return '\n'.join(items)

def generate_route_list(routes):
    items = []
    for r in routes:
        items.append(f'<div class="list-item route-item" data-route="{r["route"]}">'
                    f'{r["start_code"]} → {r["end_code"]} <span class="count">{r["count"]}</span></div>')
    return '\n'.join(items)

if __name__ == '__main__':
    print("Generating visualization...")

    print("  Loading location clusters...")
    clusters = get_location_clusters()
    print(f"    Found {len(clusters)} clusters")

    print("  Loading flight routes...")
    routes = get_flight_routes()
    print(f"    Found {len(routes)} unique routes")

    print("  Loading airport stats...")
    airports = get_airport_visits()
    print(f"    Found {len(airports)} airports")

    print("  Generating HTML...")
    html = generate_html(clusters, routes, airports)

    output_file = '/home/stu/location_map.html'
    with open(output_file, 'w') as f:
        f.write(html)

    print(f"\nVisualization saved to: {output_file}")
    print("Open in browser to view.")
