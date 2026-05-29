from langchain_openai import AzureChatOpenAI

from app.agent.graph import build_agent

llm = AzureChatOpenAI(
    azure_endpoint="https://ct-val.cognitiveservices.azure.com/",
    azure_deployment="gpt-4o-mini",
    api_version="2025-01-01-preview",
    api_key="1mrDubpfPwE2niMMIaKNRhNEX6o5jT9jOBXGl5rpPcEKhZzLyXzrJQQJ99CDACE1PydXJ3w3AAAAACOGNlJ4",
)

agent = build_agent(llm)