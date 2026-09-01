import os

from services.visitas_service import normalize_phone


REPORTS_MANAGER_PHONES_ENV = "REPORTS_MANAGER_PHONES"


def reports_manager_phones(raw_value: str | None = None) -> set[str]:
    raw = os.getenv(REPORTS_MANAGER_PHONES_ENV, "") if raw_value is None else raw_value
    phones = {
        normalize_phone(item)
        for item in str(raw or "").replace(";", ",").split(",")
    }
    return {phone for phone in phones if phone}


def is_reports_manager(phone: str, raw_value: str | None = None) -> bool:
    normalized = normalize_phone(phone)
    return bool(normalized and normalized in reports_manager_phones(raw_value))
