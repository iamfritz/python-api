import json
import os
from pathlib import Path

import bcrypt
import jwt
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import sqlite3

load_dotenv()

app = Flask(__name__)
CORS(app)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = (BASE_DIR.parent / "laravel-api" / "database" / "database.sqlite").resolve()
DB_PATH = Path(os.getenv("DB_PATH", str(DEFAULT_DB_PATH))).resolve()
PORT = int(os.getenv("PORT", "5000"))
JWT_SECRET = os.getenv("JWT_SECRET", "laravel-ai-python-secret")


def get_db_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def run(query, params=()):
    conn = get_db_connection()
    try:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def run_one(query, params=()):
    conn = get_db_connection()
    try:
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def run_statement(query, params=()):
    conn = get_db_connection()
    try:
        cursor = conn.execute(query, params)
        conn.commit()
        return {"id": cursor.lastrowid, "changes": cursor.rowcount}
    finally:
        conn.close()


def paginate(items, page=1, per_page=6):
    page = max(1, int(page or 1))
    total = len(items)
    total_pages = max(1, (total + per_page - 1) // per_page)
    start = (page - 1) * per_page
    end = start + per_page

    return {
        "data": items[start:end],
        "current_page": page,
        "last_page": total_pages,
        "total": total,
        "per_page": per_page,
        "next_page_url": f"/blog?page={page + 1}" if page < total_pages else None,
        "prev_page_url": f"/blog?page={page - 1}" if page > 1 else None,
    }


def token_required(fn):
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        token = header.replace("Bearer ", "", 1) if header.startswith("Bearer ") else None

        if not token:
            return jsonify({"message": "Unauthorized"}), 401

        try:
            data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            request.user = data
        except Exception:
            return jsonify({"message": "Invalid token"}), 401

        return fn(*args, **kwargs)

    wrapper.__name__ = fn.__name__
    return wrapper


def require_role(*roles):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            if not getattr(request, "user", None) or request.user.get("role") not in roles:
                return jsonify({"message": "Forbidden"}), 403
            return fn(*args, **kwargs)

        wrapper.__name__ = fn.__name__
        return wrapper

    return decorator


@app.get("/api/site")
def get_site():
    return jsonify({
        "name": "Laravel AI",
        "tagline": "Build faster with a Laravel API and a modern Next.js frontend.",
        "hero": {
            "title": "Launch smarter digital experiences.",
            "subtitle": "A clean architecture for modern web products, content sites, and business dashboards.",
        },
        "features": [
            "Laravel API foundation",
            "Next.js user experience",
            "Content-driven blog pages",
            "Fast setup and clear structure",
        ],
    })


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/api/pages")
def pages():
    try:
        rows = run("SELECT * FROM pages WHERE status = 'published' ORDER BY title ASC")
        results = []
        for page in rows:
            results.append({
                "id": page["id"],
                "title": page["title"],
                "slug": page["slug"],
                "content": page["content"],
                "photo": page["photo"],
                "meta_title": page["meta_title"],
                "meta_description": page["meta_description"],
                "meta_keywords": page["meta_keywords"],
                "meta_fields": json.loads(page["meta_fields"]) if page.get("meta_fields") else None,
            })
        return jsonify(results)
    except Exception as exc:
        return jsonify({"message": "Database error", "error": str(exc)}), 500


@app.get("/api/pages/<slug>")
def single_page(slug):
    try:
        row = run_one("SELECT * FROM pages WHERE slug = ? AND status = 'published' LIMIT 1", (slug,))
        if not row:
            return jsonify({"message": "Page not found"}), 404
        return jsonify({
            "id": row["id"],
            "title": row["title"],
            "slug": row["slug"],
            "content": row["content"],
            "photo": row["photo"],
            "meta_title": row["meta_title"],
            "meta_description": row["meta_description"],
            "meta_keywords": row["meta_keywords"],
            "meta_fields": json.loads(row["meta_fields"]) if row.get("meta_fields") else None,
        })
    except Exception as exc:
        return jsonify({"message": "Database error", "error": str(exc)}), 500


@app.get("/api/blog")
def blog():
    try:
        page = max(1, int(request.args.get("page", 1) or 1))
        rows = run("""
            SELECT bp.*, c.name AS category_name, c.slug AS category_slug
            FROM blog_posts bp
            LEFT JOIN categories c ON c.id = bp.category_id
            WHERE bp.status = 'published'
            ORDER BY bp.created_at DESC
        """)

        mapped = []
        for post in rows:
            mapped.append({
                "id": post["id"],
                "slug": post["slug"],
                "title": post["title"],
                "excerpt": post["excerpt"],
                "photo": post["photo"],
                "published_at": post["created_at"],
                "category": {
                    "id": post["category_id"],
                    "name": post["category_name"],
                    "slug": post["category_slug"],
                } if post.get("category_name") else None,
            })

        paged = paginate(mapped, page, 6)
        return jsonify({
            "data": paged["data"],
            "current_page": paged["current_page"],
            "last_page": paged["last_page"],
            "total": paged["total"],
            "per_page": paged["per_page"],
            "next_page_url": paged["next_page_url"],
            "prev_page_url": paged["prev_page_url"],
        })
    except Exception as exc:
        return jsonify({"message": "Database error", "error": str(exc)}), 500


@app.get("/api/blog/<slug>")
def blog_detail(slug):
    try:
        row = run_one("""
            SELECT bp.*, c.name AS category_name, c.slug AS category_slug
            FROM blog_posts bp
            LEFT JOIN categories c ON c.id = bp.category_id
            WHERE bp.slug = ? AND bp.status = 'published'
            LIMIT 1
        """, (slug,))
        if not row:
            return jsonify({"message": "Post not found"}), 404
        return jsonify({
            "title": row["title"],
            "content": row["content"],
            "photo": row["photo"],
            "category": {
                "id": row["category_id"],
                "name": row["category_name"],
                "slug": row["category_slug"],
            } if row.get("category_name") else None,
        })
    except Exception as exc:
        return jsonify({"message": "Database error", "error": str(exc)}), 500


@app.get("/api/categories")
def categories():
    try:
        rows = run("SELECT id, name, slug FROM categories ORDER BY name ASC")
        return jsonify(rows)
    except Exception as exc:
        return jsonify({"message": "Database error", "error": str(exc)}), 500


@app.get("/api/categories/<slug>/blog")
def category_blog(slug):
    try:
        category = run_one("SELECT id, name, slug FROM categories WHERE slug = ? LIMIT 1", (slug,))
        if not category:
            return jsonify({"message": "Category not found"}), 404

        rows = run("""
            SELECT bp.*, c.name AS category_name, c.slug AS category_slug
            FROM blog_posts bp
            LEFT JOIN categories c ON c.id = bp.category_id
            WHERE bp.category_id = ? AND bp.status = 'published'
            ORDER BY bp.created_at DESC
        """, (category["id"],))

        mapped = []
        for post in rows:
            mapped.append({
                "id": post["id"],
                "slug": post["slug"],
                "title": post["title"],
                "excerpt": post["excerpt"],
                "photo": post["photo"],
                "published_at": post["created_at"],
                "category": {
                    "id": category["id"],
                    "name": category["name"],
                    "slug": category["slug"],
                },
            })

        page = max(1, int(request.args.get("page", 1) or 1))
        paged = paginate(mapped, page, 6)
        return jsonify({
            "category": category,
            "data": paged["data"],
            "current_page": paged["current_page"],
            "last_page": paged["last_page"],
            "total": paged["total"],
            "per_page": paged["per_page"],
            "next_page_url": paged["next_page_url"],
            "prev_page_url": paged["prev_page_url"],
        })
    except Exception as exc:
        return jsonify({"message": "Database error", "error": str(exc)}), 500


@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    email = data.get("email")
    password = data.get("password")
    role = data.get("role", "editor")

    if not name or not email or not password:
        return jsonify({"message": "Name, email and password are required"}), 400

    existing = run_one("SELECT id FROM users WHERE email = ?", (email,))
    if existing:
        return jsonify({"message": "User already exists"}), 409

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    result = run_statement(
        'INSERT INTO users (name, email, password, role, created_at, updated_at) VALUES (?, ?, ?, ?, datetime("now"), datetime("now"))',
        (name, email, hashed, role),
    )
    user = run_one("SELECT id, name, email, role FROM users WHERE id = ?", (result["id"],))
    token = jwt.encode({"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}, JWT_SECRET, algorithm="HS256")
    return jsonify({"user": user, "token": token}), 201


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"message": "Email and password are required"}), 400

    user = run_one("SELECT * FROM users WHERE email = ?", (email,))
    if not user:
        return jsonify({"message": "Invalid credentials"}), 401

    if not bcrypt.checkpw(password.encode("utf-8"), user["password"].encode("utf-8")):
        return jsonify({"message": "Invalid credentials"}), 401

    token = jwt.encode({"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}, JWT_SECRET, algorithm="HS256")
    return jsonify({
        "user": {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]},
        "token": token,
    })


@app.get("/api/user")
@token_required
def api_user():
    return jsonify({"user": request.user})


@app.get("/api/posts")
@token_required
@require_role("admin", "editor")
def posts():
    try:
        rows = run("""
            SELECT bp.*, u.name AS author_name
            FROM blog_posts bp
            LEFT JOIN users u ON u.id = bp.user_id
            ORDER BY bp.id DESC
        """)
        return jsonify([
            {
                "id": post["id"],
                "title": post["title"],
                "slug": post["slug"],
                "excerpt": post["excerpt"],
                "content": post["content"],
                "photo": post["photo"],
                "status": post["status"],
                "author": post["author_name"],
                "created_at": post["created_at"],
            }
            for post in rows
        ])
    except Exception as exc:
        return jsonify({"message": "Database error", "error": str(exc)}), 500


@app.post("/api/posts")
@token_required
@require_role("admin", "editor")
def create_post():
    data = request.get_json(silent=True) or {}
    title = data.get("title")
    slug = data.get("slug")
    content = data.get("content")

    if not title or not slug or not content:
        return jsonify({"message": "Title, slug and content are required"}), 400

    existing = run_one("SELECT id FROM blog_posts WHERE slug = ?", (slug,))
    if existing:
        return jsonify({"message": "Slug already exists"}), 409

    result = run_statement(
        'INSERT INTO blog_posts (user_id, title, slug, excerpt, content, photo, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, datetime("now"), datetime("now"))',
        (request.user["id"], title, slug, data.get("excerpt", ""), content, data.get("photo"), data.get("status", "draft")),
    )
    post = run_one("SELECT * FROM blog_posts WHERE id = ?", (result["id"],))
    return jsonify(post), 201


@app.get("/api/pages-admin")
@token_required
@require_role("admin", "editor")
def pages_admin():
    try:
        rows = run("SELECT * FROM pages ORDER BY id ASC")
        return jsonify(rows)
    except Exception as exc:
        return jsonify({"message": "Database error", "error": str(exc)}), 500


@app.post("/api/pages-admin")
@token_required
@require_role("admin", "editor")
def create_page():
    data = request.get_json(silent=True) or {}
    title = data.get("title")
    slug = data.get("slug")

    if not title or not slug:
        return jsonify({"message": "Title and slug are required"}), 400

    existing = run_one("SELECT id FROM pages WHERE slug = ?", (slug,))
    if existing:
        return jsonify({"message": "Slug already exists"}), 409

    result = run_statement(
        'INSERT INTO pages (title, slug, content, photo, status, meta_title, meta_description, meta_keywords, meta_fields, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime("now"), datetime("now"))',
        (
            title,
            slug,
            data.get("content"),
            data.get("photo"),
            data.get("status", "draft"),
            data.get("meta_title"),
            data.get("meta_description"),
            data.get("meta_keywords"),
            json.dumps(data.get("meta_fields")) if data.get("meta_fields") is not None else None,
        ),
    )
    page = run_one("SELECT * FROM pages WHERE id = ?", (result["id"],))
    return jsonify(page), 201


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, debug=True)
