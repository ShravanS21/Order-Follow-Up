from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("tasks", views.tasks_page, name="tasks"),
    path("tasks/<int:tid>", views.update_task, name="update_task"),
    path("tasks/<int:tid>/ai-draft", views.ai_draft, name="ai_draft"),
    path("ai/daily-brief", views.ai_daily_brief, name="ai_daily_brief"),
    path("upload", views.upload, name="upload"),
    path("load-sample", views.load_sample, name="load_sample"),
    path("report", views.report, name="report"),
    path("report.csv", views.report_csv, name="report_csv"),
    path("audit", views.audit_page, name="audit"),
    path("settings", views.settings_page, name="settings"),
    path("reset", views.reset, name="reset"),
    path("user", views.switch_user, name="switch_user"),
]
