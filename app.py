from flask import Flask, render_template, request, redirect, url_for, session, flash
from functools import wraps
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime, date

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///flexmode.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'


db = SQLAlchemy(app)

# ─── Models ────────────────────────────────────────────────────────────────
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<User {self.username}>'

class Progress(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    user = db.relationship("User", backref="progress")

    day = db.Column(db.Integer)
    completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime, default=datetime.utcnow)

class Workout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.Integer, unique=True)

    title = db.Column(db.String(200))
    video_url = db.Column(db.String(300))
    meal_image = db.Column(db.String(300))

    # VEG meals
    veg_breakfast = db.Column(db.String(200))
    veg_lunch = db.Column(db.String(200))
    veg_snack = db.Column(db.String(200))
    veg_dinner = db.Column(db.String(200))

    # NON VEG meals
    nonveg_breakfast = db.Column(db.String(200))
    nonveg_lunch = db.Column(db.String(200))
    nonveg_snack = db.Column(db.String(200))
    nonveg_dinner = db.Column(db.String(200))

    exercises = db.Column(db.Text)

# Create tables & seed some admin users (only once)
with app.app_context():
    db.create_all()
    # Seed admins if none exist
    if not User.query.filter_by(is_admin=True).first():
        admins = [
            ("Nidhi", "skillns123@gmail.com", "admin123", True),
            ("admin2", "admin2@flexmode.com", "admin456", True),
        ]
        for username, email, pw, admin in admins:
            user = User(
                username=username,
                email=email,
                password=generate_password_hash(pw),
                is_admin=admin
            )
            db.session.add(user)
        db.session.commit()
        print("Admin users created.")


# ─── Helper: login required decorator ──────────────────────────────────────
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('is_admin'):
            flash("Admin access only.", "danger")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return wrapper

@app.route('/')
def index():

    if session.get("user_id"):
        if session.get("is_admin"):
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        if not all([username, email, password]):
            flash("All fields are required.", "danger")
            return redirect(url_for('register'))
        
        if len(password) < 8:
            flash("Password must be at least 8 characters long.", "danger")
            return redirect(url_for('register'))

        if password != request.form.get('confirm_password'):
            flash("Passwords do not match.", "danger")
            return redirect(url_for('register'))

        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash("Username or email already exists.", "danger")
            return redirect(url_for('register'))

        new_user = User(
            username=username,
            email=email,
            password=generate_password_hash(password),
            is_admin=False
        )
        db.session.add(new_user)
        db.session.commit()

        flash("Registration successful! Please log in.", "success")
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['is_admin'] = user.is_admin
            flash(f"Welcome back, {user.username}!", "success")
            if user.is_admin:
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid email or password.", "danger")

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    user_id = session['user_id']

    completed_records = Progress.query.filter_by(user_id=user_id, completed=True).all()
    completed_days    = len(completed_records)
    current_day       = completed_days + 1

    total_days = Workout.query.count()

    # Build a dict of completed day -> progress record for quick lookup
    completed_map = {p.day: p for p in completed_records}

    # Check if the NEXT day (current_day) is unlocked yet
    # Day 1 is always available
    # Any subsequent day unlocks 24h after the previous day was completed
    next_day_unlocked = False
    hours_remaining   = None

    if current_day == 1:
        next_day_unlocked = True

    elif (current_day - 1) in completed_map:
        prev        = completed_map[current_day - 1]
        diff        = (datetime.utcnow() - prev.completed_at).total_seconds()
        next_day_unlocked = diff >= 86400

        if not next_day_unlocked:
            # How many hours are left until unlock
            hours_remaining = round((86400 - diff) / 3600, 1)

    # Cap current_day at total_days so it never goes out of bounds
    current_day = min(current_day, total_days) if total_days > 0 else 1

    return render_template(
        "dashboard.html",
        current_day=current_day,
        completed_days=completed_days,
        total_days=total_days,
        next_day_unlocked=next_day_unlocked,
        hours_remaining=hours_remaining,
    )


@app.route('/day/<int:day_number>')
@login_required
def day(day_number):

    diet = request.args.get("diet")
    workout = Workout.query.filter_by(day=day_number).first()

    if not workout:
        flash("Workout not created yet.", "warning")
        return redirect(url_for("dashboard"))

    return render_template(
        "day.html",
        day=day_number,
        workout=workout,
        diet=diet
    )



@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():

    today_date = datetime.now().strftime("%d %B %Y")
    total_users = User.query.count()

    today = date.today()

    active_users = Progress.query.filter(
        db.func.date(Progress.completed_at) == today
    ).distinct(Progress.user_id).count()

    completed_workouts = Progress.query.filter_by(completed=True).count()

    longest_streak = db.session.query(
        db.func.max(Progress.day)
    ).filter_by(completed=True).scalar() or 0

    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    
    top_days_query = db.session.query(
    Progress.day,
    db.func.count(Progress.id).label("count")
    ).filter_by(completed=True).group_by(Progress.day).order_by(db.func.count(Progress.id).desc()).limit(3).all()

    top_days = []

    for d in top_days_query:
        workout = Workout.query.filter_by(day=d.day).first()
        title = workout.title if workout else "Workout"
        percent = round((d.count / completed_workouts) * 100) if completed_workouts else 0

        top_days.append({
            "day": d.day,
            "title": title,
            "count": d.count,
            "percent": percent
        })

    # -------- USER PROGRESS TABLE --------
    users = User.query.filter_by(is_admin=False).all()

    user_progress = []

    for user in users:

        completed = Progress.query.filter_by(user_id=user.id, completed=True).count()

        last = Progress.query.filter_by(user_id=user.id, completed=True)\
            .order_by(Progress.completed_at.desc()).first()

        last_workout = last.completed_at.strftime("%d %b %Y") if last else None

        user_progress.append({
            "username": user.username,
            "completed_days": completed,
            "current_day": completed + 1,
            "last_workout": last_workout
        })

    return render_template(
        "admin.html",
        top_days=top_days,
        total_users=total_users,
        active_users=active_users,
        completed_workouts=completed_workouts,
        longest_streak=longest_streak,
        recent_users=recent_users,
        today_date=today_date,
        user_progress=user_progress
    )

@app.route('/reset-password', methods=['GET','POST'])
def reset_password_page():

    if request.method == 'POST':

        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()

        if not user:
            flash("Email not found.", "danger")
            return redirect(url_for('reset_password_page'))
        
        if user.id != session["user_id"]:
            flash("You can only reset your own password.", "danger")
            return redirect(url_for("dashboard"))

        user.password = generate_password_hash(password)

        db.session.commit()

        flash("Password reset successfully. Please login.", "success")

        return redirect(url_for('login'))
    return render_template("reset_password.html")

@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/delete-user/<int:user_id>')
@login_required
@admin_required
def delete_user(user_id):

    user = User.query.get_or_404(user_id)

    if user.is_admin:
        flash("Cannot delete admin user.", "danger")
        return redirect(url_for('admin_users'))

    Progress.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()

    flash("User deleted.", "success")

    return redirect(url_for('admin_users'))

@app.route('/admin/promote/<int:user_id>')
@login_required
@admin_required
def promote_user(user_id):

    user = User.query.get_or_404(user_id)

    user.is_admin = True

    db.session.commit()

    flash("User promoted to admin.", "success")

    return redirect(url_for('admin_users'))

@app.route('/admin/reset-password/<int:user_id>')
@login_required
@admin_required
def reset_password(user_id):

    user = User.query.get_or_404(user_id)
    new_password = generate_password_hash("12345678")
    user.password = new_password
    db.session.commit()

    flash("Password reset to 12345678", "info")

    return redirect(url_for('admin_users'))

import csv
from flask import Response


@app.route('/admin/export-users')
@login_required
@admin_required
def export_users():

    users = User.query.all()

    def generate():
        yield "id,username,email\n"
        for u in users:
            yield f"{u.id},{u.username},{u.email}\n"

    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=users.csv"}
    )

@app.route('/admin/plans')
@login_required
@admin_required
def admin_plans():

    plans = Workout.query.order_by(Workout.day).all()

    return render_template("admin_plans.html", plans=plans)

@app.route('/admin/add-plan', methods=['GET','POST'])
@login_required
@admin_required
def add_plan():

    if request.method == "POST":

        day = int(request.form.get("day"))

        existing = Workout.query.filter_by(day=day).first()

        if existing:
            flash("Plan for this day already exists.", "danger")
            return redirect(url_for("admin_plans"))

        plan = Workout(
            day=day,
            title=request.form.get("title"),
            video_url=request.form.get("video_url"),
            meal_image=request.form.get("meal_image"),

            veg_breakfast=request.form.get("veg_breakfast"),
            veg_lunch=request.form.get("veg_lunch"),
            veg_snack=request.form.get("veg_snack"),
            veg_dinner=request.form.get("veg_dinner"),

            nonveg_breakfast=request.form.get("nonveg_breakfast"),
            nonveg_lunch=request.form.get("nonveg_lunch"),
            nonveg_snack=request.form.get("nonveg_snack"),
            nonveg_dinner=request.form.get("nonveg_dinner"),

            exercises=request.form.get("exercises")
        )

        db.session.add(plan)
        db.session.commit()

        flash("Plan added successfully", "success")

        return redirect(url_for("admin_plans"))

    return render_template("add_plan.html")


@app.route("/progress")
@login_required
def progress():

    user_id = session["user_id"]

    total_days = Workout.query.count()

    progress_records = Progress.query.filter_by(user_id=user_id).all()

    completed_days = {p.day: p for p in progress_records if p.completed}

    days = []

    for day in range(1, total_days + 1):

        status = "locked"

        # completed day
        if day in completed_days:
            status = "completed"

        # first day always available
        elif day == 1:
            status = "available"

        # unlock next day after 24h
        elif (day - 1) in completed_days:

            prev = completed_days[day - 1]

            diff = (datetime.utcnow() - prev.completed_at).total_seconds()

            if diff >= 86400:
                status = "available"

        days.append({
            "day": day,
            "status": status
        })

    return render_template("progress.html", days=days)

@app.route("/complete_day/<int:day>", methods=["POST"])
@login_required
def complete_day(day):

    user_id = session["user_id"]

    existing = Progress.query.filter_by(user_id=user_id, day=day).first()

    if not existing:
        progress = Progress(
            user_id=user_id,
            day=day,
            completed=True
        )
        db.session.add(progress)
        db.session.commit()

    flash("Day Completed!", "success")

    return redirect(url_for("progress"))


@app.route("/admin/edit-plan/<int:day>", methods=["GET","POST"])
@login_required
@admin_required
def edit_plan(day):

    plan = Workout.query.filter_by(day=day).first_or_404()

    if request.method == "POST":

        plan.title = request.form.get("title")
        plan.video_url = request.form.get("video_url")
        plan.meal_image = request.form.get("meal_image")

        plan.veg_breakfast = request.form.get("veg_breakfast")
        plan.veg_lunch = request.form.get("veg_lunch")
        plan.veg_snack = request.form.get("veg_snack")
        plan.veg_dinner = request.form.get("veg_dinner")

        plan.nonveg_breakfast = request.form.get("nonveg_breakfast")
        plan.nonveg_lunch = request.form.get("nonveg_lunch")
        plan.nonveg_snack = request.form.get("nonveg_snack")
        plan.nonveg_dinner = request.form.get("nonveg_dinner")

        plan.exercises = request.form.get("exercises")

        db.session.commit()

        flash("Plan updated successfully", "success")

        return redirect(url_for("admin_plans"))

    return render_template("edit_plan.html", plan=plan)


if __name__ == '__main__':
    app.run(debug=True, port=5000)