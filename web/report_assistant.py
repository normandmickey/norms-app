import csv
import html
import io
import json
import re
import unicodedata
from urllib import error, request as urllib_request

from django.apps import apps
from django.conf import settings
from django.db import connection, transaction


DEFAULT_MODELS = {
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-3-5-sonnet-latest",
    "gemini": "gemini-2.5-flash",
}

EXCLUDED_MODEL_NAMES = {
    "formfieldmapping", "formtemplate", "notificationrule", "notificationrun",
    "pdffieldmapping", "pdftemplate", "resourcefield", "resourcefieldlabel",
    "resourcelabel",
}

EXCLUDED_MODEL_SUFFIXES = ("attachment", "mapping", "template", "run")


class ReportAssistantError(RuntimeError):
    pass


def assistant_enabled() -> bool:
    return bool(ai_provider() and ai_model() and ai_api_key())


def ai_provider() -> str:
    return str(getattr(settings, "APP_AI_PROVIDER", getattr(settings, "CHAT_WIDGET_PROVIDER", "openai"))).strip().lower() or "openai"


def ai_api_key() -> str:
    return str(getattr(settings, "APP_AI_API_KEY", getattr(settings, "CHAT_WIDGET_API_KEY", ""))).strip()


def ai_model() -> str:
    configured = str(getattr(settings, "APP_AI_MODEL", getattr(settings, "CHAT_WIDGET_MODEL", ""))).strip()
    return configured or DEFAULT_MODELS.get(ai_provider(), DEFAULT_MODELS["openai"])


def ai_system_prompt() -> str:
    return str(getattr(settings, "APP_AI_SYSTEM_PROMPT", "")).strip()


def _candidate_models():
    try:
        app_config = apps.get_app_config("web")
    except LookupError:
        return []
    candidates = []
    for model in app_config.get_models():
        opts = model._meta
        model_name = opts.model_name.lower()
        if opts.abstract or opts.proxy:
            continue
        if model_name in EXCLUDED_MODEL_NAMES or model_name.endswith(EXCLUDED_MODEL_SUFFIXES):
            continue
        candidates.append(model)
    return sorted(candidates, key=lambda model: model._meta.verbose_name_plural.lower())


def _model_description(model) -> str:
    field_names = [field.name for field in model._meta.fields if field.name not in {"id", "created_at", "updated_at"}]
    sample = ", ".join(field_names[:6])
    if sample:
        return f"{model._meta.verbose_name_plural.title()} with fields like {sample}."
    return f"{model._meta.verbose_name_plural.title()} records."


def available_report_models() -> list[dict]:
    rows = []
    for model in _candidate_models():
        rows.append({
            "label": model._meta.verbose_name_plural.title(),
            "model": model._meta.model_name,
            "table": model._meta.db_table,
            "total": model.objects.count(),
            "description": _model_description(model),
        })
    return rows


def _schema_config():
    return {
        model._meta.db_table: {
            "label": model._meta.verbose_name_plural.title(),
            "model": model,
            "description": _model_description(model),
        }
        for model in _candidate_models()
    }


def _schema_payload():
    payload = {}
    for table_name, config in _schema_config().items():
        columns = []
        for field in config["model"]._meta.fields:
            columns.append({
                "name": field.column,
                "type": field.get_internal_type(),
            })
        payload[table_name] = {
            "label": config["label"],
            "description": config["description"],
            "columns": columns,
        }
    return payload


def _post_json(url, payload, headers):
    body = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=body,
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return response.status, raw, json.loads(raw or "{}")
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return exc.code, raw, None
    except error.URLError as exc:
        raise ReportAssistantError(f"Provider request failed: {exc.reason}") from exc


def _extract_json_text(text: str) -> dict:
    candidate = str(text or "").strip()
    if not candidate:
        raise ReportAssistantError("The model returned an empty response.")
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, re.DOTALL)
        if not match:
            raise ReportAssistantError("Could not parse the model response as JSON.")
        return json.loads(match.group(0))


def _extract_openai_text(payload):
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "").strip()
            for part in content
            if isinstance(part, dict) and part.get("text")
        ).strip()
    return ""


def _assistant_prompt(prompt: str) -> str:
    rules = (
        "Return JSON only with keys title, summary, sql. "
        "Generate one read-only PostgreSQL SELECT/CTE query only. "
        "Never use INSERT, UPDATE, DELETE, ALTER, DROP, CREATE, GRANT, COPY, TRUNCATE, or comments. "
        "Use only these tables and columns. Keep results concise and include LIMIT 200 or less."
    )
    return f"{rules}\n\nSCHEMA = {json.dumps(_schema_payload(), ensure_ascii=False)}\n\nUSER_PROMPT = {prompt}"


def _query_openai(prompt: str) -> dict:
    messages = []
    system_parts = []
    if ai_system_prompt():
        system_parts.append(ai_system_prompt())
    system_parts.append(_assistant_prompt(prompt))
    messages.append({"role": "system", "content": "\n\n".join(system_parts)})
    messages.append({"role": "user", "content": prompt})
    status, raw, payload = _post_json(
        "https://api.openai.com/v1/chat/completions",
        {"model": ai_model(), "messages": messages, "response_format": {"type": "json_object"}},
        {"Authorization": f"Bearer {ai_api_key()}"},
    )
    if status >= 400:
        raise ReportAssistantError(f"OpenAI request failed ({status}): {raw[:300]}")
    return _extract_json_text(_extract_openai_text(payload or {}))


def _query_anthropic(prompt: str) -> dict:
    system_parts = []
    if ai_system_prompt():
        system_parts.append(ai_system_prompt())
    system_parts.append(_assistant_prompt(prompt))
    status, raw, payload = _post_json(
        "https://api.anthropic.com/v1/messages",
        {
            "model": ai_model(),
            "max_tokens": 900,
            "system": "\n\n".join(system_parts),
            "messages": [{"role": "user", "content": prompt}],
        },
        {
            "x-api-key": ai_api_key(),
            "anthropic-version": "2023-06-01",
        },
    )
    if status >= 400:
        raise ReportAssistantError(f"Anthropic request failed ({status}): {raw[:300]}")
    text = "\n".join(
        part.get("text", "").strip()
        for part in (payload or {}).get("content") or []
        if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
    ).strip()
    return _extract_json_text(text)


def _query_gemini(prompt: str) -> dict:
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
        "systemInstruction": {"parts": [{"text": _assistant_prompt(prompt)}]},
    }
    status, raw, data = _post_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{ai_model()}:generateContent?key={ai_api_key()}",
        payload,
        {},
    )
    if status >= 400:
        raise ReportAssistantError(f"Gemini request failed ({status}): {raw[:300]}")
    text = "\n".join(
        part.get("text", "").strip()
        for candidate in (data or {}).get("candidates") or []
        for part in ((candidate.get("content") or {}).get("parts") or [])
        if isinstance(part, dict) and part.get("text")
    ).strip()
    return _extract_json_text(text)


def build_report_query(prompt: str) -> dict:
    if not assistant_enabled():
        raise ReportAssistantError("Default app AI is not configured for report assistant queries yet.")
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        raise ReportAssistantError("Enter a report prompt first.")
    if not _schema_config():
        raise ReportAssistantError("No reportable models are available yet for this app.")
    provider = ai_provider()
    if provider == "openai":
        payload = _query_openai(clean_prompt)
    elif provider == "anthropic":
        payload = _query_anthropic(clean_prompt)
    elif provider == "gemini":
        payload = _query_gemini(clean_prompt)
    else:
        raise ReportAssistantError(f"Unsupported provider: {provider}")
    sql = validate_sql(str((payload or {}).get("sql") or ""))
    return {
        "title": str((payload or {}).get("title") or "AI report").strip()[:120] or "AI report",
        "summary": str((payload or {}).get("summary") or "").strip(),
        "sql": sql,
        "provider": provider,
        "model": ai_model(),
    }


def validate_sql(sql: str) -> str:
    candidate = str(sql or "").strip()
    if not candidate:
        raise ReportAssistantError("The model did not return a SQL query.")
    candidate = candidate.rstrip("; ")
    lowered = candidate.lower()
    if not re.match(r"^(select|with)\b", lowered):
        raise ReportAssistantError("Only SELECT queries are allowed.")
    forbidden = [" insert ", " update ", " delete ", " alter ", " drop ", " create ", " grant ", " revoke ", " truncate ", " copy ", " comment "]
    padded = f" {lowered} "
    if any(token in padded for token in forbidden):
        raise ReportAssistantError("That query includes a blocked SQL operation.")
    table_refs = set(re.findall(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)", lowered))
    allowed_tables = set(_schema_config().keys())
    if not table_refs or not table_refs.issubset(allowed_tables):
        raise ReportAssistantError("The query must only reference the supported reporting tables.")
    limit_match = re.search(r"\blimit\s+(\d+)\b", lowered)
    if limit_match:
        if int(limit_match.group(1)) > 200:
            raise ReportAssistantError("Report queries are limited to 200 rows.")
    else:
        candidate = f"{candidate}\nLIMIT 200"
    return candidate


def _serialize_cell(value):
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def execute_report_sql(sql: str) -> dict:
    safe_sql = validate_sql(sql)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = 5000")
            cursor.execute(safe_sql)
            columns = [col[0] for col in (cursor.description or [])]
            rows = [[_serialize_cell(value) for value in row] for row in cursor.fetchall()]
    return {"columns": columns, "rows": rows, "row_count": len(rows), "sql": safe_sql}


def _normalize_pdf_text(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return text.encode("latin-1", "replace").decode("latin-1")


def _wrap_pdf_line(value, width: int = 100) -> list[str]:
    text = _normalize_pdf_text(value)
    if not text:
        return [""]
    return [text[index:index + width] for index in range(0, len(text), width)]


def _pdf_escape(value) -> str:
    return _normalize_pdf_text(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _simple_pdf_bytes(title: str, columns: list[str], rows: list[list]) -> bytes:
    lines = []
    lines.extend(_wrap_pdf_line(title or "AI report", 90))
    lines.append("")
    header = " | ".join(str(column) for column in columns)
    lines.extend(_wrap_pdf_line(header, 100))
    lines.append("-" * min(len(header), 100))
    for row in rows[:120]:
        lines.extend(_wrap_pdf_line(" | ".join(str(value) for value in row), 100))
    pages = [lines[index:index + 48] for index in range(0, len(lines), 48)] or [["AI report"]]
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    page_numbers = []
    next_object = 4
    for page_lines in pages:
        content_lines = ["BT", "/F1 11 Tf", "14 TL", "1 0 0 1 40 752 Tm"]
        for index, line in enumerate(page_lines):
            content_lines.append(f"({_pdf_escape(line)}) Tj")
            if index != len(page_lines) - 1:
                content_lines.append("T*")
        content_lines.append("ET")
        stream = "\n".join(content_lines)
        page_number = next_object
        content_number = next_object + 1
        page_numbers.append(page_number)
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_number} 0 R >>")
        objects.append(f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream")
        next_object += 2
    kids = " ".join(f"{number} 0 R" for number in page_numbers)
    objects[1] = f"<< /Type /Pages /Count {len(page_numbers)} /Kids [{kids}] >>"
    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(f"{index} 0 obj\n".encode("latin-1"))
        output.write(body.encode("latin-1"))
        output.write(b"\nendobj\n")
    xref_offset = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    output.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode("latin-1"))
    output.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("latin-1"))
    return output.getvalue()


def _excel_xml_cell(value) -> str:
    return f'<Cell><Data ss:Type="String">{html.escape(str(value if value is not None else ""))}</Data></Cell>'


def _simple_excel_bytes(columns: list[str], rows: list[list]) -> bytes:
    xml_rows = ['<Row>' + ''.join(_excel_xml_cell(column) for column in columns) + '</Row>']
    for row in rows:
        xml_rows.append('<Row>' + ''.join(_excel_xml_cell(value) for value in row) + '</Row>')
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<?mso-application progid="Excel.Sheet"?>'
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:o="urn:schemas-microsoft-com:office:office" '
        'xmlns:x="urn:schemas-microsoft-com:office:excel" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        '<Worksheet ss:Name="Report"><Table>'
        + ''.join(xml_rows) +
        '</Table></Worksheet></Workbook>'
    )
    return document.encode('utf-8')


def export_report(file_format: str, title: str, columns: list[str], rows: list[list]):
    file_format = str(file_format or "csv").strip().lower()
    safe_title = re.sub(r"[^a-z0-9]+", "-", (title or "report").lower()).strip("-") or "report"
    if file_format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(columns)
        writer.writerows(rows)
        return buffer.getvalue().encode("utf-8"), "text/csv", f"{safe_title}.csv"
    if file_format == "xlsx":
        try:
            from openpyxl import Workbook
        except ImportError:
            return _simple_excel_bytes(columns, rows), "application/vnd.ms-excel", f"{safe_title}.xls"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Report"
        sheet.append(columns)
        for row in rows:
            sheet.append(list(row))
        output = io.BytesIO()
        workbook.save(output)
        return output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{safe_title}.xlsx"
    if file_format == "pdf":
        return _simple_pdf_bytes(title, columns, rows), "application/pdf", f"{safe_title}.pdf"
    raise ReportAssistantError("Unsupported export format.")
