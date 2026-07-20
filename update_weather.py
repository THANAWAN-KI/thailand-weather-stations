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
        "record_timestamp": normalize_timestamp(
            properties.get("record_timestamp")
        ),
    }

    return {
