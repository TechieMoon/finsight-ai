"""Report presence, never secret values. No external requests."""

import json
import platform

from finsight.config import settings

config = settings()
print(
    json.dumps(
        {
            "python": platform.python_version(),
            "mode": config.finsight_mode,
            "dart_key_present": bool(config.dart_api_key.get_secret_value()),
            "openai_key_present": bool(config.openai_api_key.get_secret_value()),
            "real_api_calls_performed": False,
        },
        indent=2,
    )
)
