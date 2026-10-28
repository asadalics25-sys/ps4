# PS4 — Online Coding Judge (Practice Platform)

A Flask + SQLite practice judge with Python 3 and C++17 submissions, hidden test cases, verdicts, submission history, a leaderboard, and an admin problem publisher.

## Features mapped to the assignment

- **Roles:** admin/faculty and participant.
- **Problem statements:** input/output format and public sample input/output.
- **Hidden tests:** only the server-side judge reads expected outputs; test data is never mounted into the submitted program's container.
- **Languages:** Python 3 and C++17.
- **Verdicts:** AC (Accepted), WA (Wrong Answer), TLE (Time Limit Exceeded), RE (Runtime Error), CE (Compilation Error).
- **Status/history:** submission detail page, status JSON endpoint, and personal history (admin can view all).
- **Leaderboard:** solved-problem count, accepted submissions, then fewer submissions.
- **Isolation:** Docker runner uses no network, read-only root filesystem, dropped Linux capabilities, `no-new-privileges`, non-root user, memory/CPU/PID limits, temporary filesystem, source-only read-only bind mount, and a subprocess timeout.
- **Seed content:** 10 built-in problems, each with public sample input/output and additional hidden test cases: Sum of Two Numbers, Maximum of Three, Even or Odd, Factorial, Prime Check, Reverse a String, Count Vowels, Nth Fibonacci Number, Sum of an Array, and Palindrome Number.
- **Resource defaults:** 2 seconds per test, 128 MiB memory. Memory reporting depends on the configured Judge0 provider.

## Quick start (no Docker required)

This version uses the Judge0 code-execution API for sandboxed Python/C++ runs, so Docker does **not** need to be installed on your computer. It does need internet access. The default `https://ce.judge0.com` endpoint may impose availability limits, quotas, or require a different configured provider; consult the [official Judge0 API docs](https://ce.judge0.com/docs) if it returns an HTTP error.

1. Install Python 3.11+.
2. Extract the ZIP, open PowerShell in the `online_coding_judge` folder, then run:

   ```powershell
   python -m pip install -r requirements.txt
   python app.py
   ```

3. Open **http://127.0.0.1:5000**.

If the default Judge0 endpoint is not accessible, configure `JUDGE0_URL` to a Judge0-compatible API endpoint provided by your instructor/host. If that provider requires an API key, set the credentials it documents; do not publish API keys in source code or share them in screenshots.

### Important privacy and security notes

- Source code and test inputs are sent to the configured remote execution provider. Do not send private/proprietary code or confidential data unless you have permission to use that provider.
- Keep hidden expected outputs in your own Flask app; the app submits each test's expected output to Judge0 for comparison, and the remote provider receives that expected output.
- A public demo endpoint is not guaranteed to be available, free, or suitable for a production contest. For reliable operation, use a trusted managed Judge0 provider or your own properly secured execution service.
- Never switch to executing arbitrary submissions directly on the Flask host as a shortcut.

### Demo accounts on first database creation

- Admin: `admin` / `Admin123!`
- Participant: `student` / `Student123!`

Change these for any real use. The demo accounts are only seeded when the database is first created. To reset a local demo database, stop the app, back up any needed data, and remove `data/judge.db`; the next launch recreates it.

## Windows note

Docker-based judging is best run with Docker Desktop using Linux containers, or inside WSL2 with Docker Engine. Make sure the terminal running Flask can call `docker` and can access the Docker daemon. The bind mount passed to Docker must be accessible to the daemon. If a submission reports Docker unavailable, run `docker version` and the image build command above.


## Add a problem

Sign in as admin → **Admin** → publish a problem. Provide a title, statement, input/output format, sample input/output, and test cases as a JSON array, for example:

```json
[
  {"input": "2 3\\n", "output": "5\\n"},
  {"input": "10 -4\\n", "output": "6\\n"},
  {"input": "-7 -8\\n", "output": "-15\\n"}
]
```

The first test is marked as the public sample. Remaining tests are hidden. Do not put confidential tests in the problem statement.

## Architecture

```text
Browser
  │ HTTP
  ▼
Flask web app ─── SQLite (users, problems, tests, submissions)
  │ submission: source + language
  ▼
Judge service
  │ one remote Judge0 submission per test case
  ▼
remote Judge0 runner (Python 3 + g++ / C++17)
  ├── network disabled
  ├── CPU / RAM / PID limits
  ├── non-root, no capabilities
  ├── read-only root; temporary /tmp
  └── only submitted source mounted read-only
  │ stdout compared to expected output (server-side only)
  ▼
Verdict + runtime → submission history / leaderboard
```

## Verdict behavior

- **AC:** all test outputs match expected output after trimming surrounding whitespace.
- **WA:** a program completes but output differs on a test.
- **TLE:** per-test execution exceeds the configured timeout.
- **RE:** program crashes, exceeds resources, or judge infrastructure is unavailable.
- **CE:** C++ compilation fails or source is too large.

## Known limitations / production hardening

- This is a course project / local demo. Synchronous judging means each HTTP submission waits until evaluation finishes; a production version should use a durable job queue (Redis + RQ/Celery), worker concurrency limits, rate limiting, CSRF protection, audit logs, and stronger sandboxing (e.g., gVisor/Firecracker or a managed Judge0/Piston service).
- Remote runtime and memory measurements depend on the configured Judge0 provider.
- Remote queueing and provider overhead can affect latency; treat this as a classroom demo rather than a contest-grade benchmark.
- Output is capped; exact stdout comparison trims outer whitespace only.
- The app binds to `127.0.0.1` by default and should not be exposed directly to the public internet.
- Do not run untrusted code without reviewing and testing the isolation configuration in your environment.
