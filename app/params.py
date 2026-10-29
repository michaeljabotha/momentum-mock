"""Shared query-parameter validation: date ranges, paging, key scoping."""
from datetime import date

from .config import (DEFAULT_PER_PAGE, MAX_PER_PAGE, MAX_RANGE_DAYS,
                     SCOPED_ORG_UNIT_IDS, SCOPED_STORE_IDS)
from .envelope import ApiException, validation_error


def parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise validation_error(
            f"{field} must be an ISO-8601 date (YYYY-MM-DD).", field, "invalid_format")


def validate_range(date_from: str, date_to: str) -> tuple[date, date]:
    start = parse_date(date_from, "dateFrom")
    end = parse_date(date_to, "dateTo")
    if end < start:
        raise validation_error("dateTo must be after dateFrom.", "dateTo", "must_be_after")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise validation_error(
            f"Date range may not exceed {MAX_RANGE_DAYS} days.", "dateTo", "range_too_large")
    return start, end


def validate_paging(page: int, per_page: int) -> tuple[int, int]:
    if page < 1:
        raise validation_error("page must be 1 or greater.", "page", "out_of_range")
    if per_page < 1 or per_page > MAX_PER_PAGE:
        raise validation_error(
            f"per_page must be between 1 and {MAX_PER_PAGE}.", "per_page", "out_of_range")
    return page, per_page


def check_enum(value: str | None, field: str, allowed: list[str]) -> None:
    if value is not None and value not in allowed:
        raise validation_error(
            f"{field} must be one of: {', '.join(allowed)}.", field, "invalid_value")


def check_org_unit_scope(org_unit_id: int | None) -> None:
    if org_unit_id is not None and org_unit_id not in SCOPED_ORG_UNIT_IDS:
        raise ApiException(403, "FORBIDDEN", "API key is not scoped to this site.")


def check_store_scope(store_id: int | None) -> None:
    if store_id is not None and store_id not in SCOPED_STORE_IDS:
        raise ApiException(403, "FORBIDDEN", "API key is not scoped to this store.")


def pagination_block(page: int, per_page: int, total_items: int) -> dict[str, int]:
    total_pages = (total_items + per_page - 1) // per_page
    return {
        "page": page,
        "per_page": per_page,
        "total_items": total_items,
        "total_pages": total_pages,
    }


DEFAULTS = {"page": 1, "per_page": DEFAULT_PER_PAGE}
