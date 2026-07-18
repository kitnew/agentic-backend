from app.agent_runtime.text_fragmenter import TextFragmenter


def test_fragmenter_preserves_text_and_prefers_boundaries():
    text = "Toto je prvá slovenská veta. Toto je druhá, ešte dlhšia veta! Koniec."
    fragmenter = TextFragmenter(20, 40)
    parts = fragmenter.add(text) + fragmenter.finish()
    assert "".join(parts) == text
    assert parts[0] == "Toto je prvá slovenská veta. "
    assert all(len(part) <= 40 for part in parts[:-1])


def test_fragmenter_timeout_and_final_short_fragment():
    fragmenter = TextFragmenter(10, 20)
    assert fragmenter.add("desať znakov bez") == []
    parts = fragmenter.add("", timed_out=True) + fragmenter.finish()
    assert "".join(parts) == "desať znakov bez"
