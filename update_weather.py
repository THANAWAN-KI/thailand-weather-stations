import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


OUTPUT_FILE = Path("weather.geojson")
TIMEOUT = 90


def safe_text(value: Any) -> str | None:
    """คืนข้อความ หรือ None เมื่อไม่มีข้อมูล."""
    if value in (None, "", "-", "null"):
        return None

    text = str(value).strip()
    return text or None


def safe_number(value: Any) -> float | None:
    """คืนตัวเลข หรือ None เมื่อค่าใช้ไม่ได้."""
    if value in (None, "", "-", "null"):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_date(value: Any) -> str | None:
    """
    แปลงวันที่เป็นรูปแบบ YYYY-MM-DD
    รองรับตัวอย่าง 07/16/2026
    """
    text = safe_text(value)

    if text is None:
        return None

    formats = (
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
    )

    for date_format in formats:
        try:
            parsed = datetime.strptime(text, date_format)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return text


def normalize_timestamp(value: Any) -> str | None:
    """
    ตรวจสอบ ISO timestamp เช่น
    2026-07-16T03:55:21.988715
    """
    text = safe_text(value)

    if text is None:
        return None

    try:
        parsed = datetime.fromisoformat(
            text.replace("Z", "+00:00")
        )
        return parsed.isoformat()
    except ValueError:
        return text


def download_source(source_url: str) -> dict[str, Any]:
    print(f"Downloading weather data: {source_url}")

    response = requests.get(
        source_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Thailand-Weather-ArcGIS/1.0",
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise RuntimeError(
            "ข้อมูลต้นทางต้องเป็น JSON object"
        )

    if data.get("type") != "FeatureCollection":
        raise RuntimeError(
            "ข้อมูลต้นทางไม่ใช่ GeoJSON FeatureCollection"
        )

    features = data.get("features")

    if not isinstance(features, list):
        raise RuntimeError(
            "ไม่พบรายการ features ในข้อมูลต้นทาง"
        )

    if not features:
        raise RuntimeError(
            "ข้อมูลต้นทางไม่มีสถานี"
        )

    print(f"Downloaded features: {len(features)}")
    return data


def clean_feature(
    feature: dict[str, Any],
) -> dict[str, Any] | None:
    geometry = feature.get("geometry") or {}
    properties = feature.get("properties") or {}

    if geometry.get("type") != "Point":
        return None

    coordinates = geometry.get("coordinates")

    if (
        not isinstance(coordinates, list)
        or len(coordinates) < 2
    ):
        return None

    try:
        longitude = float(coordinates[0])
        latitude = float(coordinates[1])
    except (TypeError, ValueError):
        return None

    # ตรวจว่าพิกัดอยู่ในช่วงที่ถูกต้อง
    if not -180 <= longitude <= 180:
        return None

    if not -90 <= latitude <= 90:
        return None

    station_name = safe_text(
        properties.get("station_name")
    )

    province = safe_text(
        properties.get("province")
    )

    if not station_name:
        return None

    wind_speed = safe_number(
        properties.get("wind_speed")
    )

    wind_direction = safe_number(
        properties.get("wind_direction_deg")
    )

    # ทิศทางลมที่ถูกต้องควรอยู่ระหว่าง 0–360 องศา
    if (
        wind_direction is not None
        and not 0 <= wind_direction <= 360
    ):
        print(
            f"Invalid wind direction at {station_name}: "
            f"{wind_direction}; converted to null."
        )
        wind_direction = None

    # ป้องกันค่าความเร็วลมติดลบ
    if wind_speed is not None and wind_speed < 0:
        wind_speed = None

    cleaned_properties = {
        "station_name": station_name,
        "province": province,
        "temp": safe_number(
            properties.get("temp")
        ),
        "rainfall": safe_number(
            properties.get("rainfall")
        ),
        "rainfall_24hr": safe_number(
            properties.get("rainfall_24hr")
        ),
        "wind_speed": wind_speed,
        "wind_direction_deg": wind_direction,
        "wind_direction_label": safe_text(
            properties.get("wind_direction_label")
        ),
       "observation_date_text": normalize_date(
        properties.get("date")
),
        ),
        "record_timestamp": normalize_timestamp(
            properties.get("record_timestamp")
        ),
    }

    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [
                longitude,
                latitude,
            ],
        },
        "properties": cleaned_properties,
    }


def main() -> None:
    source_url = os.environ.get(
        "WEATHER_SOURCE_URL"
    )

    if not source_url:
        raise RuntimeError(
            "Missing WEATHER_SOURCE_URL. "
            "กรุณาเพิ่ม URL ต้นทางใน GitHub Secret"
        )

    source = download_source(source_url)

    cleaned_features = []

    for feature in source["features"]:
        cleaned = clean_feature(feature)

        if cleaned is not None:
            cleaned_features.append(cleaned)

    if not cleaned_features:
        raise RuntimeError(
            "ไม่เหลือสถานีหลังตรวจสอบข้อมูล"
        )

    output = {
        "type": "FeatureCollection",
        "name": "Thailand_Weather_Stations",
        "features": cleaned_features,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"Created {OUTPUT_FILE} with "
        f"{len(cleaned_features)} stations."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"WEATHER UPDATE FAILED: {error}",
            file=sys.stderr,
        )
        sys.exit(1)
