# Banking agent model boundary

The target banking agent uses LangChain messages over an explicit agentgateway
`/v1/responses` endpoint. LangGraph owns conversation state and the reasoning
loop; gateway protocol conversion and remote tool routing do not constitute a
second autonomous loop. Existing Actor/state services remain responsible for
banking execution and durable effects.

`src/banking_agent/model.py` is an internal model adapter, **not a supported live
banking entry point**. It must not be used for live trials until the gateway
protocol, invocation budget, remote tool authorization and MLflow privacy/audit
gates are integrated. It does not launch or configure an upstream provider.

## Model contract

- The caller supplies the gateway `/v1` base URL, model, credential and canonical
  pinned AgentDojo catalog. There is no default local/direct/paid provider.
- `ChatOpenAI` uses the Responses API with provider state storage disabled. The
  application supplies full message history rather than `previous_response_id`.
- SDK retries are disabled. Any future graph-owned retry must reserve and record
  another attempt before inference; tool effects require status reconciliation,
  not blind retry.
- The adapter preserves the canonical tool schemas, including optional values,
  nulls, defaults, exact decimal strings and public sensitive-field declarations.
  It does not apply OpenAI strict-schema rewriting or execute tools.
- The initial transport is synchronous and non-streaming. Calling `.stream()`
  uses the same guarded non-streaming invocation; asynchronous invocation fails
  before I/O until an equivalent async wire guard is implemented.

The HTTP boundary validates response and item completion **before** LangChain
conversion. The installed LangChain adapter retains response-level status, but
does not retain message-item status in the resulting `AIMessage` text blocks.
Relying only on `AIMessage.text` could therefore misclassify partial output.

The supported initial subset is completed assistant text, structured refusal,
and completed canonical function calls. Partial/error/cancelled responses,
duplicate call/item IDs, invalid arguments, raw tool markup, unknown tools and
provider-hosted tool execution are rejected, even if accompanied by final text.
Function arguments use the existing strict JSON codec and typed catalog: no
duplicate keys, non-finite values, float-to-decimal coercion or guessed repairs.

## Version and capability proof

`src/banking_agent/capabilities.py` compares an explicitly selected gateway
binary's reported version and source revision with `infra/versions.json` and the
reviewed source revision. It only reads version information; it never installs,
upgrades, starts or substitutes a gateway.

The intended gateway route converts a Responses frontend into a custom provider
declaring **Completions only**. Declaring Responses too could select native
passthrough instead. That conversion must be verified against the pinned runtime
with a recording upstream before any inference; a mocked Responses endpoint is
not proof that agentgateway performed conversion or rendered a chat template.

## Offline verification

```bash
uv run --locked python -m pytest tests/test_banking_agent_model.py -q
```

These tests use `httpx.MockTransport`; they consume no model requests and run no
banking tools. They verify actual LangChain request serialization, full-history
call/result pairing, schema and decimal preservation, wire rejection and lack
of SDK retries/fallback.

A separate one-node compiled LangGraph fixture verifies SQLite checkpoint
reopen and **native** MLflow graph/node/model parentage for successful and failed
wire responses. It is a capability fixture, not the final banking graph. With
the locked versions, chat model spans have type `CHAT_MODEL`, not `LLM`.

The tracing tests use isolated temporary SQLite MLflow stores and synthetic,
non-secret content. They do not prove remote gateway/Actor trace propagation,
async isolation, secret redaction or per-trace outcome score coverage. Live
inference remains gated on those separate checks.

Documentation references: [LangChain Responses integration](https://docs.langchain.com/oss/python/integrations/chat/openai),
[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence),
[MLflow LangGraph tracing](https://mlflow.org/docs/latest/genai/tracing/integrations/listing/langgraph),
and [agentgateway custom providers](https://agentgateway.dev/docs/standalone/latest/integrations/llm/providers/custom/).
Version-pinned behavior must be tested rather than inferred from latest docs.
