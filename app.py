import os
import mysql.connector
from mysql.connector import Error
from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response, jsonify
from functools import wraps
from werkzeug.utils import secure_filename

# --- AI & Image Processing Imports ---
import cv2
import pytesseract

# --- Application Setup ---
app = Flask(__name__)
app.secret_key = 'a_very_secure_and_random_secret_key_for_sessions'

# --- File Upload & AI Configuration ---
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- Database Configuration ---
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'kmc24-mca-2008',
    'database': 'postal'
}

# --- Helper Functions ---
def get_db_connection():
    """Establishes a connection to the database."""
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error:
        return None

def allowed_file(filename):
    """Checks if a filename has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_image_for_address(image_path):
    """
    Loads an image, processes it with OpenCV, and extracts text with Tesseract.
    Returns the full text, the found pincode, and a status message.
    """
    try:
        image = cv2.imread(image_path)
        if image is None:
            return None, "N/A", "Error: Could not read image file."

        # Convert to grayscale for better processing
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Apply adaptive thresholding to handle different lighting conditions
        thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY, 11, 2)

        # Configure Pytesseract for address reading (psm 6 assumes a uniform block of text)
        custom_config = r'--oem 3 --psm 6'
        extracted_text = pytesseract.image_to_string(thresh, config=custom_config)

        # Basic pincode extraction logic (finds the first 6-digit number)
        pincode = "Not Found"
        if extracted_text:
            for word in extracted_text.replace("-", "").replace(" ", "").split():
                if word.isdigit() and len(word) == 6:
                    pincode = word
                    break
        else:
            extracted_text = "No text found in image."

        return extracted_text, pincode, "Success"
    except Exception as e:
        print(f"Error processing image {image_path}: {e}")
        return None, None, f"Error: Tesseract or OpenCV failed."

# --- Decorators for Access Control ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('You must be logged in to view this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(required_role):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if session.get('role') != required_role:
                flash(f'Access denied. You need to be an {required_role}.', 'danger')
                if 'role' in session:
                    return redirect(url_for(f"{session['role']}_home"))
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return wrapper
    return decorator

# --- Browser Cache Control ---
@app.after_request
def add_header_no_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

# --- Public Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password_candidate = request.form['password']

        conn = get_db_connection()
        if not conn:
            flash('Database service is currently unavailable. Please try again later.', 'danger')
            return render_template('login.html')

        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            # This single query now handles both 'admin' and 'staff' roles
            query = """
                SELECT l.user_id, l.username, l.password, l.role, s.staff_name, s.status
                FROM login l
                JOIN staff s ON l.staff_id = s.staff_id
                WHERE l.username = %s
            """
            cursor.execute(query, (username,))
            user = cursor.fetchone()

            # Check if user exists and password is correct
            if user and user['password'] == password_candidate:
                # For staff, additionally check if their status is 'active'
                if user['role'] == 'staff' and user.get('status') != 'active':
                    flash('Your account is inactive. Please contact an administrator.', 'danger')
                    return redirect(url_for('login'))
                
                # If login is successful, store user info in session
                session.clear()
                session['user_id'] = user['user_id']
                session['username'] = user['username']
                session['role'] = user['role']
                session['name'] = user['staff_name']
                flash(f'Welcome back, {session["name"]}!', 'success')
                
                # Redirect based on the user's role
                if user['role'] == 'admin':
                    return redirect(url_for('admin_home'))
                else: # role is 'staff'
                    return redirect(url_for('staff_home'))
            else:
                # If user not found or password incorrect
                flash('Invalid username or password.', 'danger')
                return redirect(url_for('login'))

        except Error as e:
            flash(f'An error occurred during login: {e}', 'danger')
            return redirect(url_for('login'))
        finally:
            if cursor: cursor.close()
            if conn: conn.close()

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    resp = make_response(redirect(url_for('login')))
    resp.set_cookie('session', '', expires=0)
    return resp

# --- Admin Routes ---
@app.route('/admin/home')
@login_required
@role_required('admin')
def admin_home():
    return render_template('admin_home.html', user_name=session.get('name'))

@app.route('/admin/manage-staff', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_staff():
    conn = get_db_connection()
    if not conn:
        flash('Database service is currently unavailable.', 'danger')
        return redirect(url_for('admin_home'))
    
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        staff_id = request.form['staff_id']
        staff_name = request.form['staff_name']
        phone = request.form['phone']
        username = request.form['username']
        password = request.form['password']
        try:
            conn.start_transaction()
            # Note: We assume the status defaults to 'active' as per the schema
            cursor.execute("INSERT INTO staff (staff_id, staff_name, phone) VALUES (%s, %s, %s)", (staff_id, staff_name, phone))
            cursor.execute("INSERT INTO login (username, password, role, staff_id) VALUES (%s, %s, 'staff', %s)", (username, password, staff_id))
            conn.commit()
            flash(f'Staff member {staff_name} added successfully!', 'success')
        except Error as e:
            conn.rollback()
            flash(f'Failed to add staff. Error: {e}', 'danger')
        finally:
            if cursor: cursor.close()
            if conn: conn.close()
        return redirect(url_for('manage_staff'))
    
    # This query for GET request lists all users, including the admin profile
    cursor.execute("""
        SELECT s.staff_id, s.staff_name, s.phone, s.status, s.joined_date, l.username 
        FROM staff s 
        JOIN login l ON s.staff_id = l.staff_id 
        ORDER BY s.joined_date DESC
    """)
    staff_list = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('manage_staff.html', staff_list=staff_list)

@app.route('/admin/history')
@login_required
@role_required('admin')
def view_sorted_history():
    # Placeholder for future implementation
    return f"<h1>View Sorted History Page</h1><p>Welcome, {session.get('name')}!</p>"

# --- Staff Routes ---
@app.route('/staff/home')
@login_required
@role_required('staff')
def staff_home():
    return render_template('staff_home.html', user_name=session.get('name'))

@app.route('/staff/upload')
@login_required
@role_required('staff')
def upload_capture():
    # This route now simply serves the feature-rich upload page with JavaScript.
    return render_template('upload_capture.html')

@app.route('/staff/process_queue', methods=['POST'])
@login_required
@role_required('staff')
def process_queue():
    uploaded_files = request.files.getlist('images[]')
    processing_results = []

    if not uploaded_files or uploaded_files[0].filename == '':
        return jsonify({'error': 'No files were provided for processing.'}), 400

    for file in uploaded_files:
        result_entry = {'filename': file.filename or "captured_image.jpg"}
        if file and allowed_file(file.filename or "image.jpg"):
            filename = secure_filename(file.filename or "captured_image.jpg")
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(save_path)

            address, pincode, status = process_image_for_address(save_path)
            
            result_entry.update({
                'extracted_address': address,
                'extracted_pincode': pincode,
                'status': status
            })
        else:
            result_entry.update({
                'extracted_address': None,
                'extracted_pincode': None,
                'status': 'Error: Invalid file type'
            })
        processing_results.append(result_entry)

    return jsonify(processing_results)

@app.route('/staff/bins')
@login_required
@role_required('staff')
def view_bins():
    # Placeholder for future implementation
    return f"<h1>View Bins Page</h1><p>Welcome, {session.get('name')}!</p>"

@app.route('/staff/sorted-items')
@login_required
@role_required('staff')
def view_sorted_items():
    # Placeholder for future implementation
    return f"<h1>View Sorted Items Page</h1><p>Welcome, {session.get('name')}!</p>"

# --- Main execution ---
if __name__ == '__main__':
    app.run(debug=True)