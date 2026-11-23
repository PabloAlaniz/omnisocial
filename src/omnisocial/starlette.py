"""`pip install omnisocial[starlette]`"""

from omnisocial.entrypoints.starlette import oauth_routes, webhook_routes

__all__ = ["oauth_routes", "webhook_routes"]
