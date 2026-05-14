import io
import os
import random
import sqlite3
import string
import uuid

import qrcode
from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, send_file, url_for)
from werkzeug.utils import secure_filename
import embeddings as emb

app = Flask(__name__)

_KEY_FILE = os.path.join(os.path.dirname(__file__), ".secret_key")
if os.path.exists(_KEY_FILE):
    with open(_KEY_FILE, "rb") as f:
        app.secret_key = f.read()
else:
    app.secret_key = os.urandom(24)
    with open(_KEY_FILE, "wb") as f:
        f.write(app.secret_key)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
DB_PATH = os.path.join(os.path.dirname(__file__), "inventory.db")
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

os.makedirs(UPLOAD_DIR, exist_ok=True)


# ── Database ─────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            description TEXT,
            photo       TEXT,
            embedding   BLOB,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS locations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            code        TEXT UNIQUE NOT NULL,
            description TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS item_locations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id     INTEGER NOT NULL,
            location_id INTEGER NOT NULL,
            quantity    INTEGER DEFAULT 1,
            added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (item_id)     REFERENCES items(id)     ON DELETE CASCADE,
            FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE CASCADE,
            UNIQUE (item_id, location_id)
        );
    """)
    conn.commit()
    # migrate: add embedding column if missing
    cols = [r[1] for r in conn.execute("PRAGMA table_info(items)").fetchall()]
    if "embedding" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN embedding BLOB")
        conn.commit()
    conn.close()


init_db()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def _make_embedding(photo_filename):
    """Generate embedding blob for a saved photo file, or None if no photo."""
    if not photo_filename:
        return None
    path = os.path.join(UPLOAD_DIR, photo_filename)
    try:
        return emb.to_blob(emb.embed_image_file(path))
    except Exception:
        return None


def _save_photo(file_storage):
    if file_storage and file_storage.filename and _allowed(file_storage.filename):
        ext = file_storage.filename.rsplit(".", 1)[1].lower()
        name = f"{uuid.uuid4().hex}.{ext}"
        file_storage.save(os.path.join(UPLOAD_DIR, name))
        return name
    return None


def _delete_photo(filename):
    if filename:
        path = os.path.join(UPLOAD_DIR, filename)
        if os.path.exists(path):
            os.remove(path)


def _random_code(length=6):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


# ── Routes: dashboard ─────────────────────────────────────────────────────────

@app.route("/")
def index():
    conn = get_db()
    item_count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    loc_count  = conn.execute("SELECT COUNT(*) FROM locations").fetchone()[0]
    recent     = conn.execute("""
        SELECT l.*, COUNT(il.item_id) AS item_count
        FROM locations l LEFT JOIN item_locations il ON l.id = il.location_id
        GROUP BY l.id ORDER BY l.created_at DESC LIMIT 6
    """).fetchall()
    conn.close()
    return render_template("index.html",
                           item_count=item_count, loc_count=loc_count, recent=recent)


# ── Routes: items ─────────────────────────────────────────────────────────────

@app.route("/items")
def items():
    q    = request.args.get("q", "").strip()
    conn = get_db()
    if q:
        rows = conn.execute(
            "SELECT * FROM items WHERE name LIKE ? OR description LIKE ? ORDER BY name",
            (f"%{q}%", f"%{q}%"),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM items ORDER BY name").fetchall()
    conn.close()
    return render_template("items.html", items=rows, q=q)


@app.route("/items/new", methods=["GET", "POST"])
def new_item():
    from_location = request.args.get("from_location") or request.form.get("from_location")
    if request.method == "POST":
        name  = request.form["name"].strip()
        desc  = request.form.get("description", "").strip()
        photo = _save_photo(request.files.get("photo"))
        embedding = _make_embedding(photo)
        conn  = get_db()
        conn.execute("INSERT INTO items (name, description, photo, embedding) VALUES (?,?,?,?)",
                     (name, desc, photo, embedding))
        conn.commit()
        item_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        if from_location:
            conn.execute(
                "INSERT INTO item_locations (item_id, location_id, quantity) VALUES (?,?,1)",
                (item_id, int(from_location)),
            )
            conn.commit()
        conn.close()
        flash("Item created.", "success")
        if from_location:
            return redirect(url_for("location_detail", location_id=int(from_location)))
        return redirect(url_for("items"))
    return render_template("item_form.html", item=None, from_location=from_location)


@app.route("/items/<int:item_id>")
def item_detail(item_id):
    conn = get_db()
    item = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not item:
        abort(404)
    locs = conn.execute("""
        SELECT l.*, il.quantity FROM locations l
        JOIN item_locations il ON l.id = il.location_id
        WHERE il.item_id = ? ORDER BY l.name
    """, (item_id,)).fetchall()
    conn.close()
    return render_template("item_detail.html", item=item, locations=locs)


@app.route("/items/<int:item_id>/edit", methods=["GET", "POST"])
def edit_item(item_id):
    conn = get_db()
    item = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not item:
        abort(404)
    if request.method == "POST":
        name  = request.form["name"].strip()
        desc  = request.form.get("description", "").strip()
        photo = item["photo"]
        new_p = _save_photo(request.files.get("photo"))
        if new_p:
            _delete_photo(photo)
            photo = new_p
        embedding = _make_embedding(photo) if new_p else item["embedding"]
        conn.execute("UPDATE items SET name=?,description=?,photo=?,embedding=? WHERE id=?",
                     (name, desc, photo, embedding, item_id))
        conn.commit()
        conn.close()
        flash("Item updated.", "success")
        return redirect(url_for("item_detail", item_id=item_id))
    conn.close()
    return render_template("item_form.html", item=item)


@app.route("/items/<int:item_id>/delete", methods=["POST"])
def delete_item(item_id):
    conn = get_db()
    item = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if item:
        _delete_photo(item["photo"])
        conn.execute("DELETE FROM items WHERE id=?", (item_id,))
        conn.commit()
    conn.close()
    flash("Item deleted.", "info")
    return redirect(url_for("items"))


# ── Routes: locations ─────────────────────────────────────────────────────────

@app.route("/locations")
def locations():
    q    = request.args.get("q", "").strip()
    conn = get_db()
    base = """
        SELECT l.*, COUNT(il.item_id) AS item_count
        FROM locations l LEFT JOIN item_locations il ON l.id = il.location_id
    """
    if q:
        rows = conn.execute(
            base + " WHERE l.name LIKE ? OR l.code LIKE ? OR l.description LIKE ? GROUP BY l.id ORDER BY l.name",
            (f"%{q}%", f"%{q}%", f"%{q}%"),
        ).fetchall()
    else:
        rows = conn.execute(base + " GROUP BY l.id ORDER BY l.name").fetchall()
    conn.close()
    return render_template("locations.html", locations=rows, q=q)


@app.route("/locations/new", methods=["GET", "POST"])
def new_location():
    if request.method == "POST":
        name = request.form["name"].strip()
        code = request.form["code"].strip().upper()
        desc = request.form.get("description", "").strip()
        conn = get_db()
        try:
            conn.execute("INSERT INTO locations (name, code, description) VALUES (?,?,?)",
                         (name, code, desc))
            conn.commit()
            lid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.close()
            flash("Location created.", "success")
            return redirect(url_for("location_detail", location_id=lid))
        except sqlite3.IntegrityError:
            conn.close()
            flash(f'Code "{code}" is already taken.', "error")
    return render_template("location_form.html", location=None, suggested=_random_code())


@app.route("/locations/<int:location_id>")
def location_detail(location_id):
    conn     = get_db()
    location = conn.execute("SELECT * FROM locations WHERE id=?", (location_id,)).fetchone()
    if not location:
        abort(404)
    items = conn.execute("""
        SELECT i.*, il.quantity FROM items i
        JOIN item_locations il ON i.id = il.item_id
        WHERE il.location_id = ? ORDER BY i.name
    """, (location_id,)).fetchall()
    conn.close()
    return render_template("location_detail.html", location=location, items=items)


@app.route("/locations/<int:location_id>/edit", methods=["GET", "POST"])
def edit_location(location_id):
    conn     = get_db()
    location = conn.execute("SELECT * FROM locations WHERE id=?", (location_id,)).fetchone()
    if not location:
        abort(404)
    if request.method == "POST":
        name = request.form["name"].strip()
        code = request.form["code"].strip().upper()
        desc = request.form.get("description", "").strip()
        try:
            conn.execute("UPDATE locations SET name=?,code=?,description=? WHERE id=?",
                         (name, code, desc, location_id))
            conn.commit()
            conn.close()
            flash("Location updated.", "success")
            return redirect(url_for("location_detail", location_id=location_id))
        except sqlite3.IntegrityError:
            conn.close()
            flash(f'Code "{code}" is already taken.', "error")
    conn.close()
    return render_template("location_form.html", location=location, suggested=location["code"])


@app.route("/locations/<int:location_id>/delete", methods=["POST"])
def delete_location(location_id):
    conn = get_db()
    conn.execute("DELETE FROM locations WHERE id=?", (location_id,))
    conn.commit()
    conn.close()
    flash("Location deleted.", "info")
    return redirect(url_for("locations"))


@app.route("/locations/<int:location_id>/add", methods=["POST"])
def add_item(location_id):
    item_id  = int(request.form["item_id"])
    quantity = max(1, int(request.form.get("quantity", 1)))
    conn     = get_db()
    conn.execute("""
        INSERT INTO item_locations (item_id, location_id, quantity) VALUES (?,?,?)
        ON CONFLICT(item_id, location_id) DO UPDATE SET quantity = quantity + excluded.quantity
    """, (item_id, location_id, quantity))
    conn.commit()
    conn.close()
    return redirect(url_for("location_detail", location_id=location_id))


@app.route("/locations/<int:location_id>/remove/<int:item_id>", methods=["POST"])
def remove_item(location_id, item_id):
    conn = get_db()
    conn.execute("DELETE FROM item_locations WHERE location_id=? AND item_id=?",
                 (location_id, item_id))
    conn.commit()
    conn.close()
    return redirect(url_for("location_detail", location_id=location_id))


@app.route("/locations/<int:location_id>/qty/<int:item_id>", methods=["POST"])
def update_qty(location_id, item_id):
    qty  = max(1, int(request.form.get("quantity", 1)))
    conn = get_db()
    conn.execute("UPDATE item_locations SET quantity=? WHERE location_id=? AND item_id=?",
                 (qty, location_id, item_id))
    conn.commit()
    conn.close()
    return redirect(url_for("location_detail", location_id=location_id))


# ── Routes: QR codes ──────────────────────────────────────────────────────────

@app.route("/qr/<int:location_id>.png")
def qr_image(location_id):
    conn     = get_db()
    location = conn.execute("SELECT * FROM locations WHERE id=?", (location_id,)).fetchone()
    conn.close()
    if not location:
        abort(404)
    target = request.host_url.rstrip("/") + url_for("scan_redirect", code=location["code"])
    qr     = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(target)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/scan")
def scan():
    return render_template("scan.html")


@app.route("/go/<code>")
def scan_redirect(code):
    conn     = get_db()
    location = conn.execute("SELECT * FROM locations WHERE code=?", (code.upper(),)).fetchone()
    conn.close()
    if not location:
        flash(f'No location with code "{code}".', "error")
        return redirect(url_for("index"))
    return redirect(url_for("location_detail", location_id=location["id"]))


@app.route("/print")
def print_qr():
    conn      = get_db()
    locations = conn.execute("""
        SELECT l.*, COUNT(il.item_id) AS item_count
        FROM locations l LEFT JOIN item_locations il ON l.id = il.location_id
        GROUP BY l.id ORDER BY l.name
    """).fetchall()
    conn.close()
    return render_template("print_qr.html", locations=locations)


# ── Static uploads ────────────────────────────────────────────────────────────

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_file(os.path.join(UPLOAD_DIR, secure_filename(filename)))


# ── API ───────────────────────────────────────────────────────────────────────

@app.route("/api/items")
def api_items():
    q       = request.args.get("q", "").strip()
    excl    = request.args.get("exclude_location")
    conn    = get_db()
    if excl:
        rows = conn.execute("""
            SELECT id, name, description, photo FROM items
            WHERE (name LIKE ? OR description LIKE ?)
              AND id NOT IN (SELECT item_id FROM item_locations WHERE location_id=?)
            ORDER BY name LIMIT 30
        """, (f"%{q}%", f"%{q}%", excl)).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, name, description, photo FROM items WHERE name LIKE ? OR description LIKE ? ORDER BY name LIMIT 30",
            (f"%{q}%", f"%{q}%"),
        ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ── Visual search ─────────────────────────────────────────────────────────────

@app.route("/search/image", methods=["GET", "POST"])
def visual_search():
    if request.method == "POST":
        file = request.files.get("photo")
        if not file or not file.filename:
            flash("Please choose a photo.", "error")
            return redirect(url_for("visual_search"))

        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
        tmp = os.path.join(UPLOAD_DIR, f"_query_{uuid.uuid4().hex}.{ext}")
        file.save(tmp)
        try:
            query_vec = emb.embed_image_file(tmp)
        finally:
            os.remove(tmp)

        conn  = get_db()
        rows  = conn.execute(
            "SELECT id, name, description, photo, embedding FROM items WHERE embedding IS NOT NULL"
        ).fetchall()
        unindexed = conn.execute(
            "SELECT COUNT(*) FROM items WHERE photo IS NOT NULL AND embedding IS NULL"
        ).fetchone()[0]
        conn.close()

        scored = sorted(
            [{"score": emb.similarity(query_vec, emb.from_blob(r["embedding"])), **dict(r)}
             for r in rows],
            key=lambda x: x["score"], reverse=True
        )[:10]

        return render_template("visual_search.html", results=scored, unindexed=unindexed)

    conn = get_db()
    unindexed = conn.execute(
        "SELECT COUNT(*) FROM items WHERE photo IS NOT NULL AND embedding IS NULL"
    ).fetchone()[0]
    conn.close()
    return render_template("visual_search.html", results=None, unindexed=unindexed)


@app.route("/search/reindex", methods=["POST"])
def reindex():
    conn  = get_db()
    rows  = conn.execute(
        "SELECT id, photo FROM items WHERE photo IS NOT NULL AND embedding IS NULL"
    ).fetchall()
    conn.close()

    count = 0
    for row in rows:
        path = os.path.join(UPLOAD_DIR, row["photo"])
        if not os.path.exists(path):
            continue
        try:
            vec  = emb.embed_image_file(path)
            conn = get_db()
            conn.execute("UPDATE items SET embedding=? WHERE id=?",
                         (emb.to_blob(vec), row["id"]))
            conn.commit()
            conn.close()
            count += 1
        except Exception:
            pass

    flash(f"Indexed {count} photo{'s' if count != 1 else ''}.", "success")
    return redirect(url_for("visual_search"))


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
