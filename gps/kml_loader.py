#!/usr/bin/env python3
"""Load GPS points from KML files into the database."""

import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import config
import db

# KML namespace
NS = {'kml': 'http://earth.google.com/kml/2.2'}
NS_URI = '{http://earth.google.com/kml/2.2}'


def find_element(parent, local_name):
    """Find element handling namespace properly."""
    # Try with namespace first (most common)
    elem = parent.find(f'.//{NS_URI}{local_name}')
    if elem is not None:
        return elem
    # Fallback to no namespace
    return parent.find(f'.//{local_name}')


# Direction mapping from style codes
DIRECTION_MAP = {
    'cn': 0, 'cne': 45, 'ce': 90, 'cse': 135,
    'cs': 180, 'csw': 225, 'cw': 270, 'cnw': 315,
    'c': None, 'g': None, 'r': None
}


def parse_description(desc):
    """Extract speed, altitude, accuracy from description HTML."""
    result = {'speed_mph': None, 'speed_kmh': None, 'altitude_ft': None, 'accuracy_m': None}

    if not desc:
        return result

    # Speed: "Speed: 28 mph, 45 km/h"
    speed_match = re.search(r'Speed:\s*([\d.]+)\s*mph,\s*([\d.]+)\s*km/h', desc)
    if speed_match:
        result['speed_mph'] = float(speed_match.group(1))
        result['speed_kmh'] = float(speed_match.group(2))

    # Altitude: "Altitude: 328 ft, 100 meters"
    alt_match = re.search(r'Altitude:\s*([\d.-]+)\s*ft,\s*([\d.-]+)\s*meters', desc)
    if alt_match:
        result['altitude_ft'] = float(alt_match.group(1))

    # Accuracy: "Accuracy: 65 meters"
    acc_match = re.search(r'Accuracy:\s*([\d.]+)\s*meters', desc)
    if acc_match:
        result['accuracy_m'] = float(acc_match.group(1))

    return result


def parse_direction(style_url):
    """Convert style URL to direction in degrees."""
    if not style_url:
        return None
    style = style_url.lstrip('#')
    return DIRECTION_MAP.get(style)


def parse_kml_file(filepath):
    """Parse a KML file and extract GPS points."""
    points = []

    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
    except ET.ParseError as e:
        print(f"  XML parse error: {e}")
        return points

    # Handle both namespaced and non-namespaced KML
    placemarks = root.findall('.//kml:Placemark', NS)
    if not placemarks:
        placemarks = root.findall('.//{http://earth.google.com/kml/2.2}Placemark')
    if not placemarks:
        # Try without namespace
        placemarks = root.findall('.//Placemark')

    for pm in placemarks:
        try:
            # Get timestamp
            when_elem = find_element(pm, 'when')
            if when_elem is None or not when_elem.text:
                continue

            ts = when_elem.text.strip()

            # Skip malformed timezone offsets (e.g., -02:-30)
            if re.search(r'[+-]\d{2}:-\d{2}$', ts):
                continue

            # Get coordinates
            coords_elem = find_element(pm, 'coordinates')
            if coords_elem is None or not coords_elem.text:
                continue

            coords = coords_elem.text.strip().split(',')
            if len(coords) < 2:
                continue

            lon = float(coords[0])
            lat = float(coords[1])
            altitude_m = float(coords[2]) if len(coords) > 2 else None

            # Get description for additional fields
            desc_elem = find_element(pm, 'description')
            desc = desc_elem.text if desc_elem is not None else None
            parsed_desc = parse_description(desc)

            # Get direction from style
            style_elem = find_element(pm, 'styleUrl')
            style_url = style_elem.text if style_elem is not None else None
            direction = parse_direction(style_url)

            point = {
                'device_id': config.DEVICE_ID,
                'device_name': 'FollowMee',
                'ts': ts,
                'lat': lat,
                'lon': lon,
                'altitude_m': altitude_m,
                'altitude_ft': parsed_desc['altitude_ft'],
                'speed_mph': parsed_desc['speed_mph'],
                'speed_kmh': parsed_desc['speed_kmh'],
                'direction': direction,
                'accuracy_m': parsed_desc['accuracy_m'],
                'battery_pct': None,
                'source_type': 'kml'
            }
            points.append(point)

        except (ValueError, AttributeError) as e:
            continue  # Skip malformed placemarks

    return points


def load_all_kml_files():
    """Load all KML files from the configured directory."""
    kml_dir = Path(config.KML_DIR)

    if not kml_dir.exists():
        print(f"KML directory not found: {kml_dir}")
        return

    # Ensure unique constraint exists
    db.ensure_unique_constraint()

    # Find all KML files
    kml_files = sorted(kml_dir.glob('*.kml')) + sorted(kml_dir.glob('*FollowMee'))  # Some lack .kml extension
    print(f"Found {len(kml_files)} KML files")

    total_inserted = 0
    total_skipped = 0

    for i, kml_file in enumerate(kml_files, 1):
        print(f"[{i}/{len(kml_files)}] Processing {kml_file.name}...", end=' ')

        points = parse_kml_file(kml_file)
        if points:
            inserted, skipped = db.insert_points(points)
            total_inserted += inserted
            total_skipped += skipped
            print(f"{len(points)} points, {inserted} inserted, {skipped} duplicates")
        else:
            print("no points found")

    print(f"\nComplete: {total_inserted} inserted, {total_skipped} duplicates skipped")


if __name__ == '__main__':
    load_all_kml_files()
