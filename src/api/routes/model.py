from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field, WithJsonSchema, model_validator


def _normalize_chat_identifier(value: Any) -> Any:
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return value


ChatIdentifier = Annotated[
    str,
    BeforeValidator(_normalize_chat_identifier),
    WithJsonSchema(
        {"anyOf": [{"type": "string"}, {"type": "integer"}]},
        mode="validation",
    ),
]


class ChatInputResource(BaseModel):
    name: str
    mime_type: str = Field(alias="mimeType")
    url: str


class ChatFileInputResource(ChatInputResource):
    text: str


class ChatEfileInputResource(ChatInputResource):
    cluster_id: str | int = Field(alias="clusterId")


class ChatTextInput(BaseModel):
    type: Literal["text"]
    text: str


class ChatReferenceInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["reference"]
    text: str


class ChatFileInput(BaseModel):
    type: Literal["file"]
    resource: ChatFileInputResource


class ChatImageInput(BaseModel):
    type: Literal["image"]
    resource: ChatFileInputResource


class ChatVideoInput(BaseModel):
    type: Literal["video"]
    resource: ChatFileInputResource


class ChatAudioInput(BaseModel):
    type: Literal["audio"]
    resource: ChatFileInputResource


class ChatEfileInput(BaseModel):
    type: Literal["efile"]
    resource: ChatEfileInputResource


class ChatInteractionResult(BaseModel):
    value: str
    step_name: str = Field(default="", alias="stepName")


class ChatResourceCardInteractionResource(BaseModel):
    type: Literal["resource_card"]
    interaction_id: str
    result: list[ChatInteractionResult] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def require_selection(self) -> ChatResourceCardInteractionResource:
        self.interaction_id = self.interaction_id.strip()
        self.result[0].value = self.result[0].value.strip()
        if not self.interaction_id:
            raise ValueError("interaction_id is required")
        if not self.result[0].value:
            raise ValueError("interaction result value is required")
        return self


ChatInteractionResource = ChatResourceCardInteractionResource


class ChatInteractionInput(BaseModel):
    type: Literal["interaction"]
    resource: ChatInteractionResource


ChatInput = Annotated[
    ChatTextInput
    | ChatReferenceInput
    | ChatFileInput
    | ChatImageInput
    | ChatVideoInput
    | ChatAudioInput
    | ChatEfileInput
    | ChatInteractionInput,
    Field(discriminator="type"),
]


class UserChatRequest(BaseModel):
    conversation_id: ChatIdentifier = Field(alias="conversationId")
    user_id: ChatIdentifier = Field(alias="userId")
    extra: dict[str, Any] | None = None
    inputs: list[ChatInput]
    time: str | None = None

    @model_validator(mode="after")
    def require_user_and_input(self) -> UserChatRequest:
        if not self.user_id.strip():
            raise ValueError("userId is required")
        if not self.inputs:
            raise ValueError("inputs must not be empty")
        return self


class UserStopRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    conversation_id: ChatIdentifier = Field(
        ...,
        validation_alias=AliasChoices("conversation_id", "conversationId"),
        serialization_alias="conversationId",
    )
    user_id: ChatIdentifier = Field(
        ...,
        validation_alias=AliasChoices("user_id", "userId"),
        serialization_alias="userId",
    )


class UserChatCacheRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    conversation_id: ChatIdentifier = Field(
        ...,
        validation_alias=AliasChoices("conversation_id", "conversationId"),
        serialization_alias="conversationId",
    )


class SuggestedQuestion(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question: str = ""
    weight: int | float = 1
    enable: bool = True


class UserAgentRestartRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    restart_only: bool = Field(
        default=False,
        validation_alias=AliasChoices("restart_only", "restartOnly"),
        serialization_alias="restartOnly",
    )
    model: str | None = Field(
        default=None,
        min_length=1,
        validation_alias=AliasChoices("model", "currentModel"),
    )
    name: str | None = None
    desc: str | None = None
    avatar: str | None = None
    system_prompt: str | None = Field(
        default=None,
        validation_alias=AliasChoices("system_prompt", "systemPrompt", "prompt"),
        serialization_alias="systemPrompt",
    )
    welcome_message: str | None = Field(
        default=None,
        validation_alias=AliasChoices("welcome_message", "welcomeMessage"),
        serialization_alias="welcomeMessage",
    )
    suggested_questions: list[SuggestedQuestion] | None = Field(
        default=None,
        validation_alias=AliasChoices("suggested_questions", "suggestedQuestions"),
        serialization_alias="suggestedQuestions",
    )
    datasets: list[dict[str, Any]] | None = None
    mcp: list[dict[str, Any]] | None = None
    skills: list[dict[str, Any]] | None = None
    llm_args: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("llm_args", "llmArgs", "currentArgs"),
        serialization_alias="llmArgs",
    )


class PrivateResourcesUpdateRequest(BaseModel):
    skills: list[dict[str, Any]]
    mcp: list[dict[str, Any]]
    datasets: list[dict[str, Any]]


__all__ = [
    "ChatEfileInput",
    "ChatEfileInputResource",
    "ChatAudioInput",
    "ChatFileInput",
    "ChatFileInputResource",
    "ChatImageInput",
    "ChatInput",
    "ChatInputResource",
    "ChatInteractionInput",
    "ChatInteractionResource",
    "ChatInteractionResult",
    "ChatReferenceInput",
    "ChatResourceCardInteractionResource",
    "ChatTextInput",
    "ChatVideoInput",
    "PrivateResourcesUpdateRequest",
    "SuggestedQuestion",
    "UserAgentRestartRequest",
    "UserChatCacheRequest",
    "UserChatRequest",
    "UserStopRequest",
]
