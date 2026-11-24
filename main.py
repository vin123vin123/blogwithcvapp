import os
import base64
from datetime import datetime, timezone
import cv2
import numpy as np
from flask import Flask, request, jsonify, render_template_string
from pymongo import MongoClient
from music_player import music_bp

app = Flask(__name__)
app.register_blueprint(music_bp)

# ==========================================
# 🔌 MONGODB CONNECTION & 2-DAY TTL INDEXES
# ==========================================
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

db = client['unified_app_platform']
blog_collection = db['blog_posts']
cv_logs_collection = db['cv_match_logs']
images_collection = client['media_db']['images']  # Second DB for images

# Auto-delete documents older than 2 days (172,800 seconds)
TWO_DAYS = 172800
blog_collection.create_index("expire_at", expireAfterSeconds=TWO_DAYS)
cv_logs_collection.create_index("expire_at", expireAfterSeconds=TWO_DAYS)
images_collection.create_index("expire_at", expireAfterSeconds=TWO_DAYS)


def make_thumbnail_b64(img_matrix, max_width=180):
    h, w = img_matrix.shape[:2]
    if w > max_width:
        scale = max_width / float(w)
        img_matrix = cv2.resize(img_matrix, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA)
    _, buf = cv2.imencode('.jpg', img_matrix, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
    return base64.b64encode(buf).decode('utf-8')


# ==========================================
# 🏠 HOME INTERFACE
# ==========================================
@app.route('/', methods=['GET'])
def serve_home_interface():
    try:
        with open('index1.html', 'r', encoding='utf-8') as f:
            return render_template_string(f.read())
    except Exception as e:
        return f"<h1>Backend Live</h1><a href='/studio'>Open Music Studio</a><p>{e}</p>", 200


# ==========================================
# 📝 BLOG API (WITH 2-DAY AUTO-DELETE)
# ==========================================
@app.route('/api/blog', methods=['POST'])
def create_blog_post():
    try:
        data = request.json or {}
        title, content = data.get("title"), data.get("content")
        if not title or not content:
            return jsonify({"error": "Title and content required"}), 400

        now_utc = datetime.now(timezone.utc)
        post_doc = {
            "title": title,
            "content": content,
            "author": data.get("author", "Anonymous"),
            "created_at": now_utc.strftime("%Y-%m-%d %H:%M UTC"),
            "expire_at": now_utc
        }
        res = blog_collection.insert_one(post_doc)
        return jsonify({"success": True, "post_id": str(res.inserted_id)}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/blog', methods=['GET'])
def fetch_all_blog_posts():
    try:
        posts = list(blog_collection.find({}, {"expire_at": 0}).sort("_id", -1))
        for p in posts:
            p["_id"] = str(p["_id"])
        return jsonify(posts), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==========================================
# 👁️ CV2 SHAPE MATCHER + THUMBNAILS
# ==========================================
def extract_main_contour(gray):
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return max(contours, key=cv2.contourArea) if contours else None


@app.route('/api/cv/match-shape', methods=['POST'])
def match_grayscale_shape():
    try:
        if 'template' not in request.files or 'target' not in request.files:
            return jsonify({"error": "Upload both 'template' and 'target' images"}), 400

        img_temp = cv2.imdecode(np.frombuffer(request.files['template'].read(), np.uint8), cv2.IMREAD_GRAYSCALE)
        img_targ = cv2.imdecode(np.frombuffer(request.files['target'].read(), np.uint8), cv2.IMREAD_GRAYSCALE)
        if img_temp is None or img_targ is None:
            return jsonify({"error": "Invalid image format"}), 400

        temp_contour = extract_main_contour(img_temp)
        _, targ_thresh = cv2.threshold(img_targ, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        targ_contours, _ = cv2.findContours(targ_thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if temp_contour is None or not targ_contours:
            return jsonify({"error": "No prominent structural edges found"}), 400

        best_contour, lowest_score = None, float('inf')
        for c in targ_contours:
            if cv2.contourArea(c) >= 40:
                score = cv2.matchShapes(temp_contour, c, cv2.CONTOURS_MATCH_I1, 0.0)
                if score < lowest_score:
                    lowest_score, best_contour = score, c

        now_utc = datetime.now(timezone.utc)
        temp_thumb = make_thumbnail_b64(img_temp)
        match_found = lowest_score < 0.40 and best_contour is not None
        box = {}

        if match_found:
            x, y, w, h = cv2.boundingRect(best_contour)
            box = {"x": x, "y": y, "width": w, "height": h}
            canvas = img_targ.copy()
            cv2.rectangle(canvas, (x - 1, y - 1), (x + w + 1, y + h + 1), 0, 6)
            cv2.rectangle(canvas, (x, y), (x + w, y + h), 255, 3)
            canvas[y:y+h, x:x+w] = cv2.bitwise_not(canvas[y:y+h, x:x+w])
            cv2.putText(canvas, "MATCH", (x + 5, y + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 255, 2, cv2.LINE_AA)
            res_thumb = make_thumbnail_b64(canvas)
        else:
            res_thumb = make_thumbnail_b64(img_targ)

        log_doc = {
            "match_success": match_found,
            "score": lowest_score if lowest_score != float('inf') else 999.0,
            "bounding_box": box,
            "template_thumb": temp_thumb,
            "result_thumb": res_thumb,
            "processed_at": now_utc.strftime("%Y-%m-%d %H:%M UTC"),
            "expire_at": now_utc
        }
        log_id = str(cv_logs_collection.insert_one(log_doc).inserted_id)

        return jsonify({
            "match_found": match_found,
            "score": log_doc["score"],
            "coordinates": box,
            "database_log_id": log_id
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==========================================
# 📊 CROSS-DB JOIN & COMPARISON SUMMARY
# ==========================================
@app.route('/api/dashboard-summary', methods=['GET'])
def get_cross_db_summary():
    try:
        posts = list(blog_collection.find({}, {"expire_at": 0}).sort("_id", -1))
        imgs = list(images_collection.find({}, {"_id": 0, "expire_at": 0}))
        img_map = {i.get("title"): i for i in imgs if i.get("title")}

        joined, matched_blogs = [], 0
        for p in posts:
            pid = str(p["_id"])
            img = img_map.get(p.get("title")) or img_map.get(pid)
            if img:
                matched_blogs += 1
            joined.append({
                "id": pid,
                "title": p.get("title", "Untitled"),
                "author": p.get("author", "Anonymous"),
                "content": p.get("content", ""),
                "created_at": p.get("created_at", ""),
                "image": img
            })

        logs = list(cv_logs_collection.find({}, {"expire_at": 0}).sort("_id", -1).limit(30))
        total_cv = len(logs)
        hits = sum(1 for l in logs if l.get("match_success"))
        scores = [l["score"] for l in logs if isinstance(l.get("score"), (int, float)) and l["score"] < 900]

        return jsonify({
            "summary": {
                "total_blogs": len(posts),
                "blogs_with_images": matched_blogs,
                "total_cv_comparisons": total_cv,
                "cv_matches_found": hits,
                "cv_match_rate": f"{round((hits / total_cv) * 100, 1)}%" if total_cv else "0%",
                "avg_hu_score": round(sum(scores) / len(scores), 4) if scores else 0
            },
            "items": joined,
            "recent_comparisons": [
                {
                    "success": l.get("match_success", False),
                    "score": round(l["score"], 4) if isinstance(l.get("score"), (int, float)) and l["score"] < 900 else "N/A",
                    "box": l.get("bounding_box", {}),
                    "template_thumb": l.get("template_thumb", ""),
                    "result_thumb": l.get("result_thumb", ""),
                    "time": l.get("processed_at", "")
                }
                for l in logs[:6]
            ]
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 11000)))
