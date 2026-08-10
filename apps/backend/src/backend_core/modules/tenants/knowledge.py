from hashlib import sha256


def knowledge_content_hash(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


def knowledge_content_matches(left: str, right: str) -> bool:
    return _without_final_newline(left) == _without_final_newline(right)


def render_knowledge_context(documents: list[tuple[str, str]]) -> str:
    if len(documents) == 1 and documents[0][0] == "knowledge":
        return documents[0][1]
    return "\n\n".join(
        f"# Knowledge source: {key}.md\n\n{content}" for key, content in documents
    )


def _without_final_newline(value: str) -> str:
    if value.endswith("\r\n"):
        return value[:-2]
    if value.endswith("\n"):
        return value[:-1]
    return value
