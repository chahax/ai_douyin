"""
Lightweight service exports.

Keep package import cheap so modules like ``src.services.database`` do not
eagerly import video/audio generation dependencies.
"""

from importlib import import_module


_EXPORTS = {
    "DialogueGenerationRequest": ("src.services.generation_service", "DialogueGenerationRequest"),
    "GenerationRequest": ("src.services.generation_service", "GenerationRequest"),
    "GenerationResult": ("src.services.generation_service", "GenerationResult"),
    "GenerationService": ("src.services.generation_service", "GenerationService"),
    "KnowledgeImportRequest": ("src.services.generation_service", "KnowledgeImportRequest"),
    "QuickGenerationRequest": ("src.services.generation_service", "QuickGenerationRequest"),
    "AutoPublishRequest": ("src.services.auto_publish_service", "AutoPublishRequest"),
    "AutoPublishResult": ("src.services.auto_publish_service", "AutoPublishResult"),
    "AutoPublishService": ("src.services.auto_publish_service", "AutoPublishService"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module 'src.services' has no attribute {name!r}")

    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
