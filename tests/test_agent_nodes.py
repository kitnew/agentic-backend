from app.agent.contracts.input import AgentInput
from app.agent.contracts.output import AgentResult
from app.agent.contracts.state import (
    AgentDecision,
    ChatMemoryExtraction,
    ResponseDraft,
    ResponseValidationResult,
    ReservationExtractionResult,
    TaskStateValidationResult,
)
from app.agent.runtime import AgentRuntime
from app.agent.runtime.capability_executor import CapabilityExecution
from app.agent.runtime.graph import AgentGraph
from app.agent.profiles.loader import AgentProfileLoader
from app.capabilities.schemas import CapabilityRequest, CapabilityResult, CapabilityStatus
from app.tenants.loader import TenantConfigLoader


class FakeStructuredLlm:
    def __init__(self, outputs: list, messages: list, schema):
        self.outputs = outputs
        self.messages = messages
        self.schema = schema

    def invoke(self, messages):
        self.messages.append(messages)
        if self.outputs:
            return self.outputs.pop(0)
        return self.schema()


class FakeStateLlm:
    def __init__(self, outputs: list):
        self.outputs = outputs
        self.messages = []

    def with_structured_output(self, schema, method):
        return FakeStructuredLlm(self.outputs, self.messages, schema)


class FakeCapabilityExecutor:
    def __init__(self, status=CapabilityStatus.SUCCESS):
        self.status = status
        self.requests = []

    def execute(self, capability_request: CapabilityRequest) -> CapabilityExecution:
        self.requests.append(capability_request)
        return CapabilityExecution(
            request=capability_request,
            result=CapabilityResult(
                name=capability_request.name,
                status=self.status,
                output={"row_appended": self.status == CapabilityStatus.SUCCESS},
                user_message="Vašu žiadosť o rezerváciu sme prijali. Personál ju potvrdí.",
                provider="fake",
                error="failed" if self.status == CapabilityStatus.FAILED else None,
            ),
            tool_call={"provider": "fake", "input": capability_request.input},
        )


def build_agent_input(message_text: str, chat_history: list[dict] | None = None):
    tenant_context = TenantConfigLoader().load("demo_restaurant")
    return AgentInput(
        tenant_id=tenant_context.tenant_id,
        conversation_id="conversation-1",
        message_id="message-1",
        message_text=message_text,
        channel="chat",
        tenant_context=tenant_context,
        chat_history=chat_history or [],
    )


def ok_response_validation() -> ResponseValidationResult:
    return ResponseValidationResult(
        ok=True,
        needs_revision=False,
        mentions_validation_errors=True,
        asks_for_missing_fields=True,
    )


def reservation_decision() -> AgentDecision:
    return AgentDecision(
        primary_intent="reservation_request",
        detected_intents=["reservation_request"],
        active_task="reservation_request",
    )


def test_incomplete_reservation_collects_missing_fields_without_capability():
    runtime = AgentRuntime(
        FakeStateLlm(
            [
                ChatMemoryExtraction(active_task="reservation_request", task_status="collecting_info"),
                reservation_decision(),
                ReservationExtractionResult(active_task="reservation_request", task_status="collecting_info"),
                TaskStateValidationResult(task_status="collecting_info"),
                ResponseDraft(
                    response_text=(
                        "Pre rezerváciu potrebujem meno, dátum, čas, počet osôb a telefónne číslo."
                    )
                ),
                ok_response_validation(),
            ]
        )
    )

    result = runtime.run(build_agent_input("Chcem urobit rezervaciu."))
    memory = result.trace["validate_task_state"]

    assert result.requested_capabilities == []
    assert result.capability_results == []
    assert memory["task_status"] == "collecting_info"
    assert set(memory["missing_fields"]) == {
        "guest_name",
        "date",
        "time",
        "party_size",
        "phone",
    }
    assert "telefónne číslo" in result.response_text


def test_question_only_does_not_offer_unsolicited_reservation_collection():
    runtime = AgentRuntime(
        FakeStateLlm(
            [
                ChatMemoryExtraction(current_question_intents=["opening_hours", "parking_question"]),
                AgentDecision(
                    detected_intents=["opening_hours", "parking_question", "reservation_request"],
                    active_task="reservation_request",
                ),
                AgentDecision(detected_intents=["opening_hours", "parking_question"]),
                ResponseDraft(
                    response_text=(
                        "Otváracie hodiny: 10:00 - 21:00 every day except Sunday. "
                        "Parkovanie je dostupné pri reštaurácii."
                    )
                ),
                ok_response_validation(),
            ]
        )
    )

    result = runtime.run(build_agent_input("Odkedy ste otvoreny? A ci mate parkovanie?"))
    first_decision_validation = result.trace["validate_decision"][0]["validation"]

    assert "unsolicited_reservation_task" in first_decision_validation["issues"]
    assert result.requested_capabilities == []
    assert "Pre rezerváciu" not in result.response_text
    assert "Parkovanie" in result.response_text
    assert "10:00" in result.response_text


def test_follow_up_reservation_understands_party_size_without_repeating_answered_questions():
    chat_history = [
        {"role": "user", "content": "Odkedy ste otvoreny? A ci mate parkovanie?"},
        {
            "role": "assistant",
            "content": (
                "Otváracie hodiny: 10:00 - 21:00 every day except Sunday. "
                "Parkovanie je dostupné pri reštaurácii."
            ),
        },
    ]
    runtime = AgentRuntime(
        FakeStateLlm(
            [
                ChatMemoryExtraction(
                    answered_questions=["parking_question", "opening_hours"],
                    active_task="reservation_request",
                    task_status="collecting_info",
                    reservation_frame={
                        "guest_name": "Patrik",
                        "date": "zajtra",
                        "time": "09:00",
                        "party_size": 2,
                    },
                    current_reservation_fields={
                        "guest_name": "Patrik",
                        "date": "zajtra",
                        "time": "09:00",
                        "party_size": 2,
                    },
                    missing_fields=["phone"],
                ),
                reservation_decision(),
                ReservationExtractionResult(
                    field_updates={
                        "guest_name": "Patrik",
                        "date": "zajtra",
                        "time": "09:00",
                        "party_size": 2,
                    },
                    active_task="reservation_request",
                    task_status="collecting_info",
                ),
                TaskStateValidationResult(
                    task_status="collecting_info",
                    missing_fields=["phone"],
                    validation_errors=[
                        {
                            "field": "time",
                            "message": "09:00 is outside opening hours 10:00 - 21:00.",
                        }
                    ],
                ),
                ResponseDraft(
                    response_text=(
                        "Čas 09:00 je mimo otváracích hodín 10:00 - 21:00. "
                        "Pre rezerváciu ešte potrebujem telefónne číslo."
                    )
                ),
                ok_response_validation(),
            ]
        )
    )

    result = runtime.run(
        build_agent_input(
            "Chcem rezervaciu zajtra na rande. Volam sa Patrik a pridem s cajou okolo 9 rano.",
            chat_history,
        )
    )

    assert result.requested_capabilities == []
    assert "09:00" in result.response_text
    assert "10:00" in result.response_text
    assert "Parkovanie" not in result.response_text
    assert result.trace["build_chat_memory"]["extraction"]["answered_questions"] == [
        "parking_question",
        "opening_hours",
    ]
    assert result.trace["validate_task_state"]["llm_validation"]["validation_errors"][0]["field"] == "time"


def test_follow_up_phone_executes_capability_inside_graph():
    chat_history = [
        {
            "role": "user",
            "content": "Volam sa Patrik. Chcem rezervaciu zajtra o 19 pre dvoch.",
        },
        {
            "role": "assistant",
            "content": "Pre rezerváciu mi prosím pošlite ešte telefónne číslo.",
        },
    ]
    executor = FakeCapabilityExecutor()
    runtime = AgentRuntime(
        FakeStateLlm(
            [
                ChatMemoryExtraction(
                    active_task="reservation_request",
                    task_status="collecting_info",
                    reservation_frame={
                        "guest_name": "Patrik",
                        "date": "zajtra",
                        "time": "19:00",
                        "party_size": 2,
                    },
                    missing_fields=["phone"],
                    asked_fields=["phone"],
                ),
                reservation_decision(),
                ReservationExtractionResult(
                    field_updates={"phone": "+421944015686"},
                    active_task="reservation_request",
                    task_status="ready_to_submit",
                ),
                TaskStateValidationResult(task_status="ready_to_submit"),
                ResponseDraft(
                    response_text="Vašu žiadosť o rezerváciu sme prijali. Personál ju potvrdí."
                ),
                ok_response_validation(),
            ]
        )
    )

    result = runtime.run(build_agent_input("+421944015686", chat_history), executor)
    capability = result.requested_capabilities[0]
    frame = capability.input["reservation_frame"]

    assert result.response_mode == "after_capability"
    assert result.response_text == "Vašu žiadosť o rezerváciu sme prijali. Personál ju potvrdí."
    assert result.capability_results[0].status == "success"
    assert executor.requests[0].name == "reservation.create_request"
    assert frame["guest_name"] == "Patrik"
    assert frame["date"] == "zajtra"
    assert frame["time"] == "19:00"
    assert frame["party_size"] == 2
    assert frame["phone"] == "+421944015686"


def test_blocked_reservation_cannot_claim_ready_without_capability_result():
    runtime = AgentRuntime(
        FakeStateLlm(
            [
                ChatMemoryExtraction(
                    active_task="reservation_request",
                    task_status="collecting_info",
                    reservation_frame={
                        "guest_name": "Patrik",
                        "date": "zajtra",
                        "time": "09:00",
                        "party_size": 2,
                        "phone": "+421944015686",
                    },
                ),
                reservation_decision(),
                ReservationExtractionResult(active_task="reservation_request"),
                TaskStateValidationResult(
                    task_status="ready_to_submit",
                    validation_errors=[
                        {
                            "field": "time",
                            "code": "outside_opening_hours",
                            "message": "09:00 is outside opening hours 10:00 - 21:00.",
                        }
                    ],
                ),
                ResponseDraft(
                    response_text=(
                        "Rezervácia na zajtra o 9:00 pre 2 osoby je pripravená "
                        "a čaká na potvrdenie personálom."
                    )
                ),
                ResponseValidationResult(
                    ok=False,
                    needs_revision=True,
                    claims_capability_outcome=True,
                    claims_task_ready=True,
                    ignores_task_blockers=True,
                ),
                ResponseDraft(
                    response_text=(
                        "Čas 09:00 je mimo otváracích hodín 10:00 - 21:00. "
                        "Prosím, vyberte čas počas otváracích hodín."
                    )
                ),
                ResponseValidationResult(
                    ok=True,
                    needs_revision=False,
                    mentions_validation_errors=True,
                ),
            ]
        )
    )

    result = runtime.run(build_agent_input("+421944015686"))
    task_validation = result.trace["validate_task_state"]
    first_response_validation = result.trace["validate_response"][0]["validation"]

    assert result.requested_capabilities == []
    assert result.capability_results == []
    assert task_validation["task_status"] == "blocked_by_validation"
    assert task_validation["llm_requested_task_status"] == "ready_to_submit"
    assert result.trace["plan_capability"]["gate"]["blockers"] == [
        "task_status_not_ready",
        "validation_errors",
    ]
    assert "capability_outcome_claim_without_result" in first_response_validation["issues"]
    assert "task_ready_claim_while_blocked" in first_response_validation["issues"]
    assert "09:00" in result.response_text
    assert "10:00" in result.response_text


def test_decision_validation_retries_after_unsupported_intent():
    runtime = AgentRuntime(
        FakeStateLlm(
            [
                ChatMemoryExtraction(),
                AgentDecision(
                    primary_intent="unsupported_custom_intent",
                    detected_intents=["unsupported_custom_intent"],
                ),
                AgentDecision(primary_intent="unknown", detected_intents=["unknown"]),
                ResponseDraft(response_text="Ako vám môžem pomôcť?"),
                ok_response_validation(),
            ]
        )
    )

    result = runtime.run(build_agent_input("hello"))

    assert result.trace["validate_decision"][0]["validation"]["rejected_intents"] == [
        "unsupported_custom_intent"
    ]
    assert len(result.trace["validate_decision"]) == 2
    assert result.requested_capabilities == []


def test_opening_hours_direct_response_does_not_execute_capability():
    runtime = AgentRuntime(
        FakeStateLlm(
            [
                ChatMemoryExtraction(current_question_intents=["opening_hours"]),
                AgentDecision(detected_intents=["opening_hours"]),
                ResponseDraft(response_text="Máme otvorené: 10:00 - 21:00 every day except Sunday."),
                ok_response_validation(),
            ]
        )
    )

    result = runtime.run(build_agent_input("Kedy mate otvorene?"))

    assert result.requested_capabilities == []
    assert result.response_mode == "direct"
    assert "10:00 - 21:00 every day except Sunday" in result.response_text


def test_agent_result_schema_still_accepts_requested_capabilities():
    result = AgentResult(
        requested_capabilities=[
            CapabilityRequest(name="reservation.create_request", input={"reservation_frame": {}})
        ]
    )

    assert result.requested_capabilities[0].name == "reservation.create_request"


def test_agent_graph_is_real_langgraph_with_start_and_end():
    graph = AgentGraph(
        llm=FakeStateLlm([]),
        profile_loader=AgentProfileLoader(),
        capability_executor=None,
        max_decision_iterations=1,
        max_response_iterations=1,
    )
    compiled_graph = graph.graph.get_graph()
    node_names = set(compiled_graph.nodes)
    edge_pairs = {(edge.source, edge.target) for edge in compiled_graph.edges}

    assert "__start__" in node_names
    assert "__end__" in node_names
    assert ("__start__", "load_context") in edge_pairs
    assert ("finalize", "__end__") in edge_pairs
    assert "execute_capability" in node_names
