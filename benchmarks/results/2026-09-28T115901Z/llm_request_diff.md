# Existing request diff

| Field | Status | Standalone | Cascade |
|---|---|---|---|
| api_type | same | `chat.completions` | `chat.completions` |
| model | same | `gpt-5.6-terra` | `gpt-5.6-terra` |
| deployment | same | `None` | `None` |
| requested_service_tier | same | `fast` | `fast` |
| reasoning_effort | same | `None` | `None` |
| effective_reasoning_setting | unobservable | `None` | `None` |
| max_completion_tokens | different | `128` | `512` |
| max_tokens | same | `None` | `None` |
| temperature | same | `None` | `None` |
| top_p | same | `None` | `None` |
| stream | same | `True` | `True` |
| response_format | same | `None` | `None` |
| parallel_tool_calls | same | `None` | `None` |
| tool_choice | same | `None` | `None` |
| tools | same | `[]` | `[]` |
| messages | different | `[{'role': 'system', 'content_sha256': '87143604bc17ef15ea30ef907d01edd6f4e003eb36704c49ced6a4908fc36` | `[{'role': 'system', 'content_sha256': 'ea2c872f635d755232aa7b0d78009413ba6f2de48a89c3bd377a2965598f6` |
| instructions | same | `None` | `None` |
| history_count | same | `0` | `0` |
| metadata | same | `None` | `None` |
| prompt_cache_key | same | `benchmark:benchmark:isolation` | `benchmark:benchmark:isolation` |
| prompt_cache_retention | same | `None` | `None` |
| previous_response_id | same | `None` | `None` |
| timeout | same | `60` | `60` |
| max_retries | same | `0` | `0` |
| extra_header_names | same | `[]` | `[]` |
| prompt_chars | different | `26593` | `26594` |
| prompt_bytes | different | `27488` | `27489` |
| estimated_input_tokens | unobservable | `None` | `None` |
| prompt_sha256 | different | `87143604bc17ef15ea30ef907d01edd6f4e003eb36704c49ced6a4908fc361b8` | `ea2c872f635d755232aa7b0d78009413ba6f2de48a89c3bd377a2965598f6e48` |
| user_sha256 | different | `a450ddd246a3eb6afd368a34143383f6b08d9c7eaed7517eccec3679dce7e0cc` | `1eb9c060620a96fc679614ae8d5b02df0b18e48f460463d49063018f5b041302` |
| tool_schema_count | same | `0` | `0` |
| tool_schema_bytes | same | `2` | `2` |
