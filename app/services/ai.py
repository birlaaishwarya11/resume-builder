"""
Unified LLM abstraction layer.

Supported providers: anthropic, openai, gemini
"""

import json
import re

# Per-call output cap. Bounds cost on every provider so a hostile rules file
# or a runaway agent loop cannot drain the user's key. Anthropic requires
# max_tokens; OpenAI and Gemini accept it but did not enforce one previously.
MAX_OUTPUT_TOKENS = 4000


def call_llm(provider: str, api_key: str, system_prompt: str,
             user_message: str, model: str | None = None) -> str:
    """Call a supported LLM provider and return the text response.

    Args:
        provider:      One of 'anthropic', 'openai', 'gemini'.
        api_key:       Provider API key.
        system_prompt: System/instruction context.
        user_message:  The user-facing content.
        model:         Optional model override.

    Returns:
        Raw text response from the model.
    """
    provider = (provider or '').strip().lower()
    raw_key = (api_key or '').strip()
    model = (model or '').strip() or None

    # Support custom endpoint: "API_KEY|https://base-url"
    base_url = None
    if '|' in raw_key:
        api_key, base_url = raw_key.split('|', 1)
        api_key = api_key.strip()
        base_url = base_url.strip()
    else:
        api_key = raw_key

    if not api_key:
        raise ValueError('API key is empty. Please provide a valid key.')

    if provider == 'anthropic':
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        model_name = model or 'claude-3-haiku-20240307'
        message = client.messages.create(
            model=model_name,
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0,
            system=system_prompt,
            messages=[{'role': 'user', 'content': user_message}],
        )
        return message.content[0].text

    elif provider == 'openai':
        import openai
        client = openai.OpenAI(api_key=api_key, **({'base_url': base_url} if base_url else {}))
        model_name = model or 'gpt-3.5-turbo'
        completion = client.chat.completions.create(
            model=model_name,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_message},
            ],
            temperature=0,
            max_tokens=MAX_OUTPUT_TOKENS,
        )
        return completion.choices[0].message.content

    elif provider == 'gemini':
        import google.genai as genai
        from google.genai import types
        http_opts = {'api_version': 'v1beta'}
        if base_url:
            http_opts['base_url'] = base_url
        client = genai.Client(api_key=api_key, http_options=http_opts)
        model_name = model or 'gemini-2.0-flash'
        content = (system_prompt + '\n\n' + user_message) if system_prompt else user_message
        response = client.models.generate_content(
            model=model_name,
            contents=content,
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
        )
        result = response.text
        if result is None:
            raise ValueError(
                'Gemini returned an empty response (may have been blocked by safety filters)'
            )
        return result

    raise ValueError(f"Unknown provider: {provider!r}. Must be 'anthropic', 'openai', or 'gemini'.")


def extract_ai_error(exc) -> dict:
    """Extract a user-facing error message and HTTP status code from an AI provider exception."""
    msg = str(exc)
    status_code = None
    if hasattr(exc, 'status_code'):
        status_code = exc.status_code
    elif hasattr(exc, 'code'):
        status_code = exc.code
    else:
        m = re.match(r'^(\d{3})\b', msg.strip())
        if m:
            status_code = int(m.group(1))
    short = msg.splitlines()[0][:300]
    return {'message': short, 'status_code': status_code}


def parse_json_response(response_text: str):
    """Parse JSON out of an LLM response that may have markdown fences or prose."""
    text = response_text.replace('```json', '').replace('```', '').strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for pattern in (r'\{.*\}', r'\[.*\]'):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return {}
