import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.main import app as _app


class _StripPrefix:
    """Strip /api prefix before forwarding to FastAPI (Vercel passes full path)."""

    def __init__(self, app, prefix="/api"):
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            path = scope.get("path", "")
            if path.startswith(self.prefix):
                scope = dict(scope)
                scope["path"] = path[len(self.prefix):] or "/"
                if "raw_path" in scope:
                    scope["raw_path"] = scope["path"].encode()
        await self.app(scope, receive, send)


app = _StripPrefix(_app)
