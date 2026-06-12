from app.agent.tools.base import BaseAgentTool


class CreateReservationTool(BaseAgentTool):
    name = "create_reservation"
    description = "Create a prototype reservation request for the current conversation."

    def execute(self):
        return "reservation created"
