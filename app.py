import os
import mysql.connector
import re
from mysql.connector import Error
from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response, jsonify
from functools import wraps
from werkzeug.utils import secure_filename
import cv2
import pytesseract
import numpy as np

# --- IMPORTANT TESSERACT CONFIGURATION ---
# If on Windows, set the path to your tesseract.exe if it's not in your system's PATH
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

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

# --- Helper Functions ---
def get_db_connection():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error as e:
        print(f"Database connection error: {e}")
        return None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- DEFINITIVE IMAGE PROCESSING FUNCTION ---
def process_image_for_address(image_path):
    """
    Processes an image using an advanced pipeline to handle low contrast, shadows,
    and noisy backgrounds by robustly detecting the text block before OCR.
    """
    try:
        image = cv2.imread(image_path)
        if image is None:
            return None, "N/A", "Error: Could not read image file."

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # --- Stage 1: Maximize Contrast and Detect Text Regions ---
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        contrast_enhanced = clahe.apply(gray)
        
        # Use a morphological gradient to find edges and text-like structures.
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        gradient = cv2.morphologyEx(contrast_enhanced, cv2.MORPH_GRADIENT, kernel)
        
        # Apply Otsu's threshold to the gradient image to get a binary map of text regions.
        _, binary = cv2.threshold(gradient, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

        # --- Stage 2: Connect Text and Crop ---
        kernel_wide = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 2))
        closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel_wide)
        
        kernel_tall = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 8))
        closed = cv2.morphologyEx(closed, cv2.MORPH_CLOSE, kernel_tall)
        
        # Find contours of the text block.
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        image_to_process = gray # Default to the full image
        if contours:
            largest_contour = max(contours, key=cv2.contourArea)
            # Check if the found contour is reasonably large
            if cv2.contourArea(largest_contour) > 1000:
                x, y, w, h = cv2.boundingRect(largest_contour)
                padding = 15
                x_start = max(0, x - padding)
                y_start = max(0, y - padding)
                x_end = min(gray.shape[1], x + w + padding)
                y_end = min(gray.shape[0], y + h + padding)
                
                # Crop the ORIGINAL grayscale image for maximum clarity.
                image_to_process = gray[y_start:y_end, x_start:x_end]

        # --- Stage 3: Final Cleaning and OCR ---
        # Apply a final threshold to the clean, cropped image.
        _, final_image = cv2.threshold(image_to_process, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

        # Use PSM 3, Tesseract's fully automatic page segmentation, which is the most robust.
        custom_config = r'-l eng --oem 3 --psm 3'
        extracted_text = pytesseract.image_to_string(final_image, config=custom_config)
        
        if not extracted_text.strip():
            extracted_text = "No text could be extracted."

        # --- Pincode Extraction ---
        pincode = "Not Found"
        if extracted_text:
            cleaned_text_for_search = extracted_text.replace("-", "").replace(" ", "")
            pincodes_found = re.findall(r'\b\d{6}\b', cleaned_text_for_search)
            if pincodes_found:
                pincode = pincodes_found[0]

        return extracted_text.strip(), pincode, "Success"
        
    except Exception as e:
        print(f"CRITICAL ERROR in process_image_for_address for image {image_path}: {e}")
        return None, None, f"Error: A critical failure occurred during image processing."

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

# --- THIS IS THE UPDATED LOGIN FUNCTION WITH FULL DIAGNOSTICS ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password_candidate = request.form['password']

        # ================================================================
        # --- ULTIMATE DEBUGGING BLOCK ---
        # ================================================================
        print("\n\n" + "="*60)
        print("--- ULTIMATE LOGIN DIAGNOSTICS INITIATED ---")
        print(f"Connecting to database with this configuration: {DB_CONFIG}")
        
        conn = get_db_connection()
        if not conn:
            print("DATABASE CONNECTION FAILED!")
            flash('Database service is currently unavailable. Please try again later.', 'danger')
            return render_template('login.html')
        
        print("Database connection successful.")
        cursor = conn.cursor(dictionary=True)

        user = None # Define user as None initially
        try:
            # Let's see the ENTIRE content of the tables
            print("\n--- DUMPING 'staff' TABLE CONTENT ---")
            cursor.execute("SELECT * FROM staff")
            all_staff = cursor.fetchall()
            if all_staff:
                for staff_member in all_staff:
                    print(staff_member)
            else:
                print("!!! The 'staff' table is EMPTY. !!!")

            print("\n--- DUMPING 'login' TABLE CONTENT ---")
            cursor.execute("SELECT * FROM login")
            all_logins = cursor.fetchall()
            if all_logins:
                for login_entry in all_logins:
                    print(login_entry)
            else:
                print("!!! The 'login' table is EMPTY. !!!")
            
            print("\n--- ATTEMPTING TO FIND THE ADMIN USER ---")
            query = """
                SELECT l.user_id, l.username, l.password, l.role, s.staff_name, s.status, s.staff_id
                FROM login l
                JOIN staff s ON l.staff_id = s.staff_id
                WHERE l.username = %s
            """
            cursor.execute(query, (username,))
            user = cursor.fetchone()

            if user:
                print("RESULT: Admin user record was FOUND by the query.")
                print(f"User details found: {user}")
                # Now we check the password
                if user['password'] == password_candidate:
                    print("PASSWORD CHECK: SUCCESS. Passwords match.")
                else:
                    print(f"PASSWORD CHECK: FAILED. Form password '{password_candidate}' does not match DB password '{user['password']}'.")
            else:
                print("RESULT: Admin user record was NOT FOUND by the query.")

            print("="*60 + "\n\n")
        
        except Error as e:
            print(f"AN EXCEPTION OCCURRED: {e}")
            flash(f'An error occurred during login: {e}', 'danger')
            return redirect(url_for('login'))
        finally:
            if cursor: cursor.close()
            if conn and conn.is_connected(): conn.close()
            
        # --- Original Logic (we leave this here to see the final result) ---
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
            else: # role is 'staff'
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

@app.route('/admin/manage-staff', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_staff():
    conn = get_db_connection()
    if not conn:
        flash('Database service is currently unavailable.', 'danger')
        return redirect(url_for('admin_home'))
    
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        
        if request.method == 'POST':
            staff_name = request.form['staff_name']
            phone = request.form['phone']
            username = request.form['username']
            # Storing the plain-text password directly
            password = request.form['password']
            
            try:
                cursor.execute("SELECT username FROM login WHERE username = %s", (username,))
                if cursor.fetchone():
                    flash(f'Username "{username}" already exists. Please choose a different one.', 'danger')
                    return redirect(url_for('manage_staff'))
                
                cursor.execute("INSERT INTO staff (staff_name, phone) VALUES (%s, %s)", (staff_name, phone))
                new_staff_id = cursor.lastrowid
                
                # Inserting the plain-text password into the database
                cursor.execute("INSERT INTO login (username, password, role, staff_id) VALUES (%s, %s, 'staff', %s)", (username, password, new_staff_id))
                
                conn.commit()
                flash(f'Staff member {staff_name} added successfully!', 'success')

            except Error as e:
                conn.rollback()
                if e.errno == 1062:
                    flash(f'Failed to add staff. The username or phone number is already taken.', 'danger')
                else:
                    flash(f'Failed to add staff. Error: {e}', 'danger')
            
            return redirect(url_for('manage_staff'))
        
        cursor.execute("""
            SELECT s.staff_id, s.staff_name, s.phone, s.status, s.joined_date, l.username 
            FROM staff s 
            JOIN login l ON s.staff_id = l.staff_id 
            WHERE l.role = 'staff'
            ORDER BY s.joined_date DESC
        """)
        staff_list = cursor.fetchall()
        return render_template('manage_staff.html', staff_list=staff_list)

    except Error as e:
        flash(f"A database error occurred: {e}", "danger")
        return redirect(url_for('admin_home'))
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

@app.route('/admin/history')
@login_required
@role_required('admin')
def view_sorted_history():
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
    return render_template('upload_capture.html')

@app.route('/staff/process_queue', methods=['POST'])
@login_required
@role_required('staff')
def process_queue():
    uploaded_files = request.files.getlist('images[]')
    processing_results = []
    staff_id = session.get('staff_id')

    if not uploaded_files or uploaded_files[0].filename == '':
        return jsonify({'error': 'No files were provided for processing.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database service is currently unavailable.'}), 500

    cursor = None
    try:
        cursor = conn.cursor()
        for file in uploaded_files:
            result_entry = {'filename': file.filename or "captured_image.jpg"}
            
            if file and allowed_file(file.filename or "image.jpg"):
                filename = secure_filename(file.filename or "captured_image.jpg")
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                
                try:
                    # Corrected the save path variable name
                    file.save(save_path) 
                    sql = "INSERT INTO parcel (image_path, staff_id) VALUES (%s, %s)"
                    cursor.execute(sql, (filename, staff_id))
                    conn.commit()
                    
                    new_parcel_id = cursor.lastrowid
                    address, pincode, status_msg = process_image_for_address(save_path)
                    
                    result_entry.update({
                        'parcel_id': new_parcel_id,
                        'extracted_address': address,
                        'extracted_pincode': pincode,
                        'status': status_msg
                    })

                except Error as db_error:
                    conn.rollback()
                    print(f"Database error for file {filename}: {db_error}")
                    result_entry.update({'status': 'Error: Database insert failed.'})
                except Exception as proc_error:
                    print(f"File save or processing error for {filename}: {proc_error}")
                    result_entry.update({'status': 'Error: Could not save or process file.'})
            else:
                result_entry.update({'status': 'Error: Invalid file type'})
            
            processing_results.append(result_entry)

    except Exception as e:
        print(f"An unexpected error occurred in process_queue: {e}")
        return jsonify({'error': 'An unexpected server error occurred.'}), 500
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

    return jsonify(processing_results)

@app.route('/staff/bins')
@login_required
@role_required('staff')
def view_bins():
    return f"<h1>View Bins Page</h1><p>Welcome, {session.get('name')}!</p>"

@app.route('/staff/sorted-items')
@login_required
@role_required('staff')
def view_sorted_items():
    return f"<h1>View Sorted Items Page</h1><p>Welcome, {session.get('name')}!</p>"

# --- Main execution ---
if __name__ == '__main__':
    app.run(debug=True)