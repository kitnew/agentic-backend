from langchain_core.tools import tool

@tool
def create_reservation():
    return "reservation created"