def get_resource_ui(_resource_key: str) -> dict:
    return {}


def get_field_ui(_resource_key: str) -> dict:
    return {}


def get_table_columns(_resource_key: str, field_keys: list[str]) -> list[dict]:
    return [
        {
            "key": field_key,
            "label": field_key.replace('_', ' ').title(),
        }
        for field_key in field_keys
    ]


def apply_field_ui(_resource_key: str, _fields: dict) -> None:
    return None


def get_navigation_resources() -> list[dict]:
    return []
