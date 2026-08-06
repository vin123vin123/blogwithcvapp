import os
import cv2
import numpy as np
from flask import Flask, request, jsonify
from pymongo import MongoClient
from bson.objectid import ObjectId

app = Flask(__name__)

# ==========================================
# 🔌 MONGO DB CONNECTION SETUP
# ==========================================
# Fetches the connection string securely from Render's Environment panel
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client['unified_app_platform']

# Collection references
blog_collection = db['blog_posts']
cv_logs_collection = db['cv_match_logs']


# ==========================================
# 🏠 SERVER HEALTH ROUTE
# ==========================================
@app.route('/', methods=['GET'])
def health_check():
    return jsonify({
        "status": "Online",
        "message": "Unified Blog & CV2 API Engine running successfully."
    }), 200


# ==========================================
# 📝 APP 1: BLOG ENGINE API ENDPOINTS
# ==========================================
@app.route('/api/blog', methods=['POST'])
def create_blog_post():
    """Creates a new blog article and inserts it into MongoDB."""
    try:
        data = request.json or {}
        title = data.get("title")
        content = data.get("content")
        author = data.get("author", "Anonymous")

        if not title or not content:
            return jsonify({"error": "Title and content fields are required"}), 400

        post_document = {
            "title": title,
            "content": content,
            "author": author,
            "created_at": np.datetime64('now').astype(str)
        }

        inserted_id = blog_collection.insert_one(post_document).inserted_id
        return jsonify({"success": True, "post_id": str(inserted_id)}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/blog', methods=['GET'])
def fetch_all_blog_posts():
    """Retrieves all stored blog entries out of the database."""
    try:
        posts = list(blog_collection.find().sort("_id", -1))
        for post in posts:
            post["_id"] = str(post["_id"]) # Cast MongoDB ObjectId to JSON string
        return jsonify(posts), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==========================================
# 👁️ APP 2: CV2 SHAPE MATCHING API ENDPOINT
# ==========================================
def extract_main_contour(grayscale_matrix):
    """Binarizes an image buffer using Otsu's thresholding and extracts the main contour."""
    _, thresh = cv2.threshold(grayscale_matrix, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    return max(contours, key=cv2.contourArea)


@app.route('/api/cv/match-shape', methods=['POST'])
def match_grayscale_shape():
    """
    Accepts a template image file and a target image file. 
    Finds the shape via Hu Moments, draws contrast outlines, and logs coordinates to MongoDB.
    """
    try:
        if 'template' not in request.files or 'target' not in request.files:
            return jsonify({"error": "Please upload both 'template' and 'target' images"}), 400

        # 1. Read files into RAM buffers
        template_bytes = request.files['template'].read()
        target_bytes = request.files['target'].read()

        # 2. Decode files straight into 1-channel Grayscale matrices
        np_temp = np.frombuffer(template_bytes, np.uint8)
        np_targ = np.frombuffer(target_bytes, np.uint8)

        img_template = cv2.imdecode(np_temp, cv2.IMREAD_GRAYSCALE)
        img_target = cv2.imdecode(np_targ, cv2.IMREAD_GRAYSCALE)

        if img_template is None or img_target is None:
            return jsonify({"error": "Invalid image file format uploaded"}), 400

        # 3. Separate structural outlines
        template_contour = extract_main_contour(img_template)
        
        _, target_thresh = cv2.threshold(img_target, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        target_contours, _ = cv2.findContours(target_thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if template_contour is None or not target_contours:
            return jsonify({"error": "Could not isolate enough prominent structural edges"}), 400

        # 4. Search and score target image contents
        best_match_contour = None
        lowest_match_score = float('inf')

        for contour in target_contours:
            if cv2.contourArea(contour) < 40: # Ignore tiny visual artifacts/dust
                continue
            
            # Compute Hu Moments structural delta score
            score = cv2.matchShapes(template_contour, contour, cv2.CONTOURS_MATCH_I1, 0.0)
            if score < lowest_match_score:
                lowest_match_score = score
                best_match_contour = contour

        # 5. Evaluate results against standard structural margins (relaxed to 0.40)
        match_found = False
        box_coordinates = {}
        log_id = None

        if lowest_match_score < 0.40 and best_match_contour is not None:
            match_found = True
            x, y, w, h = cv2.boundingRect(best_match_contour)
            box_coordinates = {"x": x, "y": y, "width": w, "height": h}

            # --- DUAL-CONTRAST GRAYSCALE DRAWING ENGINE ---
            # Create working copy of target image grid array
            canvas = img_target.copy()
            
            # Draw wide black outer boundary baseline box for light backgrounds
            cv2.rectangle(canvas, (x-1, y-1), (x + w + 1, y + h + 1), 0, 6)
            # Draw tight inner white box for dark backgrounds
            cv2.rectangle(canvas, (x, y), (x + w, y + h), 255, 3)

            # Invert colors inside the bounding region to flag exactly what matched
            roi = canvas[y:y+h, x:x+w]
            canvas[y:y+h, x:x+w] = cv2.bitwise_not(roi)

            # Text confirmation marker on the image array
            cv2.putText(canvas, "MATCH", (x + 5, y + 22), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, 255, 2, cv2.LINE_AA)

            # --- MONGO DB LOGGING TRIGGER ---
            log_document = {
                "match_success": True,
                "score": lowest_match_score,
                "bounding_box": box_coordinates,
                "processed_at": np.datetime64('now').astype(str)
            }
            log_id = str(db['cv_match_logs'].insert_one(log_document).inserted_id)

            # Convert our updated image array back to a binary string to return it
            _, encoded_img = cv2.imencode('.jpg', canvas)
            # You can process encoded_img if saving down to cloud blobs later

        else:
            # Log failed matches to database tracking for debugging analytics
            log_document = {
                "match_success": False,
                "score": lowest_match_score,
                "processed_at": np.datetime64('now').astype(str)
            }
            log_id = str(db['cv_match_logs'].insert_one(log_document).inserted_id)

        return jsonify({
            "match_found": match_found,
            "score": lowest_match_score,
            "coordinates": box_coordinates,
            "database_log_id": log_id
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==========================================
# ⚙️ SYSTEM START RUNTIME
# ==========================================
if __name__ == '__main__':
    # Render maps dynamic ports inside routing headers dynamically at launch
    app_port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=app_port)
