import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


PORTAL_URL = "https://ieat.maps.arcgis.com"
GEOJSON_FILE = Path("weather.geojson")
TIMEOUT = 90


def check_result(
    result: dict[str, Any],
) -> dict[str, Any]:
    if "error" not in result:
        return result

    error = result["error"]
    code = error.get("code", "unknown")
    message = error.get(
        "message",
        "Unknown ArcGIS error",
    )
    details = "; ".join(
        error.get("details", [])
    )

    raise RuntimeError(
        f"ArcGIS error {code}: "
        f"{message}. {details}"
    )


def get_json(
    url: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    response = requests.get(
        url,
        params=params,
        timeout=TIMEOUT,
    )
    response.raise_for_status()

    return check_result(response.json())


def post_json(
    url: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    response = requests.post(
        url,
        data=data,
        timeout=TIMEOUT,
    )
    response.raise_for_status()

    return check_result(response.json())


def generate_token(
    username: str,
    password: str,
) -> str:
    result = post_json(
        f"{PORTAL_URL}/sharing/rest/generateToken",
        {
            "f": "json",
            "username": username,
            "password": password,
            "client": "referer",
            "referer": PORTAL_URL,
            "expiration": 60,
        },
    )

    token = result.get("token")

    if not token:
        raise RuntimeError(
            "ArcGIS Online ไม่ส่ง Token กลับมา"
        )

    print("ArcGIS authentication successful.")
    return token


def get_layer_url(
    item_id: str,
    token: str,
) -> str:
    item = get_json(
        (
            f"{PORTAL_URL}/sharing/rest/"
            f"content/items/{item_id}"
        ),
        {
            "f": "json",
            "token": token,
        },
    )

    print(f"Item title: {item.get('title')}")
    print(f"Item type: {item.get('type')}")

    if item.get("type") != "Feature Service":
        raise RuntimeError(
            "ARCGIS_ITEM_ID ไม่ใช่ "
            "Feature layer (hosted)"
        )

    service_url = str(
        item.get("url", "")
    ).rstrip("/")

    if not service_url:
        raise RuntimeError(
            "ไม่พบ Feature Service URL"
        )

    service_info = get_json(
        service_url,
        {
            "f": "json",
            "token": token,
        },
    )

    layers = service_info.get("layers") or []

    if not layers:
        raise RuntimeError(
            "Feature Service ไม่มี Layer"
        )

    layer_id = layers[0]["id"]
    layer_name = layers[0].get("name")

    print(f"Layer name: {layer_name}")

    return f"{service_url}/{layer_id}"


def parse_arcgis_date(value: Any) -> int | None:
    if value in (None, "", "-"):
        return None

    text = str(value)

    formats = (
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
    )

    for date_format in formats:
        try:
            parsed = datetime.strptime(
                text,
                date_format,
            )
            return int(
                parsed.timestamp() * 1000
            )
        except ValueError:
            continue

    return None


def convert_value(
    value: Any,
    field: dict[str, Any],
) -> Any:
    if value is None:
        return None

    field_type = field.get("type")

    if field_type == "esriFieldTypeString":
        text = str(value)
        length = field.get("length")

        if length:
            text = text[: int(length)]

        return text

    if field_type in (
        "esriFieldTypeDouble",
        "esriFieldTypeSingle",
    ):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    if field_type in (
        "esriFieldTypeInteger",
        "esriFieldTypeSmallInteger",
    ):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    if field_type == "esriFieldTypeDate":
        return parse_arcgis_date(value)

    return value


def load_geojson() -> dict[str, Any]:
    if not GEOJSON_FILE.exists():
        raise RuntimeError(
            f"ไม่พบไฟล์ {GEOJSON_FILE}"
        )

    data = json.loads(
        GEOJSON_FILE.read_text(
            encoding="utf-8"
        )
    )

    if data.get("type") != "FeatureCollection":
        raise RuntimeError(
            "weather.geojson ไม่ใช่ FeatureCollection"
        )

    features = data.get("features")

    if not isinstance(features, list) or not features:
        raise RuntimeError(
            "weather.geojson ไม่มีสถานี"
        )

    print(f"GeoJSON features: {len(features)}")
    return data


def build_arcgis_features(
    geojson: dict[str, Any],
    layer_info: dict[str, Any],
) -> list[dict[str, Any]]:
    object_id_field = layer_info.get(
        "objectIdField"
    )

    fields = {}

    for field in layer_info.get("fields", []):
        name = field.get("name")
        field_type = field.get("type")

        if not name:
            continue

        if name == object_id_field:
            continue

        if field_type in (
            "esriFieldTypeOID",
            "esriFieldTypeGlobalID",
            "esriFieldTypeGeometry",
        ):
            continue

        if field.get("editable") is False:
            continue

        fields[name.lower()] = field

    output = []

    for feature in geojson["features"]:
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}
        coordinates = geometry.get("coordinates")

        if (
            geometry.get("type") != "Point"
            or not isinstance(coordinates, list)
            or len(coordinates) < 2
        ):
            continue

        try:
            longitude = float(coordinates[0])
            latitude = float(coordinates[1])
        except (TypeError, ValueError):
            continue

        source_fields = {
            str(key).lower(): value
            for key, value in properties.items()
        }

        attributes = {}

        for lower_name, field in fields.items():
            if lower_name not in source_fields:
                continue

            attributes[field["name"]] = convert_value(
                source_fields[lower_name],
                field,
            )

        output.append(
            {
                "geometry": {
                    "x": longitude,
                    "y": latitude,
                    "spatialReference": {
                        "wkid": 4326
                    },
                },
                "attributes": attributes,
            }
        )

    if not output:
        raise RuntimeError(
            "ไม่สามารถสร้าง ArcGIS Features ได้"
        )

    print(f"Prepared features: {len(output)}")
    return output


def get_existing_ids(
    layer_url: str,
    token: str,
) -> list[int]:
    result = post_json(
        f"{layer_url}/query",
        {
            "f": "json",
            "token": token,
            "where": "1=1",
            "returnIdsOnly": "true",
        },
    )

    ids = result.get("objectIds") or []

    print(f"Existing features: {len(ids)}")
    return ids


def apply_edits(
    layer_url: str,
    token: str,
    features: list[dict[str, Any]],
    old_ids: list[int],
) -> None:
    payload: dict[str, Any] = {
        "f": "json",
        "token": token,
        "adds": json.dumps(
            features,
            ensure_ascii=False,
        ),
        "rollbackOnFailure": "true",
    }

    if old_ids:
        payload["deletes"] = ",".join(
            str(object_id)
            for object_id in old_ids
        )

    result = post_json(
        f"{layer_url}/applyEdits",
        payload,
    )

    add_results = result.get("addResults") or []
    delete_results = (
        result.get("deleteResults") or []
    )

    failed_adds = [
        item
        for item in add_results
        if not item.get("success")
    ]

    failed_deletes = [
        item
        for item in delete_results
        if not item.get("success")
    ]

    if failed_adds or failed_deletes:
        raise RuntimeError(
            "applyEdits failed: "
            f"adds={failed_adds}; "
            f"deletes={failed_deletes}"
        )

    print(f"Added features: {len(add_results)}")
    print(
        f"Deleted old features: "
        f"{len(delete_results)}"
    )


def verify_count(
    layer_url: str,
    token: str,
    expected: int,
) -> None:
    result = post_json(
        f"{layer_url}/query",
        {
            "f": "json",
            "token": token,
            "where": "1=1",
            "returnCountOnly": "true",
        },
    )

    actual = result.get("count")

    print(
        f"ArcGIS feature count after sync: "
        f"{actual}"
    )

    if actual != expected:
        raise RuntimeError(
            f"Expected {expected} features, "
            f"but ArcGIS contains {actual}"
        )


def main() -> None:
    username = os.environ.get(
        "ARCGIS_USERNAME"
    )
    password = os.environ.get(
        "ARCGIS_PASSWORD"
    )
    item_id = os.environ.get(
        "ARCGIS_ITEM_ID"
    )

    missing = [
        name
        for name, value in (
            ("ARCGIS_USERNAME", username),
            ("ARCGIS_PASSWORD", password),
            ("ARCGIS_ITEM_ID", item_id),
        )
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Missing GitHub Secrets: "
            + ", ".join(missing)
        )

    token = generate_token(
        username,
        password,
    )

    layer_url = get_layer_url(
        item_id,
        token,
    )

    layer_info = get_json(
        layer_url,
        {
            "f": "json",
            "token": token,
        },
    )

    geojson = load_geojson()

    features = build_arcgis_features(
        geojson,
        layer_info,
    )

    old_ids = get_existing_ids(
        layer_url,
        token,
    )

    apply_edits(
        layer_url,
        token,
        features,
        old_ids,
    )

    verify_count(
        layer_url,
        token,
        len(features),
    )

    print(
        "Thailand weather synchronization completed."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"SYNC FAILED: {error}",
            file=sys.stderr,
        )
        sys.exit(1)
