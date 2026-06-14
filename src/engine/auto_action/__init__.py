from src.engine.config.auto_action_config import AutoActionConfig

def available_detectors():
    from src.plugins.detectors.detector import available_detectors as _impl
    return _impl()

__all__ = [
    "AutoActionConfig",
    "available_detectors",
]
