import os
import cv2
import io
import numpy as np
from flask import Flask, render_template_string, request, redirect, url_for, flash, send_file
from pymongo import MongoClient
from bson.objectid import ObjectId

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "super_secret_fallback_key")

# 1. MONGODB CONFIGURATION
# Pulls connection string from Render env variables. Falls back to local machine if blank.
mongo_url = os.environ.get('DATABASE_URL')

if mongo_url:
    # Connect to MongoDB Atlas Cloud
    client = MongoClient(mongo_url)
else:
    # Fallback to local MongoDB instance for development testing
    client = MongoClient('mongodb://localhost:27017/')

# Define the database and collection names
db = client['blog_db']
posts_collection = db['posts']


# 2. MONOLITHIC HTML TEMPLATE
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Multi-Service MongoDB App</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; background: #f4f4f9; }
        .card { background: white; padding: 20px; margin-bottom: 20px; border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
        h1 { color: #333; }
        nav { margin-bottom: 20px; background: #fff; padding: 15px; border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
        nav a { margin-right: 15px; text-decoration: none; color: #007BFF; font-weight: bold; }
        nav a:hover { text-decoration: underline; }
        label { display: block; margin-top: 10px; font-weight: bold; }
        input[type="text"], input[type="file"], textarea { width: 100%; padding: 10px; margin-top: 5px; box-sizing: border-box; }
        button { background: #007BFF; color: white; border: none; padding: 10px 15px; margin-top: 10px; cursor: pointer; border-radius: 3px; }
        button:hover { background: #0056b3; }
    </style>
</head>
<body>
    <nav>
        <a href="{{ url_for('home') }}">Blog Home</a>
        <a href="{{ url_for('about') }}">About Me</a>
        <a href="{{ url_for('cv_tool') }}">OpenCV Tool</a>
        <a href="{{ url_for('admin') }}">Write Post</a>
    </nav>

    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for message in messages %}
          <p style="color: green;"><b>{{ message }}</b></p>
        {% endfor %}
      {% endif %}
    {% endwith %}

    {% block content %}{% endblock %}
</body>
</html>
"""

# 3. ROUTE CONTROLLERS

# Route A: Blog Feed (Fetches all documents from MongoDB sorted by newest first)
@app.route('/')
def home():
    # MongoDB uses .find().sort('_id', -1) to achieve descending chronological order
    posts = list(posts_collection.find().sort('_id', -1))
    
    home_html = HTML_TEMPLATE.replace('{% block content %}{% endblock %}', """
        <h1>Latest Blog Updates (MongoDB)</h1>
        {% if posts %}
            {% for post in posts %}
                <div class="card">
                    <h2>{{ post.title }}</h2>
                    <p>{{ post.content }}</p>
                </div>
            {% endfor %}
        {% else %}
            <div class="card"><p>No posts found. Use 'Write Post' to add content!</p></div>
        {% endif %}
    """)
    return render_template_string(home_html, posts=posts)

# Route B: Static About Page
@app.route('/about')
def about():
    about_html = HTML_TEMPLATE.replace('{% block content %}{% endblock %}', """
        <h1>About This Web Service</h1>
        <div class="card">
            <p>This is a unified application deployed to Render.</p>
            <p>It dynamically switches roles between serving content out of a permanent MongoDB Atlas cloud cluster and executing matrix manipulations on uploaded images via OpenCV.</p>
        </div>
    """)
    return render_template_string(about_html)

# Route C: The Admin Console (Inserts documents directly into MongoDB)
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        
        if title and content:
            # Create a dictionary payload to insert into NoSQL collection
            new_post = {
                "title": title,
                "content": content
            }
            posts_collection.insert_one(new_post)
            flash("Blog post written to MongoDB successfully!")
            return redirect(url_for('home'))
            
    admin_html = HTML_TEMPLATE.replace('{% block content %}{% endblock %}', """
        <h1>Write New Blog Entry</h1>
        <form method="POST" class="card">
            <label>Post Title</label>
            <input type="text" name="title" required>
            <label>Content</label>
            <textarea name="content" rows="6" required></textarea>
            <button type="submit">Publish</button>
        </form>
    """)
    return render_template_string(admin_html)

# Route D: OpenCV User Interface Page
@app.route('/cv-tool')
def cv_tool():
    cv_html = HTML_TEMPLATE.replace('{% block content %}{% endblock %}', """
        <h1>OpenCV Image Processing Microservice</h1>
        <div class="card">
            <p>Upload any picture below. The application will convert the image into an uncompressed byte-array stream, apply a grayscale matrix transform using <b>cv2</b>, and download it instantly.</p>
            <form action="{{ url_for('process_image') }}" method="POST" enctype="multipart/form-data">
                <label>Select Image File:</label>
                <input type="file" name="image" accept="image/*" required>
                <button type="submit">Process & Download</button>
            </form>
        </div>
    """)
    return render_template_string(cv_html)

# Route E: OpenCV Processing Engine API Endpoint
@app.route('/process-image', methods=['POST'])
def process_image():
    if 'image' not in request.files:
        return "No image provided", 400
    file = request.files['image']
    
    in_memory_file = io.BytesIO()
    file.save(in_memory_file)
    data = np.frombuffer(in_memory_file.getvalue(), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)

    if image is None:
        return "Invalid file format", 400

    processed_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, buffer = cv2.imencode('.jpg', processed_image)
    
    return send_file(io.BytesIO(buffer), mimetype='image/jpeg')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
