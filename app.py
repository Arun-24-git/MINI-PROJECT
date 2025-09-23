import os
import mysql.connector
import re
from mysql.connector import Error
from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response, jsonify
from functools import wraps
from werkzeug.utils import secure_filename
import cv2
import numpy as np
import easyocr

# --- Application Setup ---
app = Flask(__name__)
app.secret_key = 'a_very_secure_and_random_secret_key_for_sessions'
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

# --- GLOBAL EASYOCR READER INITIALIZATION ---
print("Loading EasyOCR model into memory... (This may take a moment)")
try:
    OCR_READER = easyocr.Reader(['en'], gpu=False)
    print("EasyOCR model loaded successfully.")
except Exception as e:
    OCR_READER = None
    print(f"CRITICAL ERROR: Failed to load EasyOCR model: {e}")


# --- Helper Functions ---
def get_db_connection():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error as e:
        print(f"Database connection error: {e}")
        return None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- REVISED, MORE ACCURATE IMAGE PROCESSING FUNCTION ---
def process_image_for_address(image_path):
    """
    This enhanced function uses OpenCV for image pre-processing and a more
    accurate regular expression with word boundaries to correctly isolate the pincode.
    """
    if OCR_READER is None:
        return "N/A", "N/A", "Error: OCR model is not loaded."

    try:
        # 1. Read and pre-process the image for better OCR results
        img = cv2.imread(image_path)
        gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        processed_img = cv2.adaptiveThreshold(
            gray_img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )

        # 2. Pass the processed image data directly to EasyOCR
        results = OCR_READER.readtext(processed_img, detail=0, paragraph=True)
        extracted_text = "\n".join(results)
        
        print("\n--- EasyOCR Raw Extracted Text (from processed image) ---")
        print(f"'{extracted_text}'")
        print("----------------------------------------------------------")
        
        if not extracted_text.strip():
            extracted_text = "No text could be extracted."

        # --- Pincode Extraction (CORRECTED LOGIC) ---
        pincode = "Not Found"
        if extracted_text:
            pincodes_found = re.findall(r'\b\d{6}\b', extracted_text)
            
            print(f"--- All 6-digit 'whole word' numbers found: {pincodes_found} ---")

            if pincodes_found:
                pincode = pincodes_found[-1] 
                print(f"--- SUCCESS: Selected the last pincode: {pincode} ---")
            else:
                print("--- INFO: No standalone 6-digit pincode found. Trying fallback method. ---")
                cleaned_text = extracted_text.replace(" ", "").replace("-", "")
                pincodes_found = re.findall(r'\d{6}', cleaned_text)
                if pincodes_found:
                    pincode = pincodes_found[-1]
                    print(f"--- SUCCESS (Fallback): Selected the last pincode: {pincode} ---")
                else:
                    print(f"--- FAILURE: No 6-digit numbers found even with fallback. ---")

        return extracted_text.strip(), pincode, "Success"
        
    except Exception as e:
        print(f"CRITICAL ERROR in process_image_for_address for image {image_path}: {e}")
        return "Error during processing", "Error", f"A critical failure occurred during image processing: {e}"

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
        cursor = conn.cursor(dictionary=True)
        try:
            query = """
                SELECT l.user_id, l.username, l.password, l.role, s.staff_name, s.status, s.staff_id
                FROM login l
                JOIN staff s ON l.staff_id = s.staff_id
                WHERE l.username = %s
            """
            cursor.execute(query, (username,))
            user = cursor.fetchone()
        finally:
            cursor.close()
            conn.close()
            
        if user and user['password'] == password_candidate:
            if user['role'] == 'staff' and user.get('status') != 'active':
                flash('Your account is inactive. Please contact an administrator.', 'danger')
                return redirect(url_for('login'))
            session.clear()
            session['user_id'] = user['user_id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['name'] = user['staff_name']
            session['staff_id'] = user['staff_id']
            flash(f'Welcome back, {session["name"]}!', 'success')
            if user['role'] == 'admin':
                return redirect(url_for('admin_home'))
            else:
                return redirect(url_for('staff_home'))
        else:
            flash('Invalid username or password.', 'danger')
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been successfully logged out.', 'success')
    resp = make_response(redirect(url_for('login')))
    resp.set_cookie('session', '', expires=0)
    return resp

# --- Admin Routes ---
@app.route('/admin/home')
@login_required
@role_required('admin')
def admin_home():
    return render_template('admin_home.html', user_name=session.get('name'))

# --- THIS IS THE UPDATED FUNCTION ---
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
        staff_name = request.form['staff_name'].strip()
        phone = request.form['phone'].strip()
        username = request.form['username'].strip()
        password = request.form['password'] # Don't strip password
        
        errors = []
        # Rule 1: Validate Staff Name (letters and spaces, 2-50 chars)
        if not re.match(r"^[a-zA-Z\s]{2,50}$", staff_name):
            errors.append("Full Name must be between 2 and 50 characters and contain only letters and spaces.")
            
        # Rule 2: Validate Phone Number (must be 10-13 digits)
        if not re.match(r"^\d{10,13}$", phone):
            errors.append("Phone Number must contain only digits and be between 10 and 13 numbers long.")
            
        # Rule 3: Validate Username (alphanumeric + underscore, 4-20 chars)
        if not re.match(r"^[a-zA-Z0-9_]{4,20}$", username):
            errors.append("Username must be 4-20 characters long and contain only letters, numbers, and underscores.")

        # Rule 4: Validate Password (minimum 6 characters)
        if len(password) < 6:
            errors.append("Password must be at least 6 characters long.")

        if errors:
            # If there are any validation errors, flash them and re-render the page
            for error in errors:
                flash(error, 'danger')
        else:
            # --- If validation passes, proceed to database logic ---
            try:
                # Check for existing username
                cursor.execute("SELECT username FROM login WHERE username = %s", (username,))
                if cursor.fetchone():
                    flash(f'Username "{username}" already exists.', 'danger')
                else:
                    # Check for existing phone number
                    cursor.execute("SELECT phone FROM staff WHERE phone = %s", (phone,))
                    if cursor.fetchone():
                        flash(f'Phone number "{phone}" is already in use.', 'danger')
                    else:
                        cursor.execute("INSERT INTO staff (staff_name, phone) VALUES (%s, %s)", (staff_name, phone))
                        new_staff_id = cursor.lastrowid
                        cursor.execute("INSERT INTO login (username, password, role, staff_id) VALUES (%s, %s, 'staff', %s)", (username, password, new_staff_id))
                        conn.commit()
                        flash(f'Staff member {staff_name} added successfully!', 'success')
                        return redirect(url_for('manage_staff')) # Redirect only on success
            except Error as e:
                conn.rollback()
                flash(f'Failed to add staff due to a database error: {e}', 'danger')
    
    # Fetch staff list for both GET requests and failed POST requests
    try:
        cursor.execute("""
            SELECT s.staff_id, s.staff_name, s.phone, s.status, s.joined_date, l.username 
            FROM staff s JOIN login l ON s.staff_id = l.staff_id 
            WHERE l.role = 'staff' ORDER BY s.joined_date DESC
        """)
        staff_list = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
        
    return render_template('manage_staff.html', staff_list=staff_list)


@app.route('/admin/history')
@login_required
@role_required('admin')
def view_sorted_history():
    return "<h1>View Sorted History Page</h1>"

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
        original_filename = file.filename or "captured_image.jpg"
        result_entry = {'original_filename': original_filename}
        
        if file and allowed_file(original_filename):
            unique_filename = f"{os.path.splitext(secure_filename(original_filename))[0]}_{os.urandom(8).hex()}.jpg"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            
            try:
                file.save(save_path)
                address, pincode, status_msg = process_image_for_address(save_path)
                result_entry.update({
                    'image_path': unique_filename,
                    'extracted_address': address,
                    'extracted_pincode': pincode,
                    'status': status_msg
                })
            except Exception as proc_error:
                result_entry.update({'status': f'Error: Could not process file: {proc_error}'})
        else:
            result_entry.update({'status': 'Error: Invalid file type'})
        
        processing_results.append(result_entry)

    return jsonify(processing_results)

@app.route('/staff/finalize_parcels', methods=['POST'])
@login_required
@role_required('staff')
def finalize_parcels():
    data = request.get_json()
    parcels_to_save = data.get('parcels')
    staff_id = session.get('staff_id')

    if not parcels_to_save:
        return jsonify({'success': False, 'message': 'No parcel data provided.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database service is currently unavailable.'}), 500

    cursor = conn.cursor()
    errors = []
    success_count = 0
    
    try:
        for parcel in parcels_to_save:
            image_path = parcel.get('image_path')
            pincode = parcel.get('pincode')
            address = parcel.get('address')
            
            db_pincode = pincode if pincode and re.match(r'^\d{6}$', pincode) else None
            db_address = address if address else None

            try:
                sql = "INSERT INTO parcel (image_path, staff_id, pincode, full_address, status) VALUES (%s, %s, %s, %s, %s)"
                cursor.execute(sql, (image_path, staff_id, db_pincode, db_address, 'sorted'))
                success_count += 1
            except Error as e:
                print(f"!!!!! DATABASE ERROR FOR '{image_path}': {e} !!!!!")
                errors.append(f"DB error for {image_path}: {e}")
        
        if errors:
            conn.rollback()
            return jsonify({
                'success': False, 
                'message': 'Some records failed to save. No data was committed.', 
                'errors': [str(e) for e in errors] 
            }), 500
        else:
            conn.commit()
            return jsonify({
                'success': True, 
                'message': f'Successfully saved {success_count} parcels.'
            })
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'An unexpected error occurred: {e}'}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/staff/bins')
@login_required
@role_required('staff')
def view_bins():
    return "<h1>View Bins Page</h1>"

@app.route('/staff/sorted-items')
@login_required
@role_required('staff')
def view_sorted_items():
    return "<h1>View Sorted Items Page</h1>"

# --- Main execution ---
if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)