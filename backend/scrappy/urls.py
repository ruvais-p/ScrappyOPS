from django.urls import include, path, re_path

from core.api import views as api
from core.api import frontend
from portal import views as portal

urlpatterns = [
    path("healthz", api.healthz),
    # login (same addresses and answers as before, so the dashboards need no change)
    path("auth/v1/token", api.token),
    path("auth/v1/logout", api.logout),
    path("auth/v1/user", api.user_info),
    # data
    path("rest/v1/rpc/<str:fn>", api.rpc_call),
    path("rest/v1/<str:table>", api.rest_table),
    # the two server-side helpers that used to be edge functions
    path("functions/v1/bill-pdf", api.bill_pdf),
    path("functions/v1/hq-logins", api.hq_logins),
    # one front door: the login page, sign-out, and the staff app (Scrappy Field). portal.gate decides who may open which page.
    path("login/", portal.login),
    path("logout/", portal.logout),
    path("kwd/", portal.kwd_app),
    path("kwd/api/", include("kwd.urls")),
    # optional: serve the website files from this same server
    re_path(r"^(?P<path>.*)$", frontend.serve),
]
