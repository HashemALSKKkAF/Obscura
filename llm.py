import re
import time
import logging
import openai
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import providers
from llm_utils import (
    BufferedStreamingHandler,
    _common_llm_params,
    resolve_model_config,
    get_model_choices,
)

# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------
# Number of attempts before giving up on a single LLM chain call.
LLM_MAX_RETRIES = 3
# Base delay (seconds) for exponential back-off: 2s → 4s → 8s
LLM_RETRY_BASE_DELAY = 2

# Exceptions that are safe to retry (transient failures).
# Provider SDKs (anthropic, google.api_core) are imported defensively: if the
# package is missing the entry is simply omitted, so retry coverage scales
# with whichever providers are installed.
_retryable: list = [
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,   # 5xx from OpenAI-compatible providers
]

try:
    import anthropic
    _retryable.extend([
        anthropic.RateLimitError,
        anthropic.APITimeoutError,
        anthropic.APIConnectionError,
        anthropic.InternalServerError,
    ])
except ImportError:
    pass

try:
    from google.api_core import exceptions as _google_exc
    _retryable.extend([
        _google_exc.ResourceExhausted,    # 429
        _google_exc.ServiceUnavailable,   # 503
        _google_exc.DeadlineExceeded,     # 504
        _google_exc.InternalServerError,  # 500
    ])
except ImportError:
    pass

_RETRYABLE_EXCEPTIONS = tuple(_retryable)

# Batch size for the LLM filter step — keeps each prompt well within context limits.
FILTER_BATCH_SIZE = 25


def get_llm(model_choice):
    config = resolve_model_config(model_choice)

    if config is None:
        supported_models = get_model_choices()
        raise ValueError(
            f"Unsupported LLM model: '{model_choice}'. "
            f"Supported models (case-insensitive match) are: {', '.join(supported_models)}"
        )

    llm_class = config["class"]
    model_specific_params = config["constructor_params"]

    # Fresh handler per instance — prevents shared-singleton streaming bugs.
    fresh_handler = BufferedStreamingHandler(buffer_limit=60)
    all_params = {
        **_common_llm_params,
        **model_specific_params,
        "callbacks": [fresh_handler],
    }

    _ensure_credentials(model_choice)

    return llm_class(**all_params)


def _ensure_credentials(model_choice: str) -> None:
    """Raise a clear error if a hosted model is selected without its key.

    Provider knowledge (which env var, display name, cloud-vs-local) comes from
    the registry, so this stays correct as providers are added. Local models
    (Ollama / llama.cpp) have no provider here and therefore need no key.
    """
    provider = providers.provider_for_model(model_choice)
    if provider and provider.is_cloud and not provider.is_configured():
        raise ValueError(
            f"{provider.name} model '{model_choice}' selected but `{provider.env_var}` is not set.\n"
            "Add it to your .env file or export it before running the app."
        )


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------

def _invoke_with_retry(chain, inputs: dict, stage: str = "LLM call"):
    """
    Invoke a LangChain chain with exponential back-off retry on transient errors.

    Retries on: rate limits, timeouts, connection errors, and 5xx responses.
    Propagates immediately on any other exception (e.g. auth failures).

    Args:
        chain:  A LangChain Runnable (prompt | llm | parser).
        inputs: Variables passed to chain.invoke().
        stage:  Human-readable label used in log/warning messages.

    Returns:
        The chain's string output.

    Raises:
        The last retryable exception if all attempts are exhausted.
        Any non-retryable exception on first occurrence.
    """
    last_exc = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            return chain.invoke(inputs)
        except _RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            if attempt >= LLM_MAX_RETRIES:
                # Out of attempts — raise immediately rather than sleeping.
                break
            delay = LLM_RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logging.warning(
                "[%s] attempt %d/%d failed (%s: %s) — retrying in %.0fs",
                stage, attempt, LLM_MAX_RETRIES,
                type(exc).__name__, str(exc)[:120], delay,
            )
            time.sleep(delay)
        except Exception:
            raise   # Auth errors, bad requests, etc. — don't retry
    raise last_exc


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def refine_query(llm, user_input):
    system_prompt = """
    You are a Cybercrime Threat Intelligence Expert. Your task is to refine the provided user query that needs to be sent to darkweb search engines. 
    
    Rules:
    1. Analyze the user query and think about how it can be improved to use as search engine query
    2. Refine the user query by adding or removing words so that it returns the best result from dark web search engines
    3. Don't use any logical operators (AND, OR, etc.)
    4. Keep the final refined query limited to 5 words or less
    5. Output just the user query and nothing else

    INPUT:
    """
    prompt_template = ChatPromptTemplate(
        [("system", system_prompt), ("user", "{query}")]
    )
    chain = prompt_template | llm | StrOutputParser()
    refined = _invoke_with_retry(chain, {"query": user_input}, stage="refine_query")
    return _clean_refined_query(refined, fallback=user_input)


def _clean_refined_query(refined: str, fallback: str = "") -> str:
    """Normalise the model's refined query before it hits a search URL.

    Models routinely wrap the answer in newlines, quotes, or a 'Query:' preamble.
    Left raw, those characters get URL-encoded into every engine request
    (e.g. ``%0A%0Aransomware``), which degrades or breaks results. We collapse
    whitespace, strip wrapping quotes/labels, and fall back to the user's
    original query if the model returned nothing usable.
    """
    text = " ".join((refined or "").split())          # collapse all whitespace
    text = re.sub(r'^(refined query|query|output)\s*[:\-]\s*', "", text, flags=re.IGNORECASE)
    text = text.strip().strip('"').strip("'").strip()
    return text or " ".join((fallback or "").split())


def _filter_batch(llm, query: str, batch: list, batch_offset: int) -> list:
    """
    Ask the LLM to select the most relevant indices from a single batch.

    The batch is a slice of the original results list. batch_offset is the
    number of items before this slice, used to convert local (1-based within
    the batch) indices back to global (1-based across all results) indices.

    Returns a list of global 1-based indices.
    """
    system_prompt = """
    You are a Cybercrime Threat Intelligence Expert. You are given a dark web search query and a list of search results in the form of index, link and title. 
    Your task is to select the Top 10 relevant results that best match the search query for further investigation.
    Rule:
    1. Output ONLY the indices (comma-separated list), no more than 10, that best match the input query.

    Search Query: {query}
    Search Results:
    """
    final_str = _generate_final_string(batch)
    prompt_template = ChatPromptTemplate(
        [("system", system_prompt), ("user", "{results}")]
    )
    chain = prompt_template | llm | StrOutputParser()

    try:
        raw = _invoke_with_retry(chain, {"query": query, "results": final_str}, stage="filter_batch")
    except openai.RateLimitError:
        # Last-resort fallback: truncated titles only to minimise token use.
        final_str = _generate_final_string(batch, truncate=True)
        raw = _invoke_with_retry(
            chain, {"query": query, "results": final_str}, stage="filter_batch_truncated"
        )

    # Parse local indices (1-based within this batch) and convert to global.
    parsed = []
    for match in re.findall(r"\d+", raw):
        try:
            local_idx = int(match)
            if 1 <= local_idx <= len(batch):
                global_idx = batch_offset + local_idx  # 1-based global
                parsed.append(global_idx)
        except ValueError:
            continue

    return parsed


def filter_results(llm, query: str, results: list) -> list:
    """
    Filter search results down to the top 20 most relevant entries.

    Results are processed in batches of FILTER_BATCH_SIZE (default 25) so that
    each LLM prompt stays well within context limits. Each batch independently
    selects up to 10 candidates; the combined candidates are de-duplicated and
    capped at 20.
    """
    if not results:
        return []

    all_selected_indices = []

    for batch_start in range(0, len(results), FILTER_BATCH_SIZE):
        batch = results[batch_start: batch_start + FILTER_BATCH_SIZE]
        selected = _filter_batch(llm, query, batch, batch_offset=batch_start)
        all_selected_indices.extend(selected)

    # De-duplicate while preserving order.
    seen: set = set()
    unique_indices = [i for i in all_selected_indices if not (i in seen or seen.add(i))]

    if not unique_indices:
        num_batches = (len(results) + FILTER_BATCH_SIZE - 1) // FILTER_BATCH_SIZE
        logging.warning(
            "filter_results: LLM returned no usable indices across %d batch(es). "
            "Defaulting to top %d results.",
            num_batches,
            min(len(results), 20),
        )
        unique_indices = list(range(1, min(len(results), 20) + 1))

    # Cap at 20 and convert to 0-based for list indexing.
    return [results[i - 1] for i in unique_indices[:20]]


def _generate_final_string(results, truncate=False):
    """Generate a formatted string from search results for LLM processing."""
    final_str = []
    for i, res in enumerate(results):
        truncated_link = re.sub(r"(?<=\.onion).*", "", res["link"])
        title = re.sub(r"[^0-9a-zA-Z\-\.]", " ", res["title"])
        if truncated_link == "" and title == "":
            continue

        if truncate:
            max_title_length = 30
            title = (title[:max_title_length] + "..." if len(title) > max_title_length else title)
            truncated_link = ""

        final_str.append(f"{i+1}. {truncated_link} - {title}")

    return "\n".join(s for s in final_str)


PRESET_PROMPTS = {
    "threat_intel": """
    You are an Cybercrime Threat Intelligence Expert tasked with generating a professional, structured investigative report from dark web OSINT data.

    Rules:
    1. Analyze the Darkweb OSINT data provided (links and raw text).
    2. Maintain a professional cyber threat-intelligence tone throughout.
    3. Use markdown table formatting exactly as specified in the Output Format.
    4. Do NOT simplify or merge table columns.
    5. Always provide a concise intelligence-style description for every source URL.
    6. Include separators (---) between every section.
    7. Ignore not safe for work texts from the analysis.
    8. Add a footer with explanatory notes and disclaimers regarding data verification.

    Output Format:

    1. Input Query: {query}
    ---
    2. Source Links Referenced for Analysis
    | # | URL (onion) | Brief Description |
    |---|---|---|
    (Provide 1-2 professional sentences per URL explaining content, relevance, and threat type)
    ---
    3. Investigation Artifacts
    | Artifact Type | Value / Indicator | Context from Source |
    |---|---|---|
    (Include: names, emails, crypto addresses, domains, markets, threat actors, malware family, TTPs, etc.)
    ---
    4. Key Insights
    | # | Insight | Why it matters |
    |---|---|---|
    (3-5 specific, data-driven insights)
    ---
    5. Solutions & Defensive Recommendations
    | Threat / Risk | Recommended Solution | Implementation Details | Security Benefit |
    |---|---|---|---|
    (Actionable, enterprise-focused security recommendations)
    ---
    6. Next Steps
    | Action | Suggested Query / Method |
    |---|---|
    (Specific investigative steps to pivot or expand findings)
    ---
    *Disclaimer: OBSCURA provides automated OSINT insights. All critical findings must be manually verified. This report is for lawful investigative purposes only.*

    INPUT:
    """,
    "ransomware_malware": """
    You are a Malware and Ransomware Intelligence Expert tasked with generating a professional, structured threat analysis report from dark web data.

    Rules:
    1. Analyze the Darkweb OSINT data provided, focusing on ransomware groups, malware families, and attack infrastructure.
    2. Maintain a professional cyber threat-intelligence tone throughout.
    3. Use markdown table formatting exactly as specified in the Output Format.
    4. Do NOT simplify or merge table columns.
    5. Always provide a concise intelligence-style description for every source URL.
    6. Include separators (---) between every section.
    7. Ignore not safe for work texts from the analysis.
    8. Add a footer with explanatory notes and disclaimers regarding data verification.

    Output Format:

    1. Input Query: {query}
    ---
    2. Source Links Referenced for Analysis
    | # | URL (onion) | Brief Description |
    |---|---|---|
    (Provide 1-2 professional sentences per URL explaining content, relevance, and threat type)
    ---
    3. Investigation Artifacts
    | Artifact Type | Value / Indicator | Context from Source |
    |---|---|---|
    (Focus on: hashes, C2s, staging URLs, TTPs, victim sectors, group aliases)
    ---
    4. Key Insights
    | # | Insight | Why it matters |
    |---|---|---|
    (3-5 specific, malware-focused insights)
    ---
    5. Solutions & Defensive Recommendations
    | Threat / Risk | Recommended Solution | Implementation Details | Security Benefit |
    |---|---|---|---|
    (Focus on: EDR/XDR, YARA/Sigma, backup resilience, containment)
    ---
    6. Next Steps
    | Action | Suggested Query / Method |
    |---|---|
    (Specific hunting queries or malware analysis pivots)
    ---
    *Disclaimer: OBSCURA provides automated OSINT insights. All critical findings must be manually verified. This report is for lawful investigative purposes only.*

    INPUT:
    """,
    "personal_identity": """
    You are a Personal Threat Intelligence Expert tasked with generating a professional identity-exposure report from dark web data.

    Rules:
    1. Analyze the Darkweb OSINT data provided, focusing on PII exposure, breach sources, and marketplace listings.
    2. Maintain a professional cyber threat-intelligence tone throughout.
    3. Use markdown table formatting exactly as specified in the Output Format.
    4. Do NOT simplify or merge table columns.
    5. Always provide a concise intelligence-style description for every source URL.
    6. Include separators (---) between every section.
    7. Ignore not safe for work texts from the analysis. Handle personal data with discretion.
    8. Add a footer with explanatory notes and disclaimers regarding data verification.

    Output Format:

    1. Input Query: {query}
    ---
    2. Source Links Referenced for Analysis
    | # | URL (onion) | Brief Description |
    |---|---|---|
    (Provide 1-2 professional sentences per URL explaining content, relevance, and threat type)
    ---
    3. Investigation Artifacts
    | Artifact Type | Value / Indicator | Context from Source |
    |---|---|---|
    (Include: names, emails, phone numbers, SSNs, financial accounts, breach sources)
    ---
    4. Key Insights
    | # | Insight | Why it matters |
    |---|---|---|
    (3-5 insights on exposure risk and severity)
    ---
    5. Solutions & Defensive Recommendations
    | Threat / Risk | Recommended Solution | Implementation Details | Security Benefit |
    |---|---|---|---|
    (Focus on: MFA, dark-web monitoring, identity hardening, credit freezes)
    ---
    6. Next Steps
    | Action | Suggested Query / Method |
    |---|---|
    (Protective actions or further PII search pivots)
    ---
    *Disclaimer: OBSCURA provides automated OSINT insights. All critical findings must be manually verified. This report is for lawful investigative purposes only.*

    INPUT:
    """,
    "corporate_espionage": """
    You are a Corporate Intelligence Expert tasked with generating a professional corporate risk assessment report from dark web data.

    Rules:
    1. Analyze the Darkweb OSINT data provided, focusing on leaked credentials, source code, internal documents, and corporate targeting.
    2. Maintain a professional cyber threat-intelligence tone throughout.
    3. Use markdown table formatting exactly as specified in the Output Format.
    4. Do NOT simplify or merge table columns.
    5. Always provide a concise intelligence-style description for every source URL.
    6. Include separators (---) between every section.
    7. Ignore not safe for work texts from the analysis.
    8. Add a footer with explanatory notes and disclaimers regarding data verification.

    Output Format:

    1. Input Query: {query}
    ---
    2. Source Links Referenced for Analysis
    | # | URL (onion) | Brief Description |
    |---|---|---|
    (Provide 1-2 professional sentences per URL explaining content, relevance, and threat type)
    ---
    3. Investigation Artifacts
    | Artifact Type | Value / Indicator | Context from Source |
    |---|---|---|
    (Include: internal docs, credentials, database leaks, threat actor activity)
    ---
    4. Key Insights
    | # | Insight | Why it matters |
    |---|---|---|
    (3-5 insights on business impact and risk posture)
    ---
    5. Solutions & Defensive Recommendations
    | Threat / Risk | Recommended Solution | Implementation Details | Security Benefit |
    |---|---|---|---|
    (Focus on: network segmentation, Zero Trust, IR actions, application whitelisting)
    ---
    6. Next Steps
    | Action | Suggested Query / Method |
    |---|---|
    (Legal considerations, IR pivots, or credential monitoring pivots)
    ---
    *Disclaimer: OBSCURA provides automated OSINT insights. All critical findings must be manually verified. This report is for lawful investigative purposes only.*

    INPUT:
    """,
}


def generate_summary(
    llm,
    query,
    content,
    preset: str = "threat_intel",
    custom_instructions: str = "",
    system_prompt_override: str | None = None,
):
    """
    Generate the final investigation summary.

    Resolution order for the system prompt:
      1. `system_prompt_override` (if provided) — used verbatim. This is how
         the UI passes user-defined custom-domain prompts through.
      2. `PRESET_PROMPTS[preset]` — one of the four built-in domains.
      3. `PRESET_PROMPTS["threat_intel"]` — final fallback for unknown keys.
    """
    if system_prompt_override and system_prompt_override.strip():
        system_prompt = system_prompt_override
    else:
        system_prompt = PRESET_PROMPTS.get(preset, PRESET_PROMPTS["threat_intel"])

    if custom_instructions and custom_instructions.strip():
        system_prompt = system_prompt.rstrip() + f"\n\nAdditionally focus on: {custom_instructions.strip()}"
    prompt_template = ChatPromptTemplate(
        [("system", system_prompt), ("user", "{content}")]
    )
    chain = prompt_template | llm | StrOutputParser()
    return _invoke_with_retry(chain, {"query": query, "content": content}, stage="generate_summary")