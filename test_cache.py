from flask import Flask, session, redirect, url_for, request, make_response

app = Flask(__name__)
app.secret_key = 'a_very_secret_key'

# Using the same robust cache-control headers
@app.after_request
def add_header_no_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

@app.route('/')
def index():
    return '<h1>Minimal Test App</h1><a href="/login">Go to Login</a>'

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        session['user'] = 'testuser'
        return redirect(url_for('protected'))
    # A simple HTML form
    return '<form method="post"><button type="submit">Log In</button></form>'

@app.route('/protected')
def protected():
    if 'user' not in session:
        # If no user in session, redirect to login
        return redirect(url_for('login'))
    return '<h1>This is the PROTECTED page.</h1><a href="/logout">Logout</a>'

# Using the same robust logout
@app.route('/logout')
def logout():
    session.clear()
    resp = make_response(redirect(url_for('login')))
    resp.set_cookie('session', '', expires=0)
    return resp

if __name__ == '__main__':
    # Run on a different port (5001) to avoid any browser conflicts
    app.run(debug=True, port=5001)