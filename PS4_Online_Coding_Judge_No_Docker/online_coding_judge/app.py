import os, sqlite3, json, secrets, time
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash
from judge import judge_submission, DOCKER_AVAILABLE

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("JUDGE_DB", os.path.join(APP_DIR, "data", "judge.db"))
SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-secret-before-deployment")
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'participant',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS problems (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, slug TEXT UNIQUE NOT NULL,
            statement TEXT NOT NULL, input_format TEXT NOT NULL, output_format TEXT NOT NULL,
            sample_input TEXT NOT NULL, sample_output TEXT NOT NULL,
            time_limit REAL NOT NULL DEFAULT 2.0, memory_limit INTEGER NOT NULL DEFAULT 128,
            is_published INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS test_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, problem_id INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
            input_data TEXT NOT NULL, expected_output TEXT NOT NULL, is_sample INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
            problem_id INTEGER NOT NULL REFERENCES problems(id), language TEXT NOT NULL,
            source_code TEXT NOT NULL, status TEXT NOT NULL, verdict TEXT NOT NULL DEFAULT 'QUEUED',
            passed INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
            runtime_ms INTEGER, memory_kb INTEGER, error_message TEXT, created_at TEXT NOT NULL,
            finished_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_submissions_user ON submissions(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status);
        """)
        if not con.execute("SELECT id FROM users WHERE username='admin'").fetchone():
            con.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
                        ("admin", generate_password_hash(os.environ.get("ADMIN_PASSWORD", "Admin123!")), "admin", now()))
        if not con.execute("SELECT id FROM users WHERE username='student'").fetchone():
            con.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
                        ("student", generate_password_hash("Student123!"), "participant", now()))
        if not con.execute("SELECT id FROM problems LIMIT 1").fetchone():
            seed_problem(con, "Sum of Two Numbers", "sum-two-numbers",
                "Read two integers and print their sum.", "Two integers a and b separated by whitespace.",
                "Print a single integer: a + b.", "2 3\n", "5\n",
                [("2 3\n","5\n"),("10 -4\n","6\n"),("0 0\n","0\n"),("-7 -8\n","-15\n")])
            seed_problem(con, "Maximum of Three", "maximum-of-three",
                "Read three integers and print the largest value.", "Three integers a, b and c.",
                "Print the maximum of the three integers.", "4 9 2\n", "9\n",
                [("4 9 2\n","9\n"),("1 1 1\n","1\n"),("-5 -2 -9\n","-2\n"),("100 20 99\n","100\n")])


        seed_extra_problems(con)

def now():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def seed_problem(con, title, slug, statement, infmt, outfmt, sin, sout, tests):
    cur = con.execute("""INSERT INTO problems(title,slug,statement,input_format,output_format,sample_input,sample_output,time_limit,memory_limit,is_published,created_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                      (title, slug, statement, infmt, outfmt, sin, sout, 2.0, 128, 1, now()))
    pid = cur.lastrowid
    for i, (inp, out) in enumerate(tests):
        con.execute("INSERT INTO test_cases(problem_id,input_data,expected_output,is_sample) VALUES(?,?,?,?)",
                    (pid, inp, out, 1 if i == 0 else 0))


def seed_extra_problems(con):
    """Add the built-in practice set once, without duplicating existing problems."""
    problems = [
        ("Even or Odd", "even-or-odd",
         "Read an integer N. Print Even if N is divisible by 2; otherwise print Odd.",
         "One integer N.", "Print exactly Even or Odd.",
         "7\n", "Odd\n",
         [("7\n","Odd\n"),("12\n","Even\n"),("0\n","Even\n"),("-3\n","Odd\n"),("-8\n","Even\n")]),
        ("Factorial", "factorial",
         "Given a non-negative integer N, print N factorial. N will be between 0 and 20.",
         "One integer N.", "Print N! as an integer.",
         "5\n", "120\n",
         [("5\n","120\n"),("0\n","1\n"),("1\n","1\n"),("10\n","3628800\n"),("20\n","2432902008176640000\n")]),
        ("Prime Check", "prime-check",
         "Read an integer N. Print Yes if N is prime, otherwise print No. Values may be as large as 10^9.",
         "One integer N.", "Print Yes or No.",
         "17\n", "Yes\n",
         [("17\n","Yes\n"),("1\n","No\n"),("2\n","Yes\n"),("49\n","No\n"),("1000000007\n","Yes\n"),("-5\n","No\n")]),
        ("Reverse a String", "reverse-string",
         "Read one line of text and print its characters in reverse order. Spaces are part of the text.",
         "One line of text.", "Print the reversed line.",
         "hello\n", "olleh\n",
         [("hello\n","olleh\n"),("coding judge\n","egduj gnidoc\n"),("a\n","a\n"),("12345\n","54321\n"),("\n","\n")]),
        ("Count Vowels", "count-vowels",
         "Read one line and count the vowels a, e, i, o, u in it, case-insensitively.",
         "One line of text.", "Print the number of vowels.",
         "Online Judge\n", "5\n",
         [("Online Judge\n","5\n"),("AEIOU\n","5\n"),("rhythm\n","0\n"),("Hello World\n","3\n"),("Programming\n","3\n")]),
        ("Nth Fibonacci Number", "nth-fibonacci",
         "Given N, print the Nth Fibonacci number using F(0)=0 and F(1)=1. N is between 0 and 90.",
         "One integer N.", "Print F(N).",
         "7\n", "13\n",
         [("7\n","13\n"),("0\n","0\n"),("1\n","1\n"),("10\n","55\n"),("20\n","6765\n"),("90\n","2880067194370816120\n")]),
        ("Sum of an Array", "sum-of-array",
         "Read N followed by N integers. Print their sum. N is at least 1 and at most 1000.",
         "First integer N, then N integers separated by whitespace.", "Print one integer: the sum.",
         "5\n1 2 3 4 5\n", "15\n",
         [("5\n1 2 3 4 5\n","15\n"),("1\n-9\n","-9\n"),("4\n10 -2 7 5\n","20\n"),("3\n0 0 0\n","0\n"),("6\n100000 -100000 4 5 6 7\n","22\n")]),
        ("Palindrome Number", "palindrome-number",
         "Read a non-negative integer N. Print Yes if its decimal representation reads the same forward and backward; otherwise print No.",
         "One non-negative integer N.", "Print Yes or No.",
         "121\n", "Yes\n",
         [("121\n","Yes\n"),("123\n","No\n"),("7\n","Yes\n"),("10\n","No\n"),("0\n","Yes\n"),("1221\n","Yes\n")]),
    ]
    for title, slug, statement, infmt, outfmt, sin, sout, tests in problems:
        if not con.execute("SELECT id FROM problems WHERE slug=?", (slug,)).fetchone():
            seed_problem(con, title, slug, statement, infmt, outfmt, sin, sout, tests)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapper

@app.context_processor
def inject_globals():
    return {"current_user": session.get("username"), "current_role": session.get("role"),
            "docker_available": DOCKER_AVAILABLE}

@app.route("/")
def index():
    with db() as con:
        problems = con.execute("SELECT * FROM problems WHERE is_published=1 ORDER BY id").fetchall()
        stats = {
            "problems": con.execute("SELECT COUNT(*) FROM problems WHERE is_published=1").fetchone()[0],
            "submissions": con.execute("SELECT COUNT(*) FROM submissions").fetchone()[0],
            "users": con.execute("SELECT COUNT(*) FROM users WHERE role='participant'").fetchone()[0]
        }
    return render_template("index.html", problems=problems, stats=stats)

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        if len(username) < 3 or len(username) > 30 or not username.replace("_","").isalnum():
            flash("Username must be 3–30 characters (letters, numbers or underscores).", "error")
        elif len(password) < 8:
            flash("Password must contain at least 8 characters.", "error")
        else:
            try:
                with db() as con:
                    con.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
                                (username, generate_password_hash(password), "participant", now()))
                flash("Account created. You can now sign in.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("That username is already taken.", "error")
    return render_template("auth.html", mode="register")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        with db() as con:
            user = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"], session["username"], session["role"] = user["id"], user["username"], user["role"]
            return redirect(request.args.get("next") or url_for("index"))
        flash("Invalid username or password.", "error")
    return render_template("auth.html", mode="login")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/problem/<int:problem_id>")
def problem(problem_id):
    with db() as con:
        p = con.execute("SELECT * FROM problems WHERE id=? AND is_published=1", (problem_id,)).fetchone()
        if not p: abort(404)
        samples = con.execute("SELECT input_data,expected_output FROM test_cases WHERE problem_id=? AND is_sample=1", (problem_id,)).fetchall()
        previous = []
        if session.get("user_id"):
            previous = con.execute("""SELECT id,language,verdict,passed,total,created_at FROM submissions
                                      WHERE user_id=? AND problem_id=? ORDER BY id DESC LIMIT 8""",
                                    (session["user_id"], problem_id)).fetchall()
    return render_template("problem.html", p=p, samples=samples, previous=previous)

@app.route("/submit/<int:problem_id>", methods=["POST"])
@login_required
def submit(problem_id):
    language = request.form.get("language","")
    source = request.form.get("source_code","")
    if language not in ("python", "cpp"):
        flash("Choose Python 3 or C++.", "error")
        return redirect(url_for("problem", problem_id=problem_id))
    if not source.strip():
        flash("Source code cannot be empty.", "error")
        return redirect(url_for("problem", problem_id=problem_id))
    with db() as con:
        p = con.execute("SELECT * FROM problems WHERE id=? AND is_published=1", (problem_id,)).fetchone()
        if not p: abort(404)
        tests = con.execute("SELECT input_data,expected_output FROM test_cases WHERE problem_id=? ORDER BY id", (problem_id,)).fetchall()
        cur = con.execute("""INSERT INTO submissions(user_id,problem_id,language,source_code,status,verdict,total,created_at)
                             VALUES(?,?,?,?,?,?,?,?)""",
                          (session["user_id"], problem_id, language, source, "RUNNING", "RUNNING", len(tests), now()))
        sid = cur.lastrowid
    # Synchronous request gives immediate status updates in the UI; record remains queryable in history.
    try:
        result = judge_submission(language, source, [dict(t) for t in tests], float(p["time_limit"]), int(p["memory_limit"]))
    except Exception as exc:
        result = {"verdict":"RE", "passed":0, "total":len(tests), "runtime_ms":None,
                  "memory_kb":None, "error":"Judge infrastructure error. Check Docker and server logs."}
        app.logger.exception("Judge failed for submission %s", sid)
    with db() as con:
        con.execute("""UPDATE submissions SET status='FINISHED',verdict=?,passed=?,total=?,runtime_ms=?,memory_kb=?,
                       error_message=?,finished_at=? WHERE id=?""",
                    (result["verdict"], result["passed"], result["total"], result.get("runtime_ms"),
                     result.get("memory_kb"), result.get("error"), now(), sid))
    return redirect(url_for("submission_detail", submission_id=sid))

@app.route("/submission/<int:submission_id>")
@login_required
def submission_detail(submission_id):
    with db() as con:
        s = con.execute("""SELECT s.*,p.title,u.username FROM submissions s
                           JOIN problems p ON p.id=s.problem_id JOIN users u ON u.id=s.user_id WHERE s.id=?""",
                        (submission_id,)).fetchone()
        if not s: abort(404)
        if s["user_id"] != session["user_id"] and session.get("role") != "admin": abort(403)
    return render_template("submission.html", s=s)

@app.route("/api/submission/<int:submission_id>")
@login_required
def submission_status(submission_id):
    with db() as con:
        s = con.execute("SELECT id,status,verdict,passed,total,runtime_ms,error_message FROM submissions WHERE id=?", (submission_id,)).fetchone()
        if not s: abort(404)
        owner = con.execute("SELECT user_id FROM submissions WHERE id=?", (submission_id,)).fetchone()[0]
        if owner != session["user_id"] and session.get("role") != "admin": abort(403)
    return jsonify(dict(s))

@app.route("/history")
@login_required
def history():
    with db() as con:
        if session.get("role") == "admin":
            rows = con.execute("""SELECT s.id,s.language,s.verdict,s.passed,s.total,s.created_at,p.title,u.username
                                  FROM submissions s JOIN problems p ON p.id=s.problem_id JOIN users u ON u.id=s.user_id
                                  ORDER BY s.id DESC LIMIT 200""").fetchall()
        else:
            rows = con.execute("""SELECT s.id,s.language,s.verdict,s.passed,s.total,s.created_at,p.title,u.username
                                  FROM submissions s JOIN problems p ON p.id=s.problem_id JOIN users u ON u.id=s.user_id
                                  WHERE s.user_id=? ORDER BY s.id DESC LIMIT 200""", (session["user_id"],)).fetchall()
    return render_template("history.html", rows=rows)

@app.route("/leaderboard")
def leaderboard():
    with db() as con:
        rows = con.execute("""SELECT u.username,
            SUM(CASE WHEN s.verdict='AC' THEN 1 ELSE 0 END) AS accepted,
            COUNT(s.id) AS submissions,
            COUNT(DISTINCT CASE WHEN s.verdict='AC' THEN s.problem_id END) AS solved
            FROM users u LEFT JOIN submissions s ON s.user_id=u.id
            WHERE u.role='participant' GROUP BY u.id
            ORDER BY solved DESC, accepted DESC, submissions ASC, u.username ASC LIMIT 100""").fetchall()
    return render_template("leaderboard.html", rows=rows)

@app.route("/admin")
@login_required
@admin_required
def admin():
    with db() as con:
        problems = con.execute("SELECT * FROM problems ORDER BY id DESC").fetchall()
    return render_template("admin.html", problems=problems)

@app.route("/admin/problem", methods=["POST"])
@login_required
@admin_required
def create_problem():
    title = request.form.get("title","").strip()
    statement = request.form.get("statement","").strip()
    infmt = request.form.get("input_format","").strip()
    outfmt = request.form.get("output_format","").strip()
    sin = request.form.get("sample_input","")
    sout = request.form.get("sample_output","")
    raw_tests = request.form.get("tests_json","").strip()
    try:
        tests = json.loads(raw_tests)
        if not isinstance(tests, list) or not tests or any(not isinstance(t,dict) or "input" not in t or "output" not in t for t in tests):
            raise ValueError()
    except Exception:
        flash("Tests must be a JSON array of objects with input and output fields.", "error")
        return redirect(url_for("admin"))
    if not title or not statement or len(tests) > 200:
        flash("Title, statement, and 1–200 test cases are required.", "error")
        return redirect(url_for("admin"))
    slug = "".join(c.lower() if c.isalnum() else "-" for c in title).strip("-")
    slug = (slug[:70] or "problem") + "-" + secrets.token_hex(3)
    with db() as con:
        cur = con.execute("""INSERT INTO problems(title,slug,statement,input_format,output_format,sample_input,sample_output,time_limit,memory_limit,is_published,created_at)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                          (title,slug,statement,infmt,outfmt,sin,sout,2.0,128,1,now()))
        pid = cur.lastrowid
        for i,t in enumerate(tests):
            con.execute("INSERT INTO test_cases(problem_id,input_data,expected_output,is_sample) VALUES(?,?,?,?)",
                        (pid, str(t["input"]), str(t["output"]), 1 if i == 0 else 0))
    flash("Problem published with hidden tests.", "success")
    return redirect(url_for("admin"))

@app.route("/admin/problem/<int:problem_id>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_problem(problem_id):
    with db() as con:
        con.execute("UPDATE problems SET is_published=1-is_published WHERE id=?", (problem_id,))
    return redirect(url_for("admin"))

@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, message="You do not have permission to view this page."), 403

@app.errorhandler(404)
def missing(e):
    return render_template("error.html", code=404, message="The page or problem was not found."), 404

init_db()
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
