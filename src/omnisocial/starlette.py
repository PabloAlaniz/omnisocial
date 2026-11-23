"""`pip install omnisocial[starlette]`"""

from omnisocial.entrypoints.starlette import meta_data_deletion_routes, oauth_routes, webhook_routes

__all__ = ["meta_data_deletion_routes", "oauth_routes", "webhook_routes"]
