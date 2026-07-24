from app.agent.schemas.context import AgentContext
from app.tenants.policies import Clock, tenant_local_datetime, utc_now
from app.tenants.schemas import TenantContext


def build_agent_context(
    tenant: TenantContext,
    conversation_id: str,
    *,
    metadata: dict | None = None,
    clock: Clock = utc_now,
) -> AgentContext:
    now = tenant_local_datetime(tenant, clock)
    context: AgentContext = {
        "tenant_id": tenant.tenant_id,
        "conversation_id": conversation_id,
        "agent_profile": tenant.agent.profile,
        "now": now.isoformat(),
        "datetime": now.isoformat(),
        "current_local_datetime": now.isoformat(),
        "current_local_date": now.date().isoformat(),
        "current_local_time": now.time().isoformat(timespec="seconds"),
        "locale": tenant.locale or tenant.default_language,
        "date": now.date().isoformat(),
        "time": now.time().isoformat(timespec="seconds"),
        "timezone": tenant.timezone,
        "agent_style_rules": tenant.agent.style_rules,
        "tenant_instructions": "\n\n".join(
            part
            for part in (
                tenant.prompt.tenant_instructions,
                tenant.prompt.instructions,
                "When all required tool arguments are known, call the appropriate tool immediately. "
                "Do not announce the tool action yourself. Any required user-facing announcement "
                "is handled by the tool. Do not claim that an action is being performed unless you "
                "call the corresponding tool.",
            )
            if part
        ),
        "tenant_identity": {
            "tenant_id": tenant.tenant_id,
            "display_name": tenant.name,
            "business_type": tenant.business_type,
            "assistant_name": tenant.agent.display_name,
            "assistant_role": tenant.agent.role,
            "default_locale": tenant.default_locale,
            "supported_locales": tenant.supported_locales,
            "default_greeting": tenant.agent.greeting_phrase,
            "localized_greetings": tenant.agent.localized_greetings,
        },
        "business_info": tenant.business_info.model_dump(mode="json", exclude_none=True),
        "reservation_policy": _reservation_policy(tenant),
        "required_reservation_fields": [
            f"{name}: {config.label}"
            for name, config in tenant.reservation.required_fields.items()
            if config.required
        ],
        "schedule_summary": _schedule_summary(tenant),
        "supported_operations": _supported_operations(tenant),
        "conversation_scope": _conversation_scope(tenant),
        "knowledge_base": tenant.prompt.knowledge_base,
        "supplementary_guidance": tenant.prompt.supplementary_guidance,
    }
    for key in ("call_session_id", "channel", "language", "thread_id", "idempotency_key"):
        if (metadata or {}).get(key):
            context[key] = metadata[key]
    return context


def _conversation_scope(tenant: TenantContext) -> str:
    scope = tenant.conversation_scope
    if scope.mode != "property_only":
        return ""
    refusals = "\n".join(
        f"- {locale}: {response}" for locale, response in scope.localized_refusals.items()
    )
    return (
        f"Only answer questions related to {tenant.name}, its accommodation, services, "
        "relevant nearby places covered by the knowledge base, and current guest or property "
        "emergencies. Refuse unrelated requests without answering them.\n"
        f"Use the matching fixed refusal:\n{refusals}"
    )


def _supported_operations(tenant: TenantContext) -> str:
    labels = {
        "factual_qa": "Factual property questions",
        "room_recommendation": "Room recommendations",
        "availability_check": "Room availability checks",
        "reservation_create": "New reservation submission",
        "reservation_modify": "Reservation modification",
        "reservation_cancel": "Reservation cancellation",
        "reservation_lookup": "Reservation lookup",
        "human_transfer": "Human call transfer",
    }
    return "\n".join(
        f"- {labels[name]}: {'supported' if enabled else 'not supported'}"
        for name, enabled in tenant.features.model_dump().items()
    )


def _reservation_policy(tenant: TenantContext) -> str:
    reservation = tenant.reservation
    parts = [
        "New reservation submission is currently supported."
        if reservation.enabled
        else "New reservation submission is currently not supported."
    ]
    if reservation.request_cutoff_local_time:
        cutoff = reservation.request_cutoff_local_time.isoformat(timespec="minutes")
        parts.append(
            f"Do not accept or submit a new reservation request at or after {cutoff} in the "
            "tenant's local timezone. Availability and factual questions remain allowed."
        )
    if reservation.enabled and (
        reservation.mode == "request_only" or not reservation.can_confirm_reservation
    ):
        parts.append(
            "Reservation handling is request-only. Describe reservations as submitted requests "
            "waiting for staff confirmation. Do not describe them as confirmed reservations."
        )
    if reservation.flow.availability_before_guest_details:
        parts.append(
            "For a new accommodation reservation, first collect only check-in, check-out, "
            "requested room type, and room count. As soon as they are known, immediately call "
            "the availability tool in the same response. Do not ask for guest or contact "
            "details before a successful availability result."
        )
    if reservation.flow.ask_to_continue_after_availability:
        parts.append(
            "After availability succeeds, first tell the guest a room is available and ask "
            "whether they want to continue. Collect reservation details only after they agree."
        )
    if reservation.flow.require_final_confirmation:
        parts.append(
            "Summarize the final reservation details and require explicit guest confirmation "
            "before submitting the reservation request."
        )
    if reservation.contact.email_required is False:
        parts.append("Do not ask for an email address during the reservation flow.")
    if reservation.contact.prefer_inbound_phone_with_consent:
        consent_prompt = (
            f' Ask exactly: "{reservation.contact.inbound_phone_consent_prompt}".'
            if reservation.contact.inbound_phone_consent_prompt
            else ""
        )
        parts.append(
            "When trusted inbound caller metadata is available, ask permission to use that "
            "number after the guest agrees to continue."
            f"{consent_prompt} Use it only with consent; otherwise ask for another phone number."
        )
    return "\n".join(parts)


def _schedule_summary(tenant: TenantContext) -> str:
    summaries = []
    for day in (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ):
        config = tenant.reservation.schedule.weekly.get(day)
        if not config:
            continue
        if not config.open:
            summaries.append(f"{day}: closed")
            continue
        intervals = ", ".join(f"{item.start}-{item.end}" for item in config.intervals)
        summaries.append(f"{day}: {intervals or 'open'}")
    return "\n".join(summaries)
