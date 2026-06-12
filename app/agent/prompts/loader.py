def load_system_prompt():
    with open("./app/agent/prompts/system.txt", "r") as f:
        return f.read()