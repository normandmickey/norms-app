import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .chat_widget import ChatWidgetError, chat, embed_script, widget_button_label, widget_enabled, widget_title, widget_welcome_message
from .report_assistant import ReportAssistantError, assistant_enabled as report_assistant_enabled, available_report_models, build_report_query, execute_report_sql, export_report


@login_required
def home(request):
    return render(request, "home.html", {"project_name": "norms-app"})


def health(_request):
    return JsonResponse({"ok": True, "service": "norms-app"})


def _reports_context():
    return {
        "report_models": available_report_models(),
        "report_assistant_enabled": report_assistant_enabled(),
        "report_assistant_prompt": "",
        "report_assistant_error": "",
        "report_assistant_result": None,
    }


@login_required
def reports(request):
    return render(request, "reports.html", _reports_context())


@login_required
@require_POST
def report_assistant(request):
    context = _reports_context()
    prompt = (request.POST.get("prompt") or "").strip()
    context["report_assistant_prompt"] = prompt
    try:
        query = build_report_query(prompt)
        result = execute_report_sql(query["sql"])
        context["report_assistant_result"] = {
            **query,
            **result,
        }
    except ReportAssistantError as exc:
        context["report_assistant_error"] = str(exc)
    return render(request, "reports.html", context)


@login_required
@require_POST
def report_assistant_export(request):
    context = _reports_context()
    prompt = (request.POST.get("prompt") or "").strip()
    file_format = (request.POST.get("export_format") or "csv").strip().lower()
    context["report_assistant_prompt"] = prompt
    try:
        query = build_report_query(prompt)
        result = execute_report_sql(query["sql"])
        context["report_assistant_result"] = {
            **query,
            **result,
        }
        payload, content_type, filename = export_report(file_format, query["title"], result["columns"], result["rows"])
    except ReportAssistantError as exc:
        context["report_assistant_error"] = str(exc)
        return render(request, "reports.html", context, status=400)
    response = HttpResponse(payload, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@xframe_options_exempt
def public_chat_widget(request):
    enabled = widget_enabled()
    return render(request, "chat_widget.html", {
        "chat_widget_enabled": enabled,
        "chat_widget_title": widget_title(),
        "chat_widget_welcome_message": widget_welcome_message() if enabled else "Chat widget is not configured yet.",
        "chat_widget_chat_url": reverse("public_chat_widget_chat"),
        "embedded": request.GET.get("embedded") == "1",
    }, status=200 if enabled else 503)


@csrf_exempt
def public_chat_widget_chat(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required."}, status=405)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}") if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON payload."}, status=400)
    try:
        return JsonResponse({"ok": True, **chat(payload.get("message") or "", payload.get("history") or [])})
    except ChatWidgetError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"Provider request failed. {exc}"}, status=502)


def public_chat_widget_embed(request):
    iframe_url = request.build_absolute_uri(reverse("public_chat_widget"))
    return HttpResponse(embed_script(iframe_url, widget_button_label()), content_type="application/javascript")

