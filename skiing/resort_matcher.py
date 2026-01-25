#!/usr/bin/env python3
"""
Match skiing GPS points to ski resorts.

For each skiing_day:
1. Get first few GPS points for that day
2. Find nearest ski resort within threshold
3. If no resort found, use reverse geocoding for general location
4. Update skiing_days.location
"""

import sys
from pathlib import Path
from math import radians, sin, cos, sqrt, atan2

sys.path.insert(0, str(Path(__file__).parent.parent))
import db

# Ski resorts database: name -> (lat, lon)
# Compiled from common European and North American resorts
RESORTS = {
    # Switzerland
    "Zermatt": (46.0207, 7.7491),
    "Verbier": (46.0967, 7.2286),
    "Grimentz": (46.1833, 7.5750),
    "Andermatt": (46.6333, 8.5833),
    "Engelberg": (46.8200, 8.4000),
    "Saas-Fee": (46.1083, 7.9275),
    "Saas Almagell": (46.0983, 7.9483),
    "Crans-Montana": (46.3167, 7.4833),
    "Anzère": (46.3000, 7.4000),
    "Leukerbad": (46.3833, 7.6333),
    "Lötschental": (46.4167, 7.7833),
    "Chandolin": (46.2500, 7.6000),
    "Bettmeralp": (46.3833, 8.0500),

    # Italy
    "Breuil-Cervinia": (45.9333, 7.6333),
    "Courmayeur": (45.7917, 6.9667),
    "Gressoney-La-Trinité": (45.8333, 7.8167),
    "La Thuile": (45.7167, 6.9500),
    "Livigno": (46.5333, 10.1333),
    "Val di Fassa": (46.4333, 11.7667),
    "Alta Badia": (46.5500, 11.8833),
    "San Cassiano": (46.5667, 11.9333),
    "Passo Sella": (46.5000, 11.7500),
    "Canazei": (46.4767, 11.7700),

    # France
    "Chamonix": (45.9237, 6.8694),
    "Tignes": (45.4692, 6.9056),
    "Val d'Isère": (45.4481, 6.9797),
    "Les Arcs": (45.5700, 6.8200),
    "La Plagne": (45.5000, 6.6833),
    "Courchevel": (45.4167, 6.6333),
    "Méribel": (45.4000, 6.5667),
    "La Tania": (45.4333, 6.5833),
    "Les Menuires": (45.3333, 6.5333),
    "Val Thorens": (45.2983, 6.5800),
    "Flaine": (46.0058, 6.6897),
    "Les Contamines": (45.8200, 6.7300),
    "Argentière": (45.9833, 6.9333),
    "Serre Chevalier": (44.9333, 6.5000),
    "Briançon": (44.9000, 6.6333),
    "Monêtier-les-Bains": (44.9764, 6.5094),

    # Austria
    "Kitzsteinhorn": (47.1833, 12.6833),
    "Kaprun": (47.2667, 12.7500),
    "Zell am See": (47.3167, 12.8000),
    "St. Anton": (47.1297, 10.2672),
    "Ischgl": (46.9667, 10.2833),
    "Sölden": (46.9667, 10.8667),

    # Spain
    "Baqueira Beret": (42.7000, 0.9500),

    # Dolomites area
    "Falzarego": (46.5200, 12.0000),
    "Cortina d'Ampezzo": (46.5369, 12.1358),

    # Canada
    "Kicking Horse": (51.2975, -117.0475),
    "Revelstoke": (51.0000, -118.1833),

    # Norway
    "Longyearbyen": (78.2200, 15.6300),
    "Lyngen Alps": (69.6500, 20.2000),
    "Tromsø": (69.6500, 18.8500),
}


def haversine_km(lat1, lon1, lat2, lon2):
    """Calculate distance between two points in km."""
    R = 6371  # Earth radius in km

    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))

    return R * c


def find_nearest_resort(lat, lon, max_distance_km=30):
    """Find nearest ski resort within max_distance_km."""
    nearest = None
    nearest_dist = float('inf')

    for name, (rlat, rlon) in RESORTS.items():
        dist = haversine_km(lat, lon, rlat, rlon)
        if dist < nearest_dist:
            nearest_dist = dist
            nearest = name

    if nearest_dist <= max_distance_km:
        return nearest, nearest_dist
    return None, nearest_dist


def reverse_geocode_simple(lat, lon):
    """Simple reverse geocoding using known regions."""
    # Svalbard
    if lat > 76:
        return "Svalbard"

    # Northern Norway (Tromsø/Lyngen area)
    if 69 < lat < 71 and 17 < lon < 22:
        return "Northern Norway"

    # Canadian Rockies
    if 50 < lat < 53 and -120 < lon < -115:
        return "Canadian Rockies"

    # Alps regions by rough coordinates
    if 45 < lat < 47:
        if 6 < lon < 8:
            return "Swiss/French Alps"
        if 8 < lon < 10:
            return "Swiss Alps"
        if 10 < lon < 13:
            return "Italian Dolomites"

    if 46 < lat < 48 and 10 < lon < 14:
        return "Austrian Alps"

    if 42 < lat < 43 and 0 < lon < 2:
        return "Pyrenees"

    return f"Unknown ({lat:.2f}, {lon:.2f})"


def match_skiing_days():
    """Match all skiing days to resorts based on GPS data."""
    conn = db.get_connection()
    cur = conn.cursor()

    # Get all skiing days with their first few GPS points
    cur.execute("""
        WITH ranked_points AS (
            SELECT
                d.date,
                d.location as current_location,
                p.lat,
                p.lon,
                ROW_NUMBER() OVER (PARTITION BY d.date ORDER BY p.ts) as rn
            FROM skiing_days d
            JOIN gps_points p ON DATE(p.ts) = d.date AND p.source_type = 'skitracks'
        )
        SELECT date, current_location, lat, lon
        FROM ranked_points
        WHERE rn <= 5
        ORDER BY date, rn
    """)

    rows = cur.fetchall()

    # Group points by date
    from collections import defaultdict
    days = defaultdict(list)
    current_locs = {}
    for date, current_loc, lat, lon in rows:
        days[date].append((lat, lon))
        current_locs[date] = current_loc

    print(f"Processing {len(days)} skiing days...")

    updates = []
    for date, points in sorted(days.items()):
        # Average the first few points
        avg_lat = sum(p[0] for p in points) / len(points)
        avg_lon = sum(p[1] for p in points) / len(points)

        # Find nearest resort
        resort, dist = find_nearest_resort(avg_lat, avg_lon)

        if resort:
            new_location = resort
        else:
            # Fall back to general location
            new_location = reverse_geocode_simple(avg_lat, avg_lon)

        current = current_locs.get(date, "")
        if current != new_location:
            updates.append((new_location, date, current))

    # Apply updates
    if updates:
        print(f"\nUpdating {len(updates)} locations:")
        for new_loc, date, old_loc in updates[:20]:
            print(f"  {date}: {old_loc[:30]:30s} -> {new_loc}")
        if len(updates) > 20:
            print(f"  ... and {len(updates) - 20} more")

        cur.executemany(
            "UPDATE skiing_days SET location = %s WHERE date = %s",
            [(new_loc, date) for new_loc, date, _ in updates]
        )
        conn.commit()
        print(f"\nUpdated {cur.rowcount} rows")
    else:
        print("No updates needed")

    cur.close()
    conn.close()


def show_stats():
    """Show current location statistics."""
    conn = db.get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT location, COUNT(*) as days
        FROM skiing_days
        GROUP BY location
        ORDER BY days DESC
    """)

    print("\nCurrent resort breakdown:")
    for loc, count in cur.fetchall():
        print(f"  {loc or 'NULL':30s}: {count:3d} days")

    cur.close()
    conn.close()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Match skiing days to resorts')
    parser.add_argument('--dry-run', action='store_true', help='Show what would change without updating')
    parser.add_argument('--stats', action='store_true', help='Show current location statistics')
    args = parser.parse_args()

    if args.stats:
        show_stats()
    else:
        match_skiing_days()
        print("\nAfter matching:")
        show_stats()
