from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.cascade_endpointing import CascadeEndpointing
    from ..models.cascade_interruption import CascadeInterruption
    from ..models.cascade_response_scheduling import CascadeResponseScheduling
    from ..models.cascade_speech_activity import CascadeSpeechActivity
    from ..models.cascade_tokenizer import CascadeTokenizer
    from ..models.local_vad_commit import LocalVADCommit
    from ..models.provider_vad_commit import ProviderVADCommit


T = TypeVar("T", bound="CascadePolicies")


@_attrs_define
class CascadePolicies:
    """
    Attributes:
        endpointing (CascadeEndpointing):
        interruption (CascadeInterruption):
        response_scheduling (CascadeResponseScheduling):
        speech_activity (CascadeSpeechActivity):
        stt_commit (LocalVADCommit | ProviderVADCommit):
        tokenizer (CascadeTokenizer):
    """

    endpointing: CascadeEndpointing
    interruption: CascadeInterruption
    response_scheduling: CascadeResponseScheduling
    speech_activity: CascadeSpeechActivity
    stt_commit: LocalVADCommit | ProviderVADCommit
    tokenizer: CascadeTokenizer

    def to_dict(self) -> dict[str, Any]:
        from ..models.local_vad_commit import LocalVADCommit

        endpointing = self.endpointing.to_dict()

        interruption = self.interruption.to_dict()

        response_scheduling = self.response_scheduling.to_dict()

        speech_activity = self.speech_activity.to_dict()

        stt_commit: dict[str, Any]
        if isinstance(self.stt_commit, LocalVADCommit):
            stt_commit = self.stt_commit.to_dict()
        else:
            stt_commit = self.stt_commit.to_dict()

        tokenizer = self.tokenizer.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "endpointing": endpointing,
                "interruption": interruption,
                "response_scheduling": response_scheduling,
                "speech_activity": speech_activity,
                "stt_commit": stt_commit,
                "tokenizer": tokenizer,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.cascade_endpointing import CascadeEndpointing
        from ..models.cascade_interruption import CascadeInterruption
        from ..models.cascade_response_scheduling import CascadeResponseScheduling
        from ..models.cascade_speech_activity import CascadeSpeechActivity
        from ..models.cascade_tokenizer import CascadeTokenizer
        from ..models.local_vad_commit import LocalVADCommit
        from ..models.provider_vad_commit import ProviderVADCommit

        d = dict(src_dict)
        endpointing = CascadeEndpointing.from_dict(d.pop("endpointing"))

        interruption = CascadeInterruption.from_dict(d.pop("interruption"))

        response_scheduling = CascadeResponseScheduling.from_dict(
            d.pop("response_scheduling")
        )

        speech_activity = CascadeSpeechActivity.from_dict(d.pop("speech_activity"))

        def _parse_stt_commit(data: object) -> LocalVADCommit | ProviderVADCommit:
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                stt_commit_type_0 = LocalVADCommit.from_dict(data)

                return stt_commit_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            if not isinstance(data, dict):
                raise TypeError()
            stt_commit_type_1 = ProviderVADCommit.from_dict(data)

            return stt_commit_type_1

        stt_commit = _parse_stt_commit(d.pop("stt_commit"))

        tokenizer = CascadeTokenizer.from_dict(d.pop("tokenizer"))

        cascade_policies = cls(
            endpointing=endpointing,
            interruption=interruption,
            response_scheduling=response_scheduling,
            speech_activity=speech_activity,
            stt_commit=stt_commit,
            tokenizer=tokenizer,
        )

        return cascade_policies
