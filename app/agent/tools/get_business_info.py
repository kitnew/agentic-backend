from langchain_core.tools import tool


@tool
def get_business_info():
    return {
        "opening_hours": "10:00 - 21:00 every day except Sunday",
        "parking": "Parking is available at the restaurant on the street",
        "address": "Demo ulica 12, Bratislava",
        "phone": "+421 900 000 000",
        "menu_summary": "Sezónne jedlá, denné menu a výber domácich dezertov."
    }