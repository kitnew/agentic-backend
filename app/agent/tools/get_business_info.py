from app.agent.tools.base import BaseAgentTool


class GetBusinessInfoTool(BaseAgentTool):
    name = "get_business_info"
    description = "Return basic public business information for the current tenant."

    def execute(self):
        return {
            "opening_hours": "10:00 - 21:00 every day except Sunday",
            "parking": "Parking is available at the restaurant on the street",
            "address": "Demo ulica 12, Bratislava",
            "phone": "+421 900 000 000",
            "menu_summary": "Sezónne jedlá, denné menu a výber domácich dezertov.",
        }
