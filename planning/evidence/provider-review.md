C01/C02 defined before S12 implementation: trace decoded source -> separate instruction/user messages -> POST /v1/responses -> completion/refusal/incomplete/error checks -> schema -> deterministic route. Inspect model/options, redacted evidence, and provider/model success provenance. A fake transport establishes serialization/handling only; no live availability or accuracy claim. Q-49 remains pending for transport-failure provenance acceptance.

Official sources checked 2026-11-15:
- https://developers.openai.com/api/reference/resources/responses/methods/create
- https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses
- https://developers.openai.com/api/docs/models/gpt-4.1-mini

Chosen contract: non-streaming Responses, instructions plus user input, text.format json_schema with strict true. Check response status, error, refusal content and message status before parsing output_text content. Pinned model: gpt-4.1-mini-2025-04-14; configurable endpoint/timeout/output budget. No SDK dependency.
