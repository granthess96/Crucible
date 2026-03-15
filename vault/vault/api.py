from flask import Flask, request, Response, jsonify, send_file
import io
import json

app = Flask(__name__)
store = None  # injected at startup

# ── Health ───────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    ok = store.ping()
    return jsonify({"status": "ok" if ok else "degraded", "garage": ok}), 200 if ok else 503

# ── Blob routes ──────────────────────────────────────────────────

@app.route("/blob/<digest>", methods=["PUT"])
def put_blob(digest):
    actual = store.put_blob_stream(request.stream, request.content_length)
    if actual != digest:
        return jsonify({"error": "digest mismatch", "actual": actual}), 400
    return jsonify({"digest": actual}), 200

@app.route("/blob/<digest>", methods=["GET", "HEAD"])
def get_blob(digest):
    size = store.blob_size(digest)
    if size is None:
        return jsonify({"error": "not found"}), 404

    # Prepare headers that apply to BOTH GET and HEAD
    headers = {
        "Content-Length": str(size),
        "Content-Type": "application/octet-stream", # Flask 'mimetype' sets this
        "X-Blob-Size": str(size)
    }

    if request.method == "HEAD":
        return Response(status=200, headers=headers)

    try:
        # If get_blob_stream returns a file-like object, 
        # let Flask/Waitress handle the reading.
        body = store.get_blob_stream(digest)
    except KeyError:
        return jsonify({"error": "not found"}), 404

    return Response(
        body, 
        headers=headers,
        direct_passthrough=True # Crucial for Waitress to respect Content-Length
    )

# ── Name routes ──────────────────────────────────────────────────

@app.route("/name/<path:name>", methods=["GET"])
def get_name(name):
    try:
        record = store.get_name(name)
        return jsonify(record), 200
    except KeyError:
        return jsonify({"error": "not found"}), 404

@app.route("/name/<path:name>", methods=["PUT"])
def put_name(name):
    body = request.get_json()
    if not body or "digest" not in body:
        return jsonify({"error": "digest required"}), 400
    try:
        record = store.put_name(
            name,
            body["digest"],
            protected=body.get("protected", False),
            note=body.get("note", ""),
            force=body.get("force", False)
        )
        return jsonify(record), 200
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403

@app.route("/blob", methods=["GET"])
def list_blobs():
    return jsonify(store.list_blobs())

@app.route("/name", methods=["GET"])
def list_names():
    return jsonify(store.list_names())