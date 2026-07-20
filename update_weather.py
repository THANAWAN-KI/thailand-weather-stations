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
    """
    แปลงค่าเป็นข้อความ
    หากไม่มีข้อมูล ให้คืนค่า None
    """
    if value in (None, "", "-", "null"):
        return None

    text = str(value).strip()

    if not text:
        return None

    return text


def safe_number(value: Any) -> float | None:
    """
    แปลงค่าเป็นตัวเลข
    หากแปลงไม่ได้ ให้คืนค่า None
    """
    if value in (None, "", "-", "null"):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_date_text(value: Any) -> str | None:
    """
    แปลงวันที่ให้เป็นข้อความเท่านั้น

    ใส่คำว่า DATE: ไว้ด้านหน้า
    เพื่อป้องกัน ArcGIS Online เดาชนิดฟิลด์เป็น Date Only
    """
    text = safe_text(value)

    if text is None:
        return None

    date_formats = (
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
    )

    for date_format in date_formats:
        try:
            parsed_date = datetime.strptime(
                text,
                date_format,
            )

            return (
                "DATE: "
                + parsed_date.strftime("%Y-%m-%d")
            )

        except ValueError:
            continue

    return f"DATE: {text}"


def normalize_timestamp_text(value: Any) -> str | None:
    """
    เก็บวันและเวลาเป็นข้อความเท่านั้น

    ใส่คำว่า DATETIME: ไว้ด้านหน้า
    เพื่อป้องกัน ArcGIS Online เดาชนิดฟิลด์เป็น Date
    หรือ Timestamp Offset
    """
    text = safe_text(value)

    if text is None:
        return None

    try:
        parsed_timestamp = datetime.fromisoformat(
            text.replace("Z", "+00:00")
        )

        formatted_timestamp = (
            parsed_timestamp.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        return (
            "DATETIME: "
            + formatted_timestamp
        )

    except ValueError:
        return f"DATETIME: {text}"


def download_source(
    source_url: str,
) -> dict[str, Any]:
    """
    ดาวน์โหลดข้อมูล GeoJSON จาก URL ต้นทาง
    """
    print(
        f"Downloading weather data: {source_url}"
    )

    response = requests.get(
        source_url,
        headers={
            "Accept": "application/json",
            "User-Agent": (
                "Thailand-Weather-ArcGIS/1.0"
            ),
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
            "ข้อมูลต้นทางไม่ใช่ GeoJSON "
            "FeatureCollection"
        )

    features = data.get("features")

    if not isinstance(features, list):
        raise RuntimeError(
            "ไม่พบรายการ features "
            "ในข้อมูลต้นทาง"
        )

    if not features:
        raise RuntimeError(
            "ข้อมูลต้นทางไม่มีข้อมูลสถานี"
        )

    print(
        f"Downloaded features: {len(features)}"
    )

    return data


def clean_feature(
    feature: dict[str, Any],
) -> dict[str, Any] | None:
    """
    ตรวจสอบและทำความสะอาดแต่ละสถานี
    """
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

    if station_name is None:
        return None

    wind_speed = safe_number(
        properties.get("wind_speed")
    )

    wind_direction = safe_number(
        properties.get("wind_direction_deg")
    )

    if (
        wind_direction is not None
        and not 0 <= wind_direction <= 360
    ):
        print(
            "Invalid wind direction at "
            f"{station_name}: "
            f"{wind_direction}. "
            "Converted to null."
        )

        wind_direction = None

    if (
        wind_speed is not None
        and wind_speed < 0
    ):
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
            properties.get(
                "wind_direction_label"
            )
        ),
        "observation_date_text": (
            normalize_date_text(
                properties.get("date")
            )
        ),
        "record_timestamp_text": (
            normalize_timestamp_text(
                properties.get(
                    "record_timestamp"
                )
            )
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
    """
    ฟังก์ชันหลักสำหรับสร้าง weather.geojson
    """
    source_url = os.environ.get(
        "WEATHER_SOURCE_URL"
    )

    if not source_url:
        raise RuntimeError(
            "Missing WEATHER_SOURCE_URL. "
            "กรุณาเพิ่ม URL ต้นทาง "
            "ใน GitHub Secret"
        )

    source_data = download_source(
        source_url
    )

    cleaned_features = []

    for feature in source_data["features"]:
        cleaned_feature = clean_feature(
            feature
        )

        if cleaned_feature is not None:
            cleaned_features.append(
                cleaned_feature
            )

    if not cleaned_features:
        raise RuntimeError(
            "ไม่เหลือข้อมูลสถานี "
            "หลังจากตรวจสอบข้อมูล"
        )

    output_data = {
        "type": "FeatureCollection",
        "name": (
            "Thailand_Weather_Stations"
        ),
        "features": cleaned_features,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            output_data,
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
            "WEATHER UPDATE FAILED: "
            f"{error}",
            file=sys.stderr,
        )

        sys.exit(1)
