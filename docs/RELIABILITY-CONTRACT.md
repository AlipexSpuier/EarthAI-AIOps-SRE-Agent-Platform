# EarthAI reliability work boundaries

Session goal: reduce real model/tool failures using measured read-only live tests, not bypassing approvals or declaring false success. User authorizes configured paid model and configured server tests. Do not mutate production infrastructure. Paid tests are finite, record safe summary only, no raw keys or server-sensitive output.

Files owned by main agent: backend/engine.py, backend/tools.py, new backend/reliability.py, tests/model etc as assigned, live test scripts, documentation and deployment.

Model reliability subagent will own backend/model_client.py + tests/test_model_client.py + new tests/test_model_reliability.py only.
Preferences subagent owns backend/main.py + frontend ChatPage/types/AuthContext + new preference tests/package test wiring.

Key implementation constraints: temporary model failures must retry only the current request, not replay real tool actions; if public reply already emitted retry can issue content reset via callback then replace safely; malformed streamed tool JSON must be fully repaired or regenerated before any real execution. Never execute incomplete/unvalidated tool calls. Unknown tools/errors should be returned as tool feedback with available tool schema, rather than terminate full run; loop limit/circuit breaker. Only retry infrastructure reads automatically if certainly read-only; don't repeat writes after uncertain dispatch. Enforce risk/owner rules on normalized params. Preserve all valid assistant tool-call/result pairs in bounded context, avoid 18k char slicing corrupting JSON.

Existing model API exact `complete(provider,model,messages,*,on_event=None)` returns valid OpenAI message, emits sync callbacks content:{content:cumulative,reset?:bool}; metadata whitelist/notice. Engine wrapper existing 3arg model_completion heavily used test monkeypatch. progress.MODEL_EVENTS ContextVar supplies callback. New request options can be ContextVar in tools or reliability module, but main must know API before calling.
