"""Remote Judge0-backed execution; no local Docker installation required.

Configure JUDGE0_URL (default: https://ce.judge0.com). Some public instances
may require an API key, impose quotas, or disable certain features.
"""
import os
import time
import base64
import requests

JUDGE0_URL = os.environ.get("JUDGE0_URL", "https://ce.judge0.com").rstrip("/")
JUDGE0_API_KEY = os.environ.get("JUDGE0_API_KEY", "")
DOCKER_AVAILABLE = True  # Kept for compatibility with the existing Flask template.
MAX_SOURCE_BYTES = 48 * 1024
MAX_INPUT_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 64 * 1024

LANGUAGE_IDS = {"cpp": 54, "python": 71}  # C++ (GCC 9.2.0), Python 3.8.1 on common Judge0 CE versions.
POLL_INTERVAL = 0.5
POLL_TIMEOUT = 25

def _headers():
    headers = {"Content-Type": "application/json"}
    if JUDGE0_API_KEY:
        # Common RapidAPI configuration. For private instances, adapt this
        # header to the authentication method configured by that provider.
        headers["X-RapidAPI-Key"] = JUDGE0_API_KEY
        host = os.environ.get("JUDGE0_RAPIDAPI_HOST", "")
        if host:
            headers["X-RapidAPI-Host"] = host
    return headers

def _run_case(language, source, input_data, expected_output, time_limit, memory_limit):
    # Judge0 requires Base64 for any submission attributes that may contain
    # characters it cannot safely convert to UTF-8. Encode all text fields.
    encode = lambda value: base64.b64encode(value.encode("utf-8")).decode("ascii")
    payload = {
        "source_code": encode(source),
        "language_id": LANGUAGE_IDS[language],
        "stdin": encode(input_data),
        "expected_output": encode(expected_output),
        "cpu_time_limit": max(1.0, min(float(time_limit), 5.0)),
        "wall_time_limit": max(3.0, min(float(time_limit) + 2.0, 10.0)),
        "memory_limit": max(65536, min(int(memory_limit), 262144)),
        "enable_per_process_and_thread_time_limit": True,
    }
    try:
        response = requests.post(
            f"{JUDGE0_URL}/submissions?base64_encoded=true&wait=false",
            json=payload, headers=_headers(), timeout=10
        )
        if response.status_code >= 400:
            return {"kind": "INFRA", "error": f"Judge0 returned HTTP {response.status_code}: {response.text[:500]}"}
        token = response.json().get("token")
        if not token:
            return {"kind": "INFRA", "error": "Judge0 did not return a submission token."}
        deadline = time.monotonic() + POLL_TIMEOUT
        while time.monotonic() < deadline:
            poll = requests.get(
                f"{JUDGE0_URL}/submissions/{token}?base64_encoded=true&fields=*",
                headers=_headers(), timeout=10
            )
            if poll.status_code >= 400:
                return {"kind": "INFRA", "error": f"Judge0 status request failed (HTTP {poll.status_code}): {poll.text[:500]}"}
            data = poll.json()
            # With base64_encoded=true, textual output fields are Base64 encoded.
            for field in ("stdout", "stderr", "compile_output", "message"):
                value = data.get(field)
                if value:
                    try:
                        data[field] = base64.b64decode(value).decode("utf-8", errors="replace")
                    except (ValueError, TypeError):
                        pass
            status = (data.get("status") or {}).get("description", "")
            if status and status not in ("In Queue", "Processing"):
                return {"kind": "RESULT", "data": data}
            time.sleep(POLL_INTERVAL)
        return {"kind": "TLE", "error": "Timed out waiting for the remote judge response."}
    except requests.RequestException as exc:
        return {"kind": "INFRA", "error": f"Could not reach Judge0: {exc}"}
    except (ValueError, TypeError) as exc:
        return {"kind": "INFRA", "error": f"Invalid response from Judge0: {exc}"}

def judge_submission(language, source, tests, time_limit=2.0, memory_limit=128):
    if language not in LANGUAGE_IDS:
        return {"verdict":"CE", "passed":0, "total":len(tests), "runtime_ms":None, "memory_kb":None,
                "error":"Unsupported language."}
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        return {"verdict":"CE", "passed":0, "total":len(tests), "runtime_ms":None, "memory_kb":None,
                "error":"Source code exceeds the 48 KB limit."}
    passed, runtimes, memories = 0, [], []
    for case in tests:
        inp, expected = str(case["input_data"]), str(case["expected_output"])
        if len(inp.encode("utf-8")) > MAX_INPUT_BYTES:
            return {"verdict":"RE", "passed":passed, "total":len(tests), "runtime_ms":None, "memory_kb":None,
                    "error":"A test input exceeds the configured input limit."}
        result = _run_case(language, source, inp, expected, time_limit, memory_limit)
        if result["kind"] == "INFRA":
            return {"verdict":"JE", "passed":passed, "total":len(tests), "runtime_ms":None, "memory_kb":None,
                    "error":result["error"]}
        if result["kind"] == "TLE":
            return {"verdict":"TLE", "passed":passed, "total":len(tests), "runtime_ms":None, "memory_kb":None,
                    "error":result["error"]}
        data = result["data"]
        status = (data.get("status") or {}).get("description", "")
        runtime = data.get("time")
        memory = data.get("memory")
        if runtime is not None:
            try: runtimes.append(int(float(runtime) * 1000))
            except (ValueError, TypeError): pass
        if memory is not None:
            try: memories.append(int(memory))
            except (ValueError, TypeError): pass
        if status == "Compilation Error":
            return {"verdict":"CE", "passed":0, "total":len(tests), "runtime_ms":max(runtimes, default=0),
                    "memory_kb":max(memories, default=0) or None,
                    "error":(data.get("compile_output") or data.get("stderr") or "Compilation failed.")[:3000]}
        if status == "Time Limit Exceeded":
            return {"verdict":"TLE", "passed":passed, "total":len(tests), "runtime_ms":max(runtimes, default=0),
                    "memory_kb":max(memories, default=0) or None, "error":"Time limit exceeded."}
        if status == "Wrong Answer":
            return {"verdict":"WA", "passed":passed, "total":len(tests), "runtime_ms":max(runtimes, default=0),
                    "memory_kb":max(memories, default=0) or None, "error":None}
        if status in ("Runtime Error (SIGSEGV)", "Runtime Error (NZEC)", "Runtime Error (SIGABRT)",
                      "Runtime Error (SIGFPE)", "Runtime Error (SIGXFSZ)", "Runtime Error (SIGBUS)",
                      "Runtime Error (SIGKILL)", "Runtime Error (SIGPIPE)", "Runtime Error (SIGSYS)",
                      "Internal Error", "Exec Format Error", "File Size Limit Exceeded"):
            return {"verdict":"RE", "passed":passed, "total":len(tests), "runtime_ms":max(runtimes, default=0),
                    "memory_kb":max(memories, default=0) or None,
                    "error":(data.get("stderr") or status or "Runtime error.")[:3000]}
        if status != "Accepted":
            return {"verdict":"RE", "passed":passed, "total":len(tests), "runtime_ms":max(runtimes, default=0),
                    "memory_kb":max(memories, default=0) or None,
                    "error":f"Judge0 result: {status or 'Unknown status'}"}
        # Judge0 compares expected_output server-side; also check output defensively if present.
        output = data.get("stdout")
        if output is not None and output.strip() != expected.strip():
            return {"verdict":"WA", "passed":passed, "total":len(tests), "runtime_ms":max(runtimes, default=0),
                    "memory_kb":max(memories, default=0) or None, "error":None}
        passed += 1
    return {"verdict":"AC", "passed":passed, "total":len(tests), "runtime_ms":max(runtimes, default=0),
            "memory_kb":max(memories, default=0) or None, "error":None}
