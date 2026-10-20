from django.urls import path

from kwd import api

urlpatterns = [
    path("session", api.session_status),
    path("q", api.query),
    path("rpc/<str:fn>", api.rpc),
    path("fn/<str:name>", api.function),
    path("storage/upload", api.storage_upload),
    path("storage/sign", api.storage_sign),
    path("storage/object", api.storage_object),
]
