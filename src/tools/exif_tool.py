"""
EXIF Reader tool — extract metadata from photos/videos.

Reads GPS coordinates, camera info, date/time, and more from EXIF data.
Uses Pillow for EXIF extraction and geopy (Nominatim) for reverse geocoding.

GPS accuracy depends on the device:
- Smartphones: 3-10 meters (GPS + GLONASS + cell towers)
- DSLR with GPS: 5-15 meters
- Photos without GPS: no location data

Requirements: Pillow (already installed), geopy
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

# Nominatim requires a User-Agent
_USER_AGENT = "ProgressiveAgent/1.0"


def _dms_to_decimal(dms: tuple, ref: str) -> float:
    """Convert EXIF GPS DMS (degrees, minutes, seconds) to decimal degrees.

    EXIF stores GPS as ((deg_num, deg_den), (min_num, min_den), (sec_num, sec_den)).
    Pillow returns IFDRational objects that can be float()-ed directly.
    """
    try:
        degrees = float(dms[0])
        minutes = float(dms[1])
        seconds = float(dms[2])
    except (TypeError, ValueError, IndexError):
        return 0.0

    decimal = degrees + minutes / 60 + seconds / 3600
    if ref in ("S", "W"):
        decimal = -decimal
    return decimal


def _extract_exif(image_path: Path) -> dict[str, Any]:
    """Extract EXIF metadata from an image file.

    Returns a dict with:
    - camera_make, camera_model — camera manufacturer and model
    - date_taken — original capture date/time
    - gps_lat, gps_lon — decimal GPS coordinates (if available)
    - gps_altitude — altitude in meters (if available)
    - focal_length, aperture, iso, exposure_time — shooting parameters
    - image_width, image_height — pixel dimensions
    - software — editing software used
    - orientation — EXIF orientation tag
    """
    from PIL import Image
    from PIL.ExifTags import GPSTAGS, TAGS

    result: dict[str, Any] = {}

    try:
        img = Image.open(image_path)
    except Exception as e:
        return {"error": f"Cannot open image: {e}"}

    result["image_width"] = img.width
    result["image_height"] = img.height
    result["format"] = img.format or image_path.suffix.upper().lstrip(".")

    exif_data = img.getexif()
    if not exif_data:
        result["has_exif"] = False
        return result

    result["has_exif"] = True

    # Map tag IDs to names
    tag_map: dict[str, Any] = {}
    for tag_id, value in exif_data.items():
        tag_name = TAGS.get(tag_id, str(tag_id))
        tag_map[tag_name] = value

    # Camera info
    if "Make" in tag_map:
        result["camera_make"] = str(tag_map["Make"]).strip()
    if "Model" in tag_map:
        result["camera_model"] = str(tag_map["Model"]).strip()
    if "Software" in tag_map:
        result["software"] = str(tag_map["Software"]).strip()

    # Date/time
    for date_tag in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
        if date_tag in tag_map:
            raw_date = str(tag_map[date_tag])
            try:
                dt = datetime.strptime(raw_date, "%Y:%m:%d %H:%M:%S")
                result["date_taken"] = dt.isoformat()
            except ValueError:
                result["date_taken"] = raw_date
            break

    # Shooting parameters
    if "FocalLength" in tag_map:
        fl = tag_map["FocalLength"]
        result["focal_length_mm"] = round(float(fl), 1)
    if "FNumber" in tag_map:
        fn = tag_map["FNumber"]
        result["aperture"] = f"f/{float(fn):.1f}"
    if "ISOSpeedRatings" in tag_map:
        result["iso"] = tag_map["ISOSpeedRatings"]
    if "ExposureTime" in tag_map:
        et = tag_map["ExposureTime"]
        et_float = float(et)
        if et_float < 1:
            result["exposure_time"] = f"1/{int(1/et_float)}"
        else:
            result["exposure_time"] = f"{et_float:.1f}s"

    # GPS data (IFD 0x8825)
    gps_ifd = exif_data.get_ifd(0x8825)
    if gps_ifd:
        gps_data: dict[str, Any] = {}
        for tag_id, value in gps_ifd.items():
            tag_name = GPSTAGS.get(tag_id, str(tag_id))
            gps_data[tag_name] = value

        # Latitude
        if "GPSLatitude" in gps_data and "GPSLatitudeRef" in gps_data:
            lat = _dms_to_decimal(gps_data["GPSLatitude"], gps_data["GPSLatitudeRef"])
            result["gps_lat"] = round(lat, 6)

        # Longitude
        if "GPSLongitude" in gps_data and "GPSLongitudeRef" in gps_data:
            lon = _dms_to_decimal(gps_data["GPSLongitude"], gps_data["GPSLongitudeRef"])
            result["gps_lon"] = round(lon, 6)

        # Altitude
        if "GPSAltitude" in gps_data:
            alt = float(gps_data["GPSAltitude"])
            alt_ref = gps_data.get("GPSAltitudeRef", 0)
            if alt_ref == 1:  # Below sea level
                alt = -alt
            result["gps_altitude_m"] = round(alt, 1)

    return result


async def _reverse_geocode(lat: float, lon: float) -> dict[str, str]:
    """Convert GPS coordinates to human-readable address using Nominatim.

    Free, no API key. Rate limit: 1 req/sec (we do 1 per photo, fine).
    Returns: {address, city, country, display_name}
    """
    from geopy.geocoders import Nominatim

    def _geocode():
        geolocator = Nominatim(user_agent=_USER_AGENT, timeout=10)
        location = geolocator.reverse(f"{lat}, {lon}", language="ru", exactly_one=True)
        if not location:
            return {"address": f"{lat}, {lon}"}

        raw = location.raw.get("address", {})
        result = {
            "display_name": location.address,
            "city": (
                raw.get("city")
                or raw.get("town")
                or raw.get("village")
                or raw.get("hamlet")
                or ""
            ),
            "state": raw.get("state", ""),
            "country": raw.get("country", ""),
        }
        # Short address
        parts = [p for p in [result["city"], result["state"], result["country"]] if p]
        result["address_short"] = ", ".join(parts) if parts else location.address
        return result

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _geocode)


class ExifReaderTool:
    """Extract EXIF metadata from photos — GPS, camera, date, shooting params."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="exif",
            description=(
                "Extract metadata from a photo: GPS location (where it was taken), "
                "camera model, date/time, shooting parameters (ISO, aperture, shutter speed). "
                "If GPS data exists, automatically resolves coordinates to a human-readable address. "
                "If NO GPS in EXIF — you MUST analyze the image visually: look at architecture, "
                "signs, license plates, language, landmarks, vegetation to guess the location. "
                "Use when user asks: 'где снято?', 'какой камерой?', 'когда сделано фото?', "
                "'exif', 'метаданные фото', 'геолокация фотки'."
            ),
            parameters=[
                ToolParameter(
                    name="image_path",
                    type="string",
                    description="Path to the image file (JPG, PNG, TIFF, etc.)",
                    required=True,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        image_path_str = kwargs.get("image_path", "")
        if not image_path_str:
            return ToolResult(success=False, error="image_path is required")

        image_path = Path(image_path_str)
        if not image_path.exists():
            return ToolResult(success=False, error=f"File not found: {image_path}")

        try:
            loop = asyncio.get_event_loop()
            exif = await loop.run_in_executor(None, _extract_exif, image_path)
        except Exception as e:
            logger.exception("EXIF extraction failed for %s", image_path)
            return ToolResult(success=False, error=f"EXIF extraction failed: {e}")

        if "error" in exif:
            return ToolResult(success=False, error=exif["error"])

        # Reverse geocode if GPS data available
        geo_info: dict[str, str] = {}
        if "gps_lat" in exif and "gps_lon" in exif:
            try:
                geo_info = await _reverse_geocode(exif["gps_lat"], exif["gps_lon"])
                exif["location"] = geo_info.get("address_short", "")
                exif["location_full"] = geo_info.get("display_name", "")
            except Exception as e:
                logger.warning("Reverse geocoding failed: %s", e)
                exif["location"] = f"{exif['gps_lat']}, {exif['gps_lon']}"

        # Build human-readable answer
        lines: list[str] = []

        # Location (most interesting info first)
        if "location" in exif:
            lines.append(f"Location: {exif['location']}")
            if "gps_lat" in exif:
                maps_url = f"https://maps.google.com/?q={exif['gps_lat']},{exif['gps_lon']}"
                lines.append(f"GPS: {exif['gps_lat']}, {exif['gps_lon']}")
                lines.append(f"Map: {maps_url}")
            if "gps_altitude_m" in exif:
                lines.append(f"Altitude: {exif['gps_altitude_m']} m")

        # Date
        if "date_taken" in exif:
            lines.append(f"Date: {exif['date_taken']}")

        # Camera
        camera_parts = []
        if "camera_make" in exif:
            camera_parts.append(exif["camera_make"])
        if "camera_model" in exif:
            camera_parts.append(exif["camera_model"])
        if camera_parts:
            lines.append(f"Camera: {' '.join(camera_parts)}")

        # Shooting params
        params = []
        if "focal_length_mm" in exif:
            params.append(f"{exif['focal_length_mm']}mm")
        if "aperture" in exif:
            params.append(exif["aperture"])
        if "exposure_time" in exif:
            params.append(exif["exposure_time"])
        if "iso" in exif:
            params.append(f"ISO {exif['iso']}")
        if params:
            lines.append(f"Settings: {' | '.join(params)}")

        # Image info
        if "image_width" in exif:
            lines.append(f"Size: {exif['image_width']}x{exif['image_height']}")
        if "software" in exif:
            lines.append(f"Software: {exif['software']}")

        if not exif.get("has_exif", True):
            lines.append("No EXIF data found in this image.")

        # If no GPS — hint the LLM to do visual analysis
        if "gps_lat" not in exif:
            lines.append("")
            lines.append(
                "NO GPS in EXIF. IMPORTANT: Analyze the image VISUALLY to determine location. "
                "Look for: architecture style, street signs, license plates, language on signs, "
                "vegetation, road markings, landmarks, shop names, terrain features. "
                "Provide your best guess with reasoning."
            )
            exif["needs_visual_analysis"] = True

        exif["answer"] = "\n".join(lines) if lines else "No metadata found."

        logger.info(
            "EXIF extracted from %s: GPS=%s, camera=%s",
            image_path.name,
            "yes" if "gps_lat" in exif else "no",
            exif.get("camera_model", "unknown"),
        )

        return ToolResult(success=True, data=exif)
