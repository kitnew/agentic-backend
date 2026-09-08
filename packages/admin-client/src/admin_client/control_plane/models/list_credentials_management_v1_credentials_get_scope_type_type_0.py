from enum import Enum


class ListCredentialsManagementV1CredentialsGetScopeTypeType0(str, Enum):
    PLATFORM = "platform"
    TENANT = "tenant"

    def __str__(self) -> str:
        return str(self.value)
