import os
import json
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, session, flash, url_for, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "supersecretkey"

UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ----------------- Helpers -----------------

def load_json(file):
    if not os.path.exists(file):
        if "notifications" in file:
            return {
                "notifications": [],
            }
        elif "users" in file:
            return {"users": []}
        elif "complaints" in file:
            return {"complaints": []}
        elif "categories" in file:
            return {"categories": []}
    with open(file, "r") as f:
        return json.load(f)

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=4)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

def generate_id():
    complaints = load_json("complaints.json")["complaints"]
    if not complaints:
        return "CMP-001"
    last = int(complaints[-1]["id"].split("-")[1])
    return f"CMP-{last + 1:03d}"

def login_required(role=None):
    def wrapper(func):
        @wraps(func)
        def decorated(*args, **kwargs):
            if "user" not in session:
                return redirect("/login")
            if role and session["user"]["role"] != role:
                return redirect("/dashboard")
            return func(*args, **kwargs)
        return decorated
    return wrapper

def add_notify(user_id, message, link="#"):
    notifs = load_json("notifications.json")

    if "notifications" not in notifs:
        notifs["notifications"] = []

    notifs["notifications"].append({
        "id": len(notifs["notifications"]) + 1,
        "user_id": user_id,   # "admin" OR actual user id
        "message": message,
        "link": link,
        "read": False,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    })

    save_json("notifications.json", notifs)
# ----------------- Auth -----------------

@app.route("/")
def home():
    return redirect("/login")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        phone = request.form["phone"]
        email = request.form["email"]
        dob = request.form["dob"]
        password = request.form["password"]
        confirm = request.form["confirm"]

        if not all([name, phone, password]):
            flash("Required fields missing", "error")
            return redirect("/register")

        if password != confirm:
            flash("Passwords do not match", "error")
            return redirect("/register")

        users = load_json("users.json")
        if any(u["phone"] == phone for u in users["users"]):
            flash("Phone already registered", "error")
            return redirect("/register")

        image = ""
        file = request.files.get("image")
        if file and file.filename:
            if not allowed_file(file.filename):
                flash("Only image files are allowed", "error")
                return redirect("/register")
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            image = filename

        user = {
            "id": len(users["users"]) + 1,
            "name": name,
            "phone": phone,
            "email": email,
            "dob": dob,
            "password": generate_password_hash(password),
            "role": "user",
            "image": image
        }

        users["users"].append(user)
        save_json("users.json", users)
        flash("Registration successful. Please login.", "success")
        return redirect("/login")

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = request.form["phone"]
        password = request.form["password"]

        users = load_json("users.json")["users"]
        for user in users:
            if user["phone"] == phone and check_password_hash(user["password"], password):
                session["user"] = user
                flash("Login successful", "success")
                return redirect("/dashboard")

        flash("Invalid credentials", "error")
        return redirect("/login")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ----------------- Dashboard -----------------

@app.route("/dashboard")
@login_required()
def dashboard():
    complaints = load_json("complaints.json")["complaints"]
    if session["user"]["role"] == "user":
        complaints = [c for c in complaints if c["user_id"] == session["user"]["id"]]
    stats = {
        "Open": sum(c["status"] == "Open" for c in complaints),
        "In Progress": sum(c["status"] == "In Progress" for c in complaints),
        "Resolved": sum(c["status"] == "Resolved" for c in complaints)
    }
    return render_template("dashboard.html", complaints=complaints, stats=stats)

# ----------------- Complaint Create -----------------

@app.route("/complaint", methods=["GET", "POST"])
@login_required()
def complaint():
    categories = load_json("categories.json")["categories"]
    if request.method == "POST":
        address = request.form["address"]
        category = request.form["category"]
        desc = request.form["desc"]
        date = request.form["date"]
        lat = request.form.get("lat")
        lng = request.form.get("lng")

        if not all([address, category, desc]):
            flash("Required fields missing", "error")
            return redirect("/complaint")

        if category not in categories:
            cat_data = load_json("categories.json")
            cat_data["categories"].append(category)
            save_json("categories.json", cat_data)

        image = ""
        file = request.files.get("image")
        if file and file.filename:
            if not allowed_file(file.filename):
                flash("Only image files are allowed", "error")
                return redirect("/complaint")
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            image = filename

        complaints = load_json("complaints.json")
        new_complaint = {
            "id": generate_id(),
            "user_id": session["user"]["id"],
            "address": address,
            "category": category,
            "description": desc,
            "date": date,
            "lat": lat,
            "lng": lng,
            "status": "Open",
            "image": image,
            "timestamp": datetime.now().isoformat()
        }
        complaints["complaints"].append(new_complaint)
        save_json("complaints.json", complaints)
        
        # Notify Admin
        add_notify(
            "admin",
            f"New complaint {new_complaint['id']} from {session['user']['name']}",
            f"/complaint/{new_complaint['id']}"
        )
        flash("Complaint submitted successfully", "success")
        return redirect("/dashboard")

    return render_template("complaint.html", categories=categories)

# ----------------- Complaint View/Edit -----------------
@app.route("/complaint/<complaint_id>", methods=["GET", "POST"])
@login_required()
def view_complaint(complaint_id):
    complaints_data = load_json("complaints.json")
    categories = load_json("categories.json")["categories"]
    complaint = next((c for c in complaints_data["complaints"] if c["id"] == complaint_id), None)

    if not complaint:
        flash("Complaint not found", "error")
        return redirect("/dashboard")

    if session["user"]["role"] != "admin" and complaint["user_id"] != session["user"]["id"]:
        flash("Unauthorized access", "error")
        return redirect("/dashboard")

    # PERMISSION: Admin can ONLY edit if they created it. User can edit their own.
    can_edit = complaint["user_id"] == session["user"]["id"]

    if request.method == "POST":
        if not can_edit:
            flash("Admin cannot edit user complaints. Change status in Admin Panel only.", "error")
            return redirect(f"/complaint/{complaint_id}")

        complaint["address"] = request.form["address"]
        complaint["category"] = request.form["category"]
        complaint["description"] = request.form["desc"]
        complaint["date"] = request.form["date"]
        complaint["lat"] = request.form.get("lat")
        complaint["lng"] = request.form.get("lng")

        file = request.files.get("image")
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            complaint["image"] = filename

        
        save_json("complaints.json", complaints_data)
        flash("Complaint updated successfully", "success")
        return redirect("/dashboard")

    return render_template("view_complaint.html", complaint=complaint, categories=categories, can_edit=can_edit)
@app.route("/complaint/delete/<complaint_id>", methods=["POST"])
@login_required()
def delete_complaint(complaint_id):
    complaints_data = load_json("complaints.json")
    complaint = None
    for c in complaints_data["complaints"]:
        if c["id"] == complaint_id:
            complaint = c
            break

    if not complaint:
        flash("Complaint not found", "error")
        return redirect("/dashboard")

    # Only Owner or Admin can delete
    if session["user"]["role"] != "admin" and complaint["user_id"] != session["user"]["id"]:
        flash("Unauthorized action", "error")
        return redirect("/dashboard")

    complaints_data["complaints"] = [c for c in complaints_data["complaints"] if c["id"] != complaint_id]
    save_json("complaints.json", complaints_data)
    flash("Complaint deleted successfully", "success")
    return redirect("/dashboard")

# ----------------- Admin -----------------

@app.route("/admin", methods=["GET", "POST"])
@login_required(role="admin")
def admin():
    users = load_json("users.json")
    complaints = load_json("complaints.json")

    if request.method == "POST":
        action = request.form["action"]
        uid = request.form.get("user_id")
        cid = request.form.get("complaint_id")

        if action == "delete_user":
            users["users"] = [u for u in users["users"] if str(u["id"]) != uid]
            save_json("users.json", users)
            flash("User deleted", "success")

        elif action == "promote":
            for u in users["users"]:
                if str(u["id"]) == uid:
                    u["role"] = "admin"
            save_json("users.json", users)
            flash("User promoted to Admin", "success")

        elif action == "update_status":
            status = request.form["status"]
            for c in complaints["complaints"]:
                if c["id"] == cid:
                    c["status"] = status
                    # Notify USER with link to complaint
                    add_notify(c["user_id"], f"Your complaint {cid} is now {status}", f"/complaint/{cid}")
            save_json("complaints.json", complaints)
            flash(f"Status updated to {status}", "success")

        return redirect("/admin")

    return render_template("admin.html", users=users["users"], complaints=complaints["complaints"])

# ----------------- Profile -----------------

@app.route("/profile", methods=["GET", "POST"])
@login_required()
def profile():
    users = load_json("users.json")
    if request.method == "POST":
        for u in users["users"]:
            if u["id"] == session["user"]["id"]:
                u["name"] = request.form["name"]
                u["email"] = request.form["email"]
                file = request.files.get("image")
                if file and file.filename:
                    if not allowed_file(file.filename):
                        flash("Only image files are allowed", "error")
                        return redirect("/profile")
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                    u["image"] = filename
                session["user"] = u
        save_json("users.json", users)
        flash("Profile updated successfully", "success")
        return redirect("/profile")
    return render_template("profile.html")

# ----------------- Notifications API -----------------

@app.route("/get_notifications")
@login_required()
def get_notifications():
    all_n = load_json("notifications.json")["notifications"]

    if session["user"]["role"] == "admin":
        # Admin ONLY sees admin notifications
        mine = [n for n in all_n if n["user_id"] == "admin"]
    else:
        # User ONLY sees their notifications
        uid = session["user"]["id"]
        mine = [n for n in all_n if n["user_id"] == uid]

    return jsonify({"notifications": mine[::-1][:10], "count": len(mine)})

if __name__ == "__main__":
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    # Initialize JSONs if missing
    if not os.path.exists("notifications.json"):
        save_json("notifications.json", {"notifications": []})
    app.run(debug=True)