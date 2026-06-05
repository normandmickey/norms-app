from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path
from web.views import health, home, public_chat_widget, public_chat_widget_chat, public_chat_widget_embed, report_assistant, report_assistant_export, reports

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("health/", health, name="health"),
    path("", home, name="home"),
    path("reports/", reports, name="reports"),
    path("reports/assistant/", report_assistant, name="report_assistant"),
    path("reports/export/", report_assistant_export, name="report_assistant_export"),
    path("chat/", public_chat_widget, name="public_chat_widget"),
    path("chat/send/", public_chat_widget_chat, name="public_chat_widget_chat"),
    path("chat/embed.js", public_chat_widget_embed, name="public_chat_widget_embed"),
]
