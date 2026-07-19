from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.tenants.schemas import TenantContext


Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def tenant_local_datetime(tenant: TenantContext, clock: Clock = utc_now) -> datetime:
    now = clock()
    if now.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return now.astimezone(ZoneInfo(tenant.timezone))


def stay_nights(check_in: date, check_out: date) -> tuple[date, ...]:
    if check_out <= check_in:
        raise ValueError("check_out must be later than check_in")
    return tuple(
        check_in + timedelta(days=offset)
        for offset in range((check_out - check_in).days)
    )


def reservation_cutoff_reached(tenant: TenantContext, local_now: datetime) -> bool:
    reservation = tenant.reservation
    return bool(
        reservation.request_cutoff_local_time
        and reservation.reject_at_or_after_cutoff
        and local_now.time().replace(tzinfo=None) >= reservation.request_cutoff_local_time
    )


def localized_phrase_match(
    message: str,
    phrases: dict[str, list[str]],
    preferred_locale: str | None = None,
) -> str | None:
    # ponytail: exact tenant phrases handle deterministic cases; add a classifier
    # only if measured misses justify it.
    normalized = message.casefold()
    locales = [
        *([preferred_locale] if preferred_locale in phrases else []),
        *(locale for locale in phrases if locale != preferred_locale),
    ]
    for locale in locales:
        localized_phrases = phrases[locale]
        if any(phrase.casefold() in normalized for phrase in localized_phrases):
            return locale
    return None


def localized_response(
    responses: dict[str, str],
    locale: str | None,
    default_locale: str,
) -> str:
    if locale in responses:
        return responses[locale]
    language = (locale or "").split("-", 1)[0]
    return next(
        (response for key, response in responses.items() if key.startswith(language)),
        responses.get(default_locale) or next(iter(responses.values())),
    )
