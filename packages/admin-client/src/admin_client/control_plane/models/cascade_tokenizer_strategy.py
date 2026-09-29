from enum import Enum


class CascadeTokenizerStrategy(str, Enum):
    PHRASE = "phrase"
    SENTENCE = "sentence"

    def __str__(self) -> str:
        return str(self.value)
