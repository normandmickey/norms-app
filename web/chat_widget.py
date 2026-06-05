import json
import re
from urllib import error, request as urllib_request

from django.apps import apps
from django.conf import settings
from django.db import models
from django.db.models import Q


DEFAULT_MODELS = {
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-3-5-sonnet-latest",
    "gemini": "gemini-2.5-flash",
}

SEARCH_STOPWORDS = {
    "a", "an", "and", "are", "be", "for", "from", "how", "i", "in", "is", "it",
    "me", "of", "on", "or", "our", "show", "that", "the", "to", "what", "where",
    "which", "who", "with", "you",
}

EXCLUDED_MODEL_NAMES = {
    "formfieldmapping", "formtemplate", "notificationrule", "notificationrun",
    "pdffieldmapping", "pdftemplate", "resourcefield",
}

EXCLUDED_MODEL_SUFFIXES = ("attachment", "mapping", "template", "run")


class ChatWidgetError(RuntimeError):
    pass


def widget_enabled() -> bool:
    return bool(
        getattr(settings, "CHAT_WIDGET_ENABLED", False)
        and str(getattr(settings, "CHAT_WIDGET_PROVIDER", "")).strip()
        and str(getattr(settings, "CHAT_WIDGET_API_KEY", "")).strip()
    )


def widget_provider() -> str:
    return str(getattr(settings, "CHAT_WIDGET_PROVIDER", "openai")).strip().lower() or "openai"


def widget_model() -> str:
    configured = str(getattr(settings, "CHAT_WIDGET_MODEL", "")).strip()
    return configured or DEFAULT_MODELS.get(widget_provider(), DEFAULT_MODELS["openai"])


def widget_title() -> str:
    return str(getattr(settings, "CHAT_WIDGET_TITLE", "Chat")).strip() or "Chat"


def widget_welcome_message() -> str:
    return str(getattr(settings, "CHAT_WIDGET_WELCOME_MESSAGE", "Hi — ask me anything.")).strip() or "Hi — ask me anything."


def widget_button_label() -> str:
    return str(getattr(settings, "CHAT_WIDGET_BUTTON_LABEL", "Chat")).strip() or "Chat"


def widget_system_prompt() -> str:
    return str(getattr(settings, "CHAT_WIDGET_SYSTEM_PROMPT", "")).strip()


def normalize_history(history):
    normalized = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        normalized.append({"role": role, "content": content[:4000]})
    return normalized[-12:]


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
        raise ChatWidgetError(f"Provider request failed: {exc.reason}") from exc


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
    return candidates


def _search_terms(question):
    tokens = re.findall(r"[a-z0-9_@.-]+", str(question or "").lower())
    deduped = []
    for token in tokens:
        if len(token) < 2 or token in SEARCH_STOPWORDS or token.isdigit():
            continue
        if token not in deduped:
            deduped.append(token)
    return deduped[:6]


def _searchable_field_names(model):
    field_names = []
    for field in model._meta.get_fields():
        if not getattr(field, "concrete", False) or getattr(field, "many_to_many", False):
            continue
        if isinstance(field, (models.CharField, models.TextField, models.EmailField, models.SlugField)):
            field_names.append(field.name)
    return field_names[:6]


def _serialize_value(value):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _serialize_instance(instance):
    data = {"id": instance.pk}
    for field in instance._meta.get_fields():
        if not getattr(field, "concrete", False) or getattr(field, "many_to_many", False):
            continue
        if getattr(field, "auto_created", False):
            continue
        if isinstance(field, (models.AutoField, models.BigAutoField, models.BinaryField, models.FileField)):
            continue
        value = getattr(instance, field.name, None)
        if value in (None, ""):
            continue
        serialized = _serialize_value(value)
        if isinstance(serialized, str) and len(serialized) > 200:
            serialized = serialized[:197] + "..."
        data[field.name] = serialized
        if len(data) >= 7:
            break
    return data


def _question_targets_model(question, model):
    haystack = str(question or "").lower()
    keywords = {
        model._meta.model_name,
        model._meta.verbose_name.lower(),
        model._meta.verbose_name_plural.lower(),
    }
    return any(keyword and keyword in haystack for keyword in keywords)


def _matches_for_model(model, question, terms):
    queryset = model.objects.all()
    searchable_fields = _searchable_field_names(model)
    targeted = _question_targets_model(question, model)
    if terms and searchable_fields:
        query = Q()
        for term in terms:
            term_query = Q()
            for field_name in searchable_fields:
                term_query |= Q(**{f"{field_name}__icontains": term})
            query |= term_query
        queryset = queryset.filter(query).distinct()
    elif targeted:
        queryset = queryset.order_by(f"-{model._meta.pk.name}")
    else:
        return []
    return [_serialize_instance(item) for item in queryset[:4]]


def build_app_context(question):
    terms = _search_terms(question)
    context = {
        "question_terms": terms,
        "models": [],
    }
    for model in _candidate_models():
        model_context = {
            "name": model._meta.verbose_name_plural.title(),
            "model": model._meta.model_name,
            "total": model.objects.count(),
        }
        matches = _matches_for_model(model, question, terms)
        if matches:
            model_context["matches"] = matches
        context["models"].append(model_context)
    return context


def _context_system_prompt(question):
    context = build_app_context(question)
    return (
        "Use the live app context below to answer questions about the app's internal data. "
        "Prefer the provided context over guessing. If the context is insufficient, say what you could not find.\n\n"
        f"LIVE_APP_CONTEXT = {json.dumps(context, ensure_ascii=False)}"
    )


def _chat_openai(history, message):
    messages = []
    system_parts = []
    if widget_system_prompt():
        system_parts.append(widget_system_prompt())
    system_parts.append(_context_system_prompt(message))
    messages.append({"role": "system", "content": "\n\n".join(system_parts)})
    messages.extend(history)
    messages.append({"role": "user", "content": message})
    status, raw, payload = _post_json(
        "https://api.openai.com/v1/chat/completions",
        {"model": widget_model(), "messages": messages},
        {"Authorization": f"Bearer {settings.CHAT_WIDGET_API_KEY.strip()}"},
    )
    if status >= 400:
        raise ChatWidgetError(f"OpenAI request failed ({status}): {raw[:300]}")
    reply = _extract_openai_text(payload or {})
    if not reply:
        raise ChatWidgetError("OpenAI returned an empty response.")
    return reply


def _chat_anthropic(history, message):
    system_parts = []
    if widget_system_prompt():
        system_parts.append(widget_system_prompt())
    system_parts.append(_context_system_prompt(message))
    status, raw, payload = _post_json(
        "https://api.anthropic.com/v1/messages",
        {
            "model": widget_model(),
            "max_tokens": 700,
            "system": "\n\n".join(system_parts),
            "messages": [
                {"role": item["role"], "content": item["content"]}
                for item in [*history, {"role": "user", "content": message}]
            ],
        },
        {
            "x-api-key": settings.CHAT_WIDGET_API_KEY.strip(),
            "anthropic-version": "2023-06-01",
        },
    )
    if status >= 400:
        raise ChatWidgetError(f"Anthropic request failed ({status}): {raw[:300]}")
    reply = "\n".join(
        part.get("text", "").strip()
        for part in (payload or {}).get("content") or []
        if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
    ).strip()
    if not reply:
        raise ChatWidgetError("Anthropic returned an empty response.")
    return reply


def _chat_gemini(history, message):
    payload = {
        "contents": [
            {
                "role": "model" if item["role"] == "assistant" else "user",
                "parts": [{"text": item["content"]}],
            }
            for item in [*history, {"role": "user", "content": message}]
        ],
    }
    system_parts = []
    if widget_system_prompt():
        system_parts.append(widget_system_prompt())
    system_parts.append(_context_system_prompt(message))
    payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
    status, raw, data = _post_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{widget_model()}:generateContent?key={settings.CHAT_WIDGET_API_KEY.strip()}",
        payload,
        {},
    )
    if status >= 400:
        raise ChatWidgetError(f"Gemini request failed ({status}): {raw[:300]}")
    reply = "\n".join(
        part.get("text", "").strip()
        for candidate in (data or {}).get("candidates") or []
        for part in ((candidate.get("content") or {}).get("parts") or [])
        if isinstance(part, dict) and part.get("text")
    ).strip()
    if not reply:
        raise ChatWidgetError("Gemini returned an empty response.")
    return reply


def chat(message, history):
    if not widget_enabled():
        raise ChatWidgetError("Chat widget is not configured yet.")
    message = str(message or "").strip()
    if not message:
        raise ChatWidgetError("Enter a message first.")
    history = normalize_history(history)
    provider = widget_provider()
    if provider == "openai":
        reply = _chat_openai(history, message)
    elif provider == "anthropic":
        reply = _chat_anthropic(history, message)
    elif provider == "gemini":
        reply = _chat_gemini(history, message)
    else:
        raise ChatWidgetError(f"Unsupported provider: {provider}")
    return {"reply": reply, "provider": provider, "model": widget_model()}


def embed_script(iframe_url, button_label):
    config = json.dumps({"iframeUrl": iframe_url, "buttonLabel": button_label or "Chat"})
    return f"""(() => {{
  const config = {config};
  const currentScript = document.currentScript;
  const position = (currentScript && currentScript.dataset.position) === 'left' ? 'left' : 'right';
  const wrapper = document.createElement('div');
  wrapper.style.position = 'fixed';
  wrapper.style.bottom = '24px';
  wrapper.style[position] = '24px';
  wrapper.style.zIndex = '2147483000';
  wrapper.style.display = 'flex';
  wrapper.style.flexDirection = 'column';
  wrapper.style.alignItems = position === 'left' ? 'flex-start' : 'flex-end';
  wrapper.style.gap = '12px';

  const iframe = document.createElement('iframe');
  iframe.src = config.iframeUrl + (config.iframeUrl.includes('?') ? '&' : '?') + 'embedded=1';
  iframe.title = config.buttonLabel;
  iframe.style.width = 'min(380px, calc(100vw - 32px))';
  iframe.style.height = 'min(640px, calc(100vh - 110px))';
  iframe.style.border = '0';
  iframe.style.borderRadius = '18px';
  iframe.style.boxShadow = '0 20px 60px rgba(0,0,0,0.28)';
  iframe.style.background = '#08101d';
  iframe.style.display = 'none';

  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = config.buttonLabel;
  button.setAttribute('aria-expanded', 'false');
  button.style.border = '0';
  button.style.borderRadius = '999px';
  button.style.padding = '14px 18px';
  button.style.background = 'linear-gradient(135deg, #5ea3ff, #7c5cff)';
  button.style.color = '#fff';
  button.style.font = '700 14px Inter, system-ui, sans-serif';
  button.style.cursor = 'pointer';
  button.style.boxShadow = '0 10px 30px rgba(94,163,255,0.35)';

  button.addEventListener('click', () => {{
    const open = iframe.style.display !== 'none';
    iframe.style.display = open ? 'none' : 'block';
    button.setAttribute('aria-expanded', open ? 'false' : 'true');
  }});

  wrapper.appendChild(iframe);
  wrapper.appendChild(button);
  document.body.appendChild(wrapper);
}})();"""
