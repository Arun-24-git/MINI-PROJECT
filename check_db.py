import mysql.connector
from mysql.connector import Error

# --- Database Configuration ---s 
# IMPORTANT: These values MUST EXACTLY MATCH what is in your app.py file
# AND what your MySQL server requires.
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',            # <-- YOUR MYSQL USERNAME
    'password': 'kmc24-mca-2008',            # <-- YOUR MYSQL PASSWORD (Leave empty if none)
    'database': 'postal' # The name of your database
}

def test_connection():
    """Attempts to connect to the database and prints the result."""
    print("Attempting to connect to the database...")
    conn = None
    try:
        # Establish the connection
        conn = mysql.connector.connect(**DB_CONFIG)
        
        if conn.is_connected():
            print("✅ SUCCESS: Database connection is successful.")
            
            # Optional: Check if tables exist
            cursor = conn.cursor()
            print("\nChecking for tables...")
            cursor.execute("SHOW TABLES;")
            tables = cursor.fetchall()
            if tables:
                print("Found tables:")
                for table in tables:
                    print(f"- {table[0]}")
            else:
                print("⚠️ WARNING: Connection successful, but no tables were found in the database.")
            cursor.close()

        else:
            print("❌ FAILURE: Connection was not established.")
            
    except Error as e:
        print(f"❌ FAILURE: An error occurred.")
        print(f"   Error Code: {e.errno}")
        print(f"   SQLSTATE: {e.sqlstate}")
        print(f"   Message: {e.msg}")
        print("\n--- Troubleshooting Tips ---")
        print("1. Is your MySQL server (from XAMPP, WAMP, etc.) running?")
        print("2. Did you enter the correct 'user' and 'password' in the DB_CONFIG above?")
        print("3. Does the database 'postal_ai_db' exist on your MySQL server?")
        
    finally:
        if conn and conn.is_connected():
            conn.close()
            print("\nConnection closed.")

if __name__ == '__main__':
    test_connection()