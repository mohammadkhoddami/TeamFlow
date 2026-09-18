"""sqladmin application subclass.

Overrides the index route so `/admin` lands on an operational dashboard
instead of the default empty page. Everything else (routes, static files,
menu) is stock sqladmin.
"""

from sqladmin import Admin
from sqladmin.authentication import login_required
from starlette.requests import Request
from starlette.responses import Response

from app.admin.dashboard import collect_dashboard_stats


class TeamFlowAdmin(Admin):
    @login_required
    async def index(self, request: Request) -> Response:
        stats = await collect_dashboard_stats()
        return await self.templates.TemplateResponse(
            request, "sqladmin/index.html", {"stats": stats}
        )
