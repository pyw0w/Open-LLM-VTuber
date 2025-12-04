# config_manager/translate.py
from typing import Literal, Optional, Dict, ClassVar, List
from pydantic import ValidationInfo, Field, model_validator
from .i18n import I18nMixin, Description

# --- Sub-models for specific Translator providers ---


class DeepLXConfig(I18nMixin):
    """Configuration for DeepLX translation service."""

    deeplx_target_lang: str = Field(..., alias="deeplx_target_lang")
    deeplx_api_endpoint: str = Field(..., alias="deeplx_api_endpoint")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "deeplx_target_lang": Description(
            en="Target language code for DeepLX translation",
            zh="DeepLX 翻译的目标语言代码",
            ru="Код целевого языка для перевода DeepLX",
        ),
        "deeplx_api_endpoint": Description(
            en="API endpoint URL for DeepLX service",
            zh="DeepLX 服务的 API 端点 URL",
            ru="URL эндпоинта API для службы DeepLX",
        ),
    }


class TencentConfig(I18nMixin):
    """Configuration for tencent translation service."""

    secret_id: str = Field(..., description="Tencent Secret ID")
    secret_key: str = Field(..., description="Tencent Secret Key")
    region: str = Field(..., description="Region for Tencent Service")
    source_lang: str = Field(
        ..., description="Source language code for tencent translation"
    )
    target_lang: str = Field(
        ..., description="Target language code for tencent translation"
    )

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "secret_id": Description(
            en="Tencent Secret ID",
            zh="腾讯服务的Secret ID",
            ru="Tencent Secret ID",
        ),
        "secret_key": Description(
            en="Tencent Secret Key",
            zh="腾讯服务的Secret Key",
            ru="Tencent Secret Key",
        ),
        "region": Description(
            en="Region for Tencent Service",
            zh="腾讯服务使用的区域",
            ru="Регион для службы Tencent",
        ),
        "source_lang": Description(
            en="Source language code for tencent translation",
            zh="腾讯翻译的源语言代码",
            ru="Код исходного языка для перевода Tencent",
        ),
        "target_lang": Description(
            en="Target language code for tencent translation",
            zh="腾讯翻译的目标语言代码",
            ru="Код целевого языка для перевода Tencent",
        ),
    }


# --- Main TranslatorConfig model ---


class TranslatorConfig(I18nMixin):
    """Configuration for translation services."""

    translate_audio: bool = Field(..., alias="translate_audio")
    translate_provider: Literal["deeplx", "tencent"] = Field(
        ..., alias="translate_provider"
    )
    deeplx: Optional[DeepLXConfig] = Field(None, alias="deeplx")
    tencent: Optional[TencentConfig] = Field(None, alias="tencent")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "translate_audio": Description(
            en="Enable audio translation (requires DeepLX deployment)",
            zh="启用音频翻译（需要部署 DeepLX）",
            ru="Включить перевод аудио (требуется развёртывание DeepLX)",
        ),
        "translate_provider": Description(
            en="Translation service provider to use",
            zh="要使用的翻译服务提供者",
            ru="Провайдер службы перевода для использования",
        ),
        "deeplx": Description(
            en="Configuration for DeepLX translation service",
            zh="DeepLX 翻译服务配置",
            ru="Конфигурация службы перевода DeepLX",
        ),
        "tencent": Description(
            en="Configuration for TenCent translation service",
            zh="腾讯 翻译服务配置",
            ru="Конфигурация службы перевода TenCent",
        ),
    }

    @model_validator(mode="after")
    def check_translator_config(cls, values: "TranslatorConfig", info: ValidationInfo):
        translate_audio = values.translate_audio
        translate_provider = values.translate_provider

        if translate_audio:
            if translate_provider == "deeplx" and values.deeplx is None:
                raise ValueError(
                    "DeepLX configuration must be provided when translate_audio is True and translate_provider is 'deeplx'"
                )
            elif translate_provider == "tencent" and values.tencent is None:
                raise ValueError(
                    "Tencent configuration must be provided when translate_audio is True and translate_provider is 'tencent'"
                )

        return values


class TTSPreprocessorConfig(I18nMixin):
    """Configuration for TTS preprocessor."""

    remove_special_char: bool = Field(..., alias="remove_special_char")
    ignore_brackets: bool = Field(default=True, alias="ignore_brackets")
    ignore_parentheses: bool = Field(default=True, alias="ignore_parentheses")
    ignore_asterisks: bool = Field(default=True, alias="ignore_asterisks")
    ignore_angle_brackets: bool = Field(default=True, alias="ignore_angle_brackets")
    forbidden_words_enabled: bool = Field(
        default=False, alias="forbidden_words_enabled"
    )
    forbidden_words: List[str] = Field(default_factory=list, alias="forbidden_words")
    forbidden_words_replacement: str = Field(
        default="[censored]", alias="forbidden_words_replacement"
    )
    translator_config: TranslatorConfig = Field(..., alias="translator_config")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "remove_special_char": Description(
            en="Remove special characters from the input text",
            zh="从输入文本中删除特殊字符",
            ru="Удалить специальные символы из входного текста",
        ),
        "forbidden_words_enabled": Description(
            en="Enable filtering of forbidden words in TTS text",
            zh="启用 TTS 文本中的禁用词过滤",
            ru="Включить фильтрацию запрещенных слов в тексте TTS",
        ),
        "forbidden_words": Description(
            en="List of forbidden words to filter from TTS text",
            zh="要从 TTS 文本中过滤的禁用词列表",
            ru="Список запрещенных слов для фильтрации из текста TTS",
        ),
        "forbidden_words_replacement": Description(
            en="Replacement text for forbidden words (e.g., '[censored]')",
            zh="禁用词的替换文本（例如，'[censored]'）",
            ru="Текст замены для запрещенных слов (например, '[censored]')",
        ),
        "translator_config": Description(
            en="Configuration for translation services",
            zh="翻译服务的配置",
            ru="Конфигурация для служб перевода",
        ),
    }
