# Dummy Instructions File (Test Only)

This file is used internally by the model availability test to verify that
the LLM provider can process instructions + image input correctly.

It mirrors the structure of the actual TradingView analysis instructions
but is intentionally minimal for fast API probing.

## Instructions

Analyze the provided image. Respond with valid JSON containing a "summary" field.

## JSON Schema

{"type": "object", "properties": {"summary": {"type": "string"}}}
