"""Regression tests for static asset integrity.

Ensures that every DOM id referenced by JavaScript in app.js exists
exactly once in index.html, and that no id is duplicated.
"""

import os
import re
from collections import Counter
from html.parser import HTMLParser

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML_PATH = os.path.join(PROJECT_ROOT, "static", "index.html")
JS_PATH = os.path.join(PROJECT_ROOT, "static", "app.js")

OPTIONAL_IDS = {
    "kpi-next-cycle",
    "kpi-confidence",
    "kpi-pnl",
    "kpi-positions",
    "kpi-trend",
    "kpi-countdown",
}


class IDCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "id":
                self.ids.append(value)


def _extract_html_ids(path):
    with open(path, encoding="utf-8") as f:
        content = f.read()
    parser = IDCollector()
    parser.feed(content)
    return parser.ids


def _extract_js_get_element_by_id(path):
    with open(path, encoding="utf-8") as f:
        content = f.read()
    matches = re.findall(r'document\.getElementById\("([^"]+)"\)', content)
    return set(matches)


def _extract_js_query_selector_ids(path):
    with open(path, encoding="utf-8") as f:
        content = f.read()
    matches = re.findall(r'querySelector\("#([^"]+)"\)', content)
    ids = set()
    for m in matches:
        id_part = m.split()[0]
        ids.add(id_part)
    return ids


class TestHTMLIDs:
    def test_no_duplicate_ids(self):
        ids = _extract_html_ids(HTML_PATH)
        counts = Counter(ids)
        duplicates = {id_: count for id_, count in counts.items() if count > 1}
        assert not duplicates, f"Duplicate IDs found in index.html: {duplicates}"

    def test_all_get_element_by_id_refs_exist(self):
        html_ids = set(_extract_html_ids(HTML_PATH))
        js_refs = _extract_js_get_element_by_id(JS_PATH)
        missing = js_refs - html_ids - OPTIONAL_IDS
        assert not missing, f"IDs referenced in app.js but missing from index.html: {missing}"

    def test_all_query_selector_id_refs_exist(self):
        html_ids = set(_extract_html_ids(HTML_PATH))
        js_refs = _extract_js_query_selector_ids(JS_PATH)
        missing = js_refs - html_ids - OPTIONAL_IDS
        assert not missing, f"IDs referenced via querySelector in app.js but missing from index.html: {missing}"

    def test_log_element_exists(self):
        html_ids = set(_extract_html_ids(HTML_PATH))
        assert "log" in html_ids, "Missing #log element required by app.js log()"

    def test_history_table_id_not_duplicated(self):
        ids = _extract_html_ids(HTML_PATH)
        counts = Counter(ids)
        assert counts.get("history-table", 0) == 1, (
            "id='history-table' must appear exactly once (dedicated History page); "
            "the Dashboard summary table must use a different id"
        )


class TestModelResponseRendering:
    def test_ollama_response_not_set_via_text_content(self):
        """Regression: cycle_start must not use ollamaResponseEl.textContent
        (which destroys the .ollama-summary child) — that caused
        showOllamaResponse to crash and the catch block to render [object Object]."""
        with open(JS_PATH, encoding="utf-8") as f:
            content = f.read()
        assert "ollamaResponseEl.textContent" not in content, (
            "ollamaResponseEl.textContent assignment destroys child elements; "
            "update .ollama-summary directly instead"
        )

    def test_model_response_catch_does_not_use_string_cast(self):
        """Regression: the model_response catch block must not use
        String(payload.response) which renders '[object Object]' for dicts."""
        with open(JS_PATH, encoding="utf-8") as f:
            content = f.read()
        assert "String(payload.response)" not in content, (
            "String(payload.response) renders '[object Object]' for non-string "
            "payloads; use JSON.stringify instead"
        )