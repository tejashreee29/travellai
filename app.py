from flask import Flask, render_template, request, redirect, session, jsonify, flash
import pandas as pd
from destination_model import recommend_destinations, generate_itinerary
import database as db
import os
import requests
import re
import warnings
import qrcode
import io
import base64
from datetime import datetime, timedelta
from functools import wraps
import secrets

# Security imports
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    LIMITER_AVAILABLE = True
except ImportError:
    LIMITER_AVAILABLE = False
    print("⚠ Flask-Limiter not installed. Install with: pip install Flask-Limiter")

try:
    from flask_wtf.csrf import CSRFProtect
    CSRF_AVAILABLE = True
except ImportError:
    CSRF_AVAILABLE = False
    print("⚠ Flask-WTF not installed. Install with: pip install Flask-WTF")

try:
    from flask_talisman import Talisman
    TALISMAN_AVAILABLE = True
except ImportError:
    TALISMAN_AVAILABLE = False
    print("⚠ Flask-Talisman not installed. Install with: pip install flask-talisman")

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✓ Environment variables loaded from .env file")
except ImportError:
    print("⚠ python-dotenv not installed. Using system environment variables only.")
    print("  Install with: pip install python-dotenv")

# Suppress FutureWarning for deprecated google.generativeai
warnings.filterwarnings('ignore', category=FutureWarning, message='.*google.generativeai.*')

# Try to import Google Generative AI for Gemini
# Note: google.generativeai is deprecated, but still works
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    genai = None

app = Flask(__name__)

# Use a stable secret key (from .env in production)
SECRET_KEY = os.environ.get("SECRET_KEY", "travelplan_dev_secret_key_stable_fallback")
if SECRET_KEY == "travelplan_dev_secret_key_stable_fallback":
    print("⚠ WARNING: Using default SECRET_KEY. Set SECRET_KEY in .env for production!")

app.secret_key = SECRET_KEY

# Detect if running in production (HTTPS) or development (HTTP)
IS_PRODUCTION = os.environ.get('FLASK_ENV') == 'production'

# Security Configuration
app.config.update(
    # Session security
    # SESSION_COOKIE_SECURE should be True only in production (HTTPS).
    # Setting it True on HTTP (localhost) causes the browser to never send
    # the session cookie, which breaks login completely.
    SESSION_COOKIE_SECURE=IS_PRODUCTION,  # True only in production (HTTPS)
    SESSION_COOKIE_HTTPONLY=True,  # Prevent JavaScript access to session cookie
    SESSION_COOKIE_SAMESITE='Lax',  # CSRF protection
    PERMANENT_SESSION_LIFETIME=timedelta(hours=24),  # Session timeout
    
    # CSRF Protection
    WTF_CSRF_ENABLED=True,
    WTF_CSRF_TIME_LIMIT=None,  # No time limit for CSRF tokens
    
    # Security headers
    SEND_FILE_MAX_AGE_DEFAULT=31536000,  # Cache static files for 1 year
)

# Initialize CSRF Protection
if CSRF_AVAILABLE:
    csrf = CSRFProtect(app)
    print("✓ CSRF Protection enabled")
else:
    csrf = None

def csrf_exempt_json_routes():
    """Exempt JSON API routes from CSRF - called after routes are defined"""
    if csrf:
        # These routes receive JSON via fetch() and cannot include CSRF tokens easily
        json_api_routes = [
            'add_to_wallet', 'remove_from_wallet', 'save_destination',
            'chatbot_api', 'chatbot'
        ]
        for route_name in json_api_routes:
            try:
                view = app.view_functions.get(route_name)
                if view:
                    csrf.exempt(view)
            except Exception:
                pass

# Initialize Rate Limiter
if LIMITER_AVAILABLE:
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["200 per day", "50 per hour"],
        storage_uri="memory://",
    )
    print("✓ Rate Limiting enabled")
else:
    limiter = None

# Initialize Talisman for HTTPS enforcement (disabled in development)
if TALISMAN_AVAILABLE and os.environ.get('FLASK_ENV') == 'production':
    csp = {
        'default-src': ["'self'"],
        'script-src': ["'self'", "'unsafe-inline'", 'https://cdn.jsdelivr.net', 'https://unpkg.com'],
        'style-src': ["'self'", "'unsafe-inline'", 'https://fonts.googleapis.com', 'https://cdn.jsdelivr.net'],
        'font-src': ["'self'", 'https://fonts.gstatic.com', 'data:'],
        'img-src': ["'self'", 'data:', 'https:', 'http:'],
        'connect-src': ["'self'", 'https://api.openweathermap.org', 'https://api.exchangerate-api.com'],
    }
    talisman = Talisman(
        app,
        force_https=True,
        strict_transport_security=True,
        content_security_policy=csp,
        content_security_policy_nonce_in=['script-src']
    )
    print("✓ HTTPS enforcement enabled (Production mode)")
else:
    # In development, just add security headers without forcing HTTPS
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        return response
    print("✓ Security headers enabled (Development mode)")

# API Keys (set these as environment variables or use free APIs)
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "")
CURRENCY_API_KEY = os.environ.get("CURRENCY_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
HERE_API_KEY = os.environ.get("HERE_API_KEY", "")

# Configure Gemini API if available
if GEMINI_AVAILABLE and GEMINI_API_KEY and GEMINI_API_KEY.strip():
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        print("✓ Gemini API configured successfully")
    except Exception as e:
        print(f"Warning: Could not configure Gemini API: {e}")
        GEMINI_API_KEY = ""  # Clear invalid key

# ---------------------------------------------------
# Load datasets
# ---------------------------------------------------
food_df = pd.read_csv("food_dataset.csv")

# If using separate transport datasets
try:
    bus_df = pd.read_csv("/Users/tejashreesuvarna/Downloads/transport/bus_routes.csv")
    road_df = pd.read_csv("/Users/tejashreesuvarna/Downloads/transport/road_segments.csv")
    traffic_df = pd.read_csv("/Users/tejashreesuvarna/Downloads/transport/traffic_flow_data.csv")
    commuter_df = pd.read_csv("/Users/tejashreesuvarna/Downloads/transport/commuter_patterns.csv")
except:
    # Fallback if transport files don't exist
    bus_df = pd.DataFrame()
    road_df = pd.DataFrame()
    traffic_df = pd.DataFrame()
    commuter_df = pd.DataFrame()

# ---------------------------------------------------
# Landing Page
# ---------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

# ---------------------------------------------------
# Login
# ---------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute") if LIMITER_AVAILABLE else lambda f: f
def login():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        
        # Input validation
        if not username or not password:
            error = "Please provide both username and password"
        else:
            user = db.verify_user(username, password)
            if user:
                # Regenerate session to prevent session fixation
                session.clear()
                session["user_id"] = user["id"]
                session["user"] = user["username"]
                session.permanent = True  # Use permanent session with timeout
                return redirect("/dashboard")
            else:
                error = "Invalid username or password"

    return render_template("login.html", error=error)

# ---------------------------------------------------
# Signup
# ---------------------------------------------------
@app.route("/signup", methods=["GET", "POST"])
@limiter.limit("3 per hour") if LIMITER_AVAILABLE else lambda f: f
def signup():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        email = request.form.get("email", "").strip() or None
        
        # Input validation
        if not username or not password:
            error = "Please provide both username and password"
        elif len(username) < 3:
            error = "Username must be at least 3 characters long"
        elif len(username) > 50:
            error = "Username must be less than 50 characters"
        elif not re.match(r'^[a-zA-Z0-9_]+$', username):
            error = "Username can only contain letters, numbers, and underscores"
        else:
            # Validate password strength
            is_valid, message = db.validate_password_strength(password)
            if not is_valid:
                error = message
            else:
                user_id = db.create_user(username, password, email)
                if user_id:
                    flash("Account created successfully! Please log in.", "success")
                    return redirect("/login")
                else:
                    error = "Username already exists. Please choose a different one."

    return render_template("signup.html", error=error)

# ---------------------------------------------------
# Chatbot Test Page
# ---------------------------------------------------
@app.route("/chatbot-test")
def chatbot_test():
    """Diagnostic page for chatbot troubleshooting"""
    return render_template("chatbot_diagnostic.html")

@app.route("/chatbot-debug")
def chatbot_debug():
    if "user_id" not in session:
        return redirect("/login")
    return render_template("chatbot_debug.html", user=session["user"])

# ---------------------------------------------------
# Logout
# ---------------------------------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ---------------------------------------------------
# Dashboard
# ---------------------------------------------------
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    user = db.get_user_by_id(user_id)
    preferences = db.get_preferences(user_id)
    travel_history = db.get_travel_history(user_id, limit=5)
    saved_destinations = db.get_saved_destinations(user_id)

    return render_template(
        "dashboard.html",
        user=session["user"],
        user_id=user_id,
        preferences=preferences,
        travel_history=travel_history,
        saved_destinations=saved_destinations
    )

# ---------------------------------------------------
# AI Destinations Page
# ---------------------------------------------------
@app.route("/destinations", methods=["GET", "POST"])
def destinations():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    results = None
    itinerary = None
    selected_city = None
    error = None
    
    # Get travel_type and budget from session or request
    travel_type = session.get("last_travel_type", "")
    budget = session.get("last_budget", "")

    if request.method == "POST":
        print(f"POST request received. Form keys: {list(request.form.keys())}")
        
        if "travel_type" in request.form:
            # Step 1: Get recommendations
            travel_type = request.form["travel_type"]
            budget = request.form["budget"]
            
            # Store in session for persistence
            session["last_travel_type"] = travel_type
            session["last_budget"] = budget
            
            # Save preferences
            db.save_preferences(user_id, travel_type=travel_type, budget_preference=budget)
            
            # AI recommendation
            results = recommend_destinations(travel_type, budget)
            print(f"Recommendations generated: {len(results) if results is not None else 0} results")
            
        elif "selected_city" in request.form:
            # Step 2: Generate itinerary for selected city
            selected_city = request.form.get("selected_city", "").strip()
            start_date = request.form.get("start_date", "").strip()
            end_date = request.form.get("end_date", "").strip()
            travel_type = request.form.get("travel_type", session.get("last_travel_type", ""))
            budget = request.form.get("budget", session.get("last_budget", ""))
            
            print(f"Creating itinerary for '{selected_city}', dates: '{start_date}' to '{end_date}'")
            print(f"Form data - selected_city: '{selected_city}', start_date: '{start_date}', end_date: '{end_date}'")
            
            try:
                # Validate dates
                if not start_date or not end_date:
                    error = "Please select both start and end dates."
                    print(f"Missing dates - start: '{start_date}', end: '{end_date}'")
                else:
                    # Validate date format and logic
                    from datetime import datetime
                    try:
                        start = datetime.strptime(start_date, "%Y-%m-%d")
                        end = datetime.strptime(end_date, "%Y-%m-%d")
                        
                        if end < start:
                            error = "End date must be after start date."
                        elif (end - start).days > 30:
                            error = "Itinerary cannot exceed 30 days. Please select a shorter date range."
                        else:
                            # Generate itinerary
                            try:
                                itinerary = generate_itinerary(selected_city, start_date, end_date)
                                
                                if itinerary and len(itinerary) > 0:
                                    # Save to travel history
                                    try:
                                        db.add_travel_history(user_id, selected_city, travel_type, budget, start_date, end_date)
                                    except Exception as db_error:
                                        print(f"Warning: Could not save to travel history: {db_error}")
                                    
                                    # Clear results after itinerary is created so user sees the itinerary
                                    results = None
                                    print(f"✓ Itinerary generated successfully: {len(itinerary)} days for {selected_city}")
                                    print(f"  Itinerary content: {itinerary[:2]}...")  # Print first 2 days
                                else:
                                    error = "Failed to generate itinerary. Please try again."
                                    print("✗ Itinerary generation returned empty result")
                                    selected_city = None  # Clear selected_city if generation failed
                            except Exception as gen_error:
                                error = f"Error generating itinerary: {str(gen_error)}"
                                import traceback
                                traceback.print_exc()
                                print(f"Itinerary generation error: {gen_error}")
                    except ValueError as e:
                        error = f"Invalid date format. Please use YYYY-MM-DD format. Error: {str(e)}"
                        print(f"Date parsing error: {e}")
            except Exception as e:
                error = f"Error creating itinerary: {str(e)}"
                import traceback
                traceback.print_exc()
                print(f"General error in itinerary creation: {e}")

    # Debug output
    print(f"=== Rendering template ===")
    print(f"  results: {results is not None} ({len(results) if results is not None else 0} items)")
    print(f"  itinerary: {itinerary is not None} ({len(itinerary) if itinerary else 0} days)")
    print(f"  selected_city: '{selected_city}'")
    print(f"  error: {error}")
    if itinerary:
        print(f"  Itinerary preview: Day 1 = {itinerary[0] if len(itinerary) > 0 else 'N/A'}")

    return render_template(
        "destinations.html",
        results=results,
        itinerary=itinerary,
        selected_city=selected_city,
        travel_type=travel_type or "",
        budget=budget or "",
        user=session["user"],
        error=error
    )

# ---------------------------------------------------
# Save Destination
# ---------------------------------------------------
@app.route("/save_destination", methods=["POST"])
def save_destination():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Not logged in"}), 401
    
    data = request.json
    user_id = session["user_id"]
    db.save_destination(
        user_id,
        data["city"],
        data["country"],
        data.get("score", 0),
        data.get("travel_type", ""),
        data.get("description", ""),
        data.get("ideal_time", "")
    )
    return jsonify({"success": True})

# ---------------------------------------------------
# Itinerary Generator Page (Separate from Destinations)
# ---------------------------------------------------
def generate_gemini_itinerary(city, start_date, end_date):
    """
    Generate a rich, city-specific itinerary using Gemini AI.
    Returns a list of day-dicts compatible with the itinerary template.
    Falls back to the CSV-dataset generator if Gemini is unavailable.
    """
    from datetime import datetime
    import json

    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    if GEMINI_AVAILABLE and GEMINI_API_KEY:
        try:
            genai.configure(api_key=GEMINI_API_KEY)
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end   = datetime.strptime(end_date,   "%Y-%m-%d")
            days  = (end - start).days + 1

            prompt = f"""You are a world-class travel guide writer creating a detailed, practical {days}-day itinerary for {city}.

CRITICAL RULES — follow every single one:
1. Every activity MUST name the EXACT place: specific museum, temple, market, street, neighbourhood, restaurant, café, viewpoint, or park. Never say "a local museum" — say "the National Museum of India" or "Chhatrapati Shivaji Maharaj Vastu Sangrahalaya".
2. Every entry must include a PRACTICAL TIP: opening hours, entry fee, best time to visit, or how to get there by local transport.
3. EVENING must always recommend a SPECIFIC restaurant or food street with the name, what dish to order, and why it's famous.
4. Include EXTRA ACTIVITY ideas (1-2 short options) after the main plan for flexible travellers.
5. Vary the days — no repeated places. Mix iconic sightseeing, local neighbourhood walks, food experiences, cultural/religious sites, markets, and nature/parks.
6. Cover different parts of {city} across the days (e.g. different districts, areas).
7. All places MUST actually exist in {city}. Do not invent places.

Format each day's morning, afternoon, and evening as a flowing paragraph (2-4 sentences), NOT bullet points.

Return ONLY valid JSON — no markdown fences, no extra text — in this exact format:
{{
  "days": [
    {{
      "day": 1,
      "morning": "Visit [EXACT PLACE NAME]. [What to see/do there]. [Practical tip: hours/entry/transport]. Extra: [1-2 nearby quick options].",
      "afternoon": "Head to [EXACT PLACE NAME] in [NEIGHBOURHOOD/AREA]. [What makes it special]. [Practical tip]. Try also: [nearby option].",
      "evening": "Dinner at [EXACT RESTAURANT/FOOD STREET NAME]. Order [SPECIFIC DISH(ES)] — [why it's famous or what makes it unique]. [Location or how to find it].",
      "highlights": "[Theme of the day in one punchy line]"
    }}
  ]
}}"""

            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(prompt)
            raw = response.text.strip()

            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            data = json.loads(raw)
            result = []
            for i, d in enumerate(data.get("days", [])[:days]):
                date_str = (start + __import__('datetime').timedelta(days=i)).strftime("%Y-%m-%d")
                result.append({
                    "Day": d.get("day", i + 1),
                    "Date": date_str,
                    "City": city,
                    "Morning": d.get("morning", ""),
                    "Afternoon": d.get("afternoon", ""),
                    "Evening": d.get("evening", ""),
                    "Highlights": d.get("highlights", ""),
                    "ai_powered": True
                })

            if result:
                print(f"✓ Gemini generated {len(result)}-day itinerary for {city}")
                return result

        except Exception as e:
            print(f"Gemini itinerary error: {e} — falling back to dataset/template")

    # Fallback to CSV-dataset or template generator
    return generate_itinerary(city, start_date, end_date)


@app.route("/itinerary", methods=["GET", "POST"])
def itinerary():
    if "user_id" not in session:
        return redirect("/login")
    
    user_id = session["user_id"]
    itinerary = None
    # Pre-fill city from URL query param (e.g., when coming from Destinations page)
    city = request.args.get("city", "").strip() or None
    error = None
    
    if request.method == "POST":
        print(f"POST request received for itinerary generation")
        
        # Extract form data
        city = request.form.get("city", "").strip()
        start_date = request.form.get("start_date", "").strip()
        end_date = request.form.get("end_date", "").strip()
        
        print(f"City: '{city}', Start: '{start_date}', End: '{end_date}'")
        
        try:
            # Validate inputs
            if not city:
                error = "Please enter a destination city."
                print(f"Error: Missing city")
            elif not start_date or not end_date:
                error = "Please select both start and end dates."
                print(f"Error: Missing dates - start: '{start_date}', end: '{end_date}'")
            else:
                # Validate date format and logic
                from datetime import datetime
                try:
                    start = datetime.strptime(start_date, "%Y-%m-%d")
                    end = datetime.strptime(end_date, "%Y-%m-%d")
                    
                    if end < start:
                        error = "End date must be after start date."
                        print(f"Error: End date before start date")
                    elif (end - start).days > 30:
                        error = "Itinerary cannot exceed 30 days. Please select a shorter date range."
                        print(f"Error: Date range too long")
                    else:
                        # Generate itinerary
                        print(f"Generating itinerary for {city} from {start_date} to {end_date}")
                        try:
                            itinerary = generate_gemini_itinerary(city, start_date, end_date)
                            
                            if itinerary and len(itinerary) > 0:
                                # Save to travel history
                                try:
                                    db.add_travel_history(user_id, city, "", "", start_date, end_date)
                                    print(f"✓ Saved to travel history")
                                except Exception as db_error:
                                    print(f"Warning: Could not save to travel history: {db_error}")
                                
                                print(f"✓ Itinerary generated successfully: {len(itinerary)} days")
                            else:
                                error = "Failed to generate itinerary. Please try again."
                                print(f"✗ Itinerary generation returned empty result")
                        except Exception as gen_error:
                            error = f"Error generating itinerary: {str(gen_error)}"
                            import traceback
                            traceback.print_exc()
                            print(f"Itinerary generation error: {gen_error}")
                except ValueError as e:
                    error = f"Invalid date format. Please use the date picker. Error: {str(e)}"
                    print(f"Date parsing error: {e}")
        except Exception as e:
            error = f"Error creating itinerary: {str(e)}"
            import traceback
            traceback.print_exc()
            print(f"General error in itinerary creation: {e}")
    
    # Debug output
    print(f"=== Rendering itinerary template ===")
    print(f"  city: '{city}'")
    print(f"  itinerary: {itinerary is not None} ({len(itinerary) if itinerary else 0} days)")
    print(f"  error: {error}")
    
    return render_template(
        "itinerary.html",
        itinerary=itinerary,
        city=city,
        user=session["user"],
        error=error
    )


# ---------------------------------------------------
# Delete Travel History
# ---------------------------------------------------
@app.route("/delete_travel/<int:travel_id>", methods=["POST"])
def delete_travel(travel_id):
    if "user_id" not in session:
        return redirect("/login")
    
    user_id = session["user_id"]
    success = db.delete_travel_history(travel_id, user_id)
    
    if success:
        return redirect("/dashboard")
    else:
        flash("Error: Could not delete travel history", "error")
        return redirect("/dashboard")

# ---------------------------------------------------
# Delete Saved Destination
# ---------------------------------------------------
@app.route("/delete_saved_destination/<int:dest_id>", methods=["POST"])
def delete_saved_destination(dest_id):
    if "user_id" not in session:
        return redirect("/login")
    
    user_id = session["user_id"]
    success = db.delete_saved_destination(dest_id, user_id)
    
    if success:
        return redirect("/dashboard")
    else:
        flash("Error: Could not delete saved destination", "error")
        return redirect("/dashboard")

# ---------------------------------------------------
# Food Page
# ---------------------------------------------------
@app.route("/food", methods=["GET", "POST"])
def food():
    if "user_id" not in session:
        return redirect("/login")

    city = None
    items = []

    if request.method == "POST":
        city = request.form["city"]
        if city:
            # Use "Region/City" column as per the dataset structure
            filtered = food_df[food_df["Region/City"].str.lower().str.contains(city.lower(), na=False)]
            # Remove duplicates based on "Dish Name" to avoid showing the same dish multiple times
            filtered = filtered.drop_duplicates(subset=["Dish Name"], keep="first")
            items = filtered.sample(min(10, len(filtered))).to_dict(orient="records") if len(filtered) > 0 else []
    else:
        # Remove duplicates before sampling for random suggestions too
        unique_foods = food_df.drop_duplicates(subset=["Dish Name"], keep="first")
        items = unique_foods.sample(min(20, len(unique_foods))).to_dict(orient="records")

    return render_template("food.html", items=items, city=city, user=session["user"])

# ---------------------------------------------------
# Transport Page (using separate datasets)
# ---------------------------------------------------
@app.route("/transport", methods=["GET", "POST"])
def transport():
    if "user_id" not in session:
        return redirect("/login")

    city = None
    bus_data = []
    road_data = []
    traffic_data = []
    commuter_data = []
    recommendations = None

    if request.method == "POST":
        city = request.form.get("city", "").strip()
        if city:
            # Try to get data from datasets
            if not bus_df.empty:
                bus_data = bus_df[bus_df["city"].str.lower() == city.lower()].to_dict(orient="records") if "city" in bus_df.columns else []
                road_data = road_df[road_df["city"].str.lower() == city.lower()].to_dict(orient="records") if "city" in road_df.columns else []
                traffic_data = traffic_df[traffic_df["city"].str.lower() == city.lower()].to_dict(orient="records") if "city" in traffic_df.columns else []
                commuter_data = commuter_df[commuter_df["city"].str.lower() == city.lower()].to_dict(orient="records") if "city" in commuter_df.columns else []
            
            # Generate intelligent transport recommendations
            recommendations = get_transport_recommendations(city)
            
            # Try to get AI-generated tips using Gemini
            ai_tips = get_ai_transport_tips(city)
            if ai_tips:
                # Replace generic tips with AI-generated ones
                recommendations["tips"] = ai_tips
                print(f"✓ Using AI-generated transport tips for {city}")

    return render_template(
        "transport.html",
        city=city,
        bus_data=bus_data,
        road_data=road_data,
        traffic_data=traffic_data,
        commuter_data=commuter_data,
        recommendations=recommendations,
        user=session["user"]
    )

def get_transport_recommendations(city):
    """Generate transport mode recommendations based on city characteristics"""
    city_lower = city.lower()
    
    # Major cities with metro systems
    metro_cities = [
        "london", "paris", "new york", "tokyo", "moscow", "beijing", "shanghai",
        "seoul", "singapore", "hong kong", "bangkok", "delhi", "mumbai", "cairo",
        "madrid", "barcelona", "berlin", "munich", "vienna", "prague", "budapest",
        "istanbul", "athens", "rome", "milan", "amsterdam", "brussels", "stockholm",
        "oslo", "copenhagen", "warsaw", "lisbon", "dublin", "edinburgh", "glasgow"
    ]
    
    # Cities known for excellent public transport
    public_transport_cities = [
        "zurich", "geneva", "helsinki", "copenhagen", "stockholm", "singapore",
        "hong kong", "tokyo", "seoul", "vienna", "berlin", "amsterdam", "london"
    ]
    
    # Cities where cycling is popular
    cycling_cities = [
        "amsterdam", "copenhagen", "utrecht", "munster", "antwerp", "strasbourg",
        "bordeaux", "portland", "minneapolis", "boulder", "berlin", "vienna"
    ]
    
    # Cities where walking is best
    walkable_cities = [
        "venice", "florence", "prague", "bruges", "salzburg", "tallinn", "riga",
        "vilnius", "lubjana", "zadar", "dubrovnik", "split", "santorini", "mykonos"
    ]
    
    # Cities where taxis/ride-sharing is recommended
    taxi_cities = [
        "los angeles", "houston", "phoenix", "atlanta", "miami", "dallas",
        "philadelphia", "detroit", "charlotte", "san antonio"
    ]
    
    recommendations = {
        "primary": [],
        "secondary": [],
        "tips": []
    }
    
    # Check for metro
    has_metro = any(metro_city in city_lower for metro_city in metro_cities)
    if has_metro:
        recommendations["primary"].append({
            "mode": "Metro/Subway",
            "reason": "Efficient and fast for city center travel",
            "pros": ["Fast", "Avoids traffic", "Affordable", "Frequent service"],
            "cons": ["Can be crowded during rush hours"]
        })
    
    # Check for excellent public transport
    has_excellent_pt = any(pt_city in city_lower for pt_city in public_transport_cities)
    if has_excellent_pt:
        recommendations["primary"].append({
            "mode": "Public Transport (Bus/Tram)",
            "reason": "Well-connected network covering the entire city",
            "pros": ["Comprehensive coverage", "Affordable", "Eco-friendly"],
            "cons": ["May require transfers"]
        })
    
    # Check for cycling
    is_cycling_city = any(cycle_city in city_lower for cycle_city in cycling_cities)
    if is_cycling_city:
        recommendations["secondary"].append({
            "mode": "Bicycle",
            "reason": "Bike-friendly infrastructure and culture",
            "pros": ["Healthy", "Eco-friendly", "Flexible", "Free after rental"],
            "cons": ["Weather dependent", "Requires physical effort"]
        })
    
    # Check for walkability
    is_walkable = any(walk_city in city_lower for walk_city in walkable_cities)
    if is_walkable:
        recommendations["primary"].append({
            "mode": "Walking",
            "reason": "Compact city center, best explored on foot",
            "pros": ["Free", "Healthy", "See more details", "No waiting"],
            "cons": ["Limited range", "Weather dependent"]
        })
    
    # Taxi recommendations
    is_taxi_city = any(taxi_city in city_lower for taxi_city in taxi_cities)
    if is_taxi_city:
        recommendations["secondary"].append({
            "mode": "Taxi/Ride-sharing",
            "reason": "Sprawling city layout, limited public transport",
            "pros": ["Door-to-door", "Convenient", "Available 24/7"],
            "cons": ["Expensive", "Traffic delays"]
        })
    
    # Default recommendations if city not in specific lists
    if not recommendations["primary"]:
        recommendations["primary"].append({
            "mode": "Public Transport (Bus/Metro)",
            "reason": "Most cost-effective way to explore the city",
            "pros": ["Affordable", "Covers major areas", "Regular service"],
            "cons": ["May require route planning"]
        })
    
    if not recommendations["secondary"]:
        recommendations["secondary"].append({
            "mode": "Walking",
            "reason": "Great for exploring city centers and neighborhoods",
            "pros": ["Free", "Flexible", "Discover hidden gems"],
            "cons": ["Limited to shorter distances"]
        })
        recommendations["secondary"].append({
            "mode": "Taxi/Ride-sharing",
            "reason": "Convenient for longer distances or when in a hurry",
            "pros": ["Convenient", "Direct routes"],
            "cons": ["More expensive"]
        })
    
    # Add general tips
    recommendations["tips"] = [
        "Purchase a day or multi-day transport pass for unlimited travel",
        "Download local transport apps for real-time schedules",
        "Avoid rush hours (7-9 AM, 5-7 PM) for a more comfortable journey",
        "Keep small change for bus/tram tickets",
        "Validate tickets before boarding to avoid fines",
        "Consider walking for distances under 2km",
        "Use ride-sharing apps for late-night travel"
    ]
    
    return recommendations

# ---------------------------------------------------
# Enhanced Transport API Integration
# ---------------------------------------------------

def get_real_time_transit(origin, destination, city=None):
    """Get real-time transit directions using Google Maps or HERE Maps API"""
    transit_data = None
    
    # Try Google Maps Directions API first
    if GOOGLE_MAPS_API_KEY:
        try:
            url = "https://maps.googleapis.com/maps/api/directions/json"
            params = {
                "origin": origin,
                "destination": destination,
                "mode": "transit",
                "alternatives": "true",
                "key": GOOGLE_MAPS_API_KEY
            }
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "OK" and data.get("routes"):
                    transit_data = parse_google_transit_data(data)
                    print(f"✓ Google Maps transit data retrieved for {origin} to {destination}")
                else:
                    print(f"Google Maps API returned status: {data.get('status')}")
            else:
                print(f"Google Maps API error: {response.status_code}")
        except Exception as e:
            print(f"Google Maps API error: {e}")
    
    # Fallback to HERE Maps API
    if not transit_data and HERE_API_KEY:
        try:
            url = "https://transit.router.hereapi.com/v8/routes"
            params = {
                "origin": origin,
                "destination": destination,
                "return": "polyline,travelSummary,typicalDuration",
                "apiKey": HERE_API_KEY
            }
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("routes"):
                    transit_data = parse_here_transit_data(data)
                    print(f"✓ HERE Maps transit data retrieved for {origin} to {destination}")
        except Exception as e:
            print(f"HERE Maps API error: {e}")
    
    return transit_data

def parse_google_transit_data(data):
    """Parse Google Maps transit API response"""
    routes = []
    
    for route in data.get("routes", [])[:3]:  # Get top 3 routes
        legs = route.get("legs", [])
        if not legs:
            continue
            
        leg = legs[0]
        steps = []
        
        for step in leg.get("steps", []):
            step_info = {
                "mode": step.get("travel_mode", "WALKING"),
                "instructions": step.get("html_instructions", ""),
                "distance": step.get("distance", {}).get("text", ""),
                "duration": step.get("duration", {}).get("text", ""),
            }
            
            # Add transit details if available
            if "transit_details" in step:
                transit = step["transit_details"]
                step_info["transit"] = {
                    "line": transit.get("line", {}).get("short_name", ""),
                    "vehicle": transit.get("line", {}).get("vehicle", {}).get("type", ""),
                    "departure_stop": transit.get("departure_stop", {}).get("name", ""),
                    "arrival_stop": transit.get("arrival_stop", {}).get("name", ""),
                    "num_stops": transit.get("num_stops", 0),
                    "departure_time": transit.get("departure_time", {}).get("text", ""),
                    "arrival_time": transit.get("arrival_time", {}).get("text", ""),
                }
            
            steps.append(step_info)
        
        routes.append({
            "summary": route.get("summary", "Route"),
            "distance": leg.get("distance", {}).get("text", ""),
            "duration": leg.get("duration", {}).get("text", ""),
            "steps": steps,
            "start_address": leg.get("start_address", ""),
            "end_address": leg.get("end_address", ""),
        })
    
    return {
        "routes": routes,
        "status": "success"
    }

def parse_here_transit_data(data):
    """Parse HERE Maps transit API response"""
    routes = []
    
    for route in data.get("routes", [])[:3]:
        sections = route.get("sections", [])
        steps = []
        
        for section in sections:
            step_info = {
                "mode": section.get("type", "transit"),
                "distance": f"{section.get('travelSummary', {}).get('length', 0) / 1000:.1f} km",
                "duration": f"{section.get('travelSummary', {}).get('duration', 0) // 60} min",
            }
            
            if section.get("transport"):
                transport = section["transport"]
                step_info["transit"] = {
                    "line": transport.get("name", ""),
                    "mode": transport.get("mode", ""),
                }
            
            steps.append(step_info)
        
        summary = route.get("sections", [{}])[0].get("travelSummary", {})
        routes.append({
            "summary": "HERE Route",
            "distance": f"{summary.get('length', 0) / 1000:.1f} km",
            "duration": f"{summary.get('duration', 0) // 60} min",
            "steps": steps,
        })
    
    return {
        "routes": routes,
        "status": "success"
    }

def get_traffic_data(city):
    """Get real-time traffic data for a city"""
    traffic_info = {
        "status": "unavailable",
        "message": "Real-time traffic data requires API key"
    }
    
    # Try Google Maps Traffic API
    if GOOGLE_MAPS_API_KEY:
        try:
            # Geocode city to get coordinates
            geocode_url = "https://maps.googleapis.com/maps/api/geocode/json"
            params = {
                "address": city,
                "key": GOOGLE_MAPS_API_KEY
            }
            response = requests.get(geocode_url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("results"):
                    location = data["results"][0]["geometry"]["location"]
                    traffic_info = {
                        "status": "available",
                        "location": location,
                        "message": "Traffic data available via Google Maps",
                        "note": "Use Google Maps embed for live traffic visualization"
                    }
        except Exception as e:
            print(f"Traffic data error: {e}")
    
    return traffic_info

# API endpoint for real-time transit
@app.route("/api/transit", methods=["POST"])
@limiter.limit("10 per minute") if LIMITER_AVAILABLE else lambda f: f
def api_transit():
    """API endpoint for real-time transit directions"""
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    origin = data.get("origin")
    destination = data.get("destination")
    city = data.get("city")
    
    if not origin or not destination:
        return jsonify({"error": "Origin and destination required"}), 400
    
    transit_data = get_real_time_transit(origin, destination, city)
    
    if transit_data:
        return jsonify(transit_data)
    else:
        return jsonify({
            "status": "error",
            "message": "No transit data available. Please configure Google Maps or HERE Maps API key."
        }), 503


# ---------------------------------------------------
# Weather Page
# ---------------------------------------------------
@app.route("/weather", methods=["GET", "POST"])
def weather():
    if "user_id" not in session:
        return redirect("/login")
    
    weather_data = None
    error = None
    city = ""
    
    if request.method == "POST":
        city = request.form.get("city", "")
        if city:
            try:
                weather_data = None
                
                # Try OpenWeatherMap API first if key is provided
                if WEATHER_API_KEY:
                    try:
                        url = "https://api.openweathermap.org/data/2.5/weather"
                        params = {
                        "q": city,
                        "appid": WEATHER_API_KEY,
                        "units": "metric"
                        }
                        response = requests.get(url, params=params, timeout=10)
                        if response.status_code == 200:
                            data = response.json()
                            weather_data = {
                                "city": data.get("name", city),
                                "country": data.get("sys", {}).get("country", "N/A"),
                                "temp": round(data.get("main", {}).get("temp", 0)),
                                "feels_like": round(data.get("main", {}).get("feels_like", 0)),
                                "description": data.get("weather", [{}])[0].get("description", "N/A").title() if data.get("weather") else "N/A",
                                "icon": data.get("weather", [{}])[0].get("icon", "01d") if data.get("weather") else "01d",
                                "humidity": data.get("main", {}).get("humidity", 0),
                                "wind_speed": data.get("wind", {}).get("speed", 0),
                                "pressure": data.get("main", {}).get("pressure", 0)
                            }
                        elif response.status_code == 401:
                            print("OpenWeatherMap API key invalid, using free API")
                        elif response.status_code == 404:
                            error = f"City '{city}' not found. Please try another city name."
                        else:
                            print(f"OpenWeatherMap error {response.status_code}, trying free API")
                    except Exception as e:
                        print(f"OpenWeatherMap API error: {e}, trying free API")
                
                # Fallback to free weather API (Open-Meteo)
                if not weather_data:
                    try:
                        # First, get coordinates for the city using a geocoding service
                        geocode_url = "https://geocoding-api.open-meteo.com/v1/search"
                        geocode_params = {"name": city, "count": 1}
                        geo_response = requests.get(geocode_url, params=geocode_params, timeout=10)
                        
                        if geo_response.status_code == 200:
                            geo_data = geo_response.json()
                            if geo_data.get("results") and len(geo_data["results"]) > 0:
                                result = geo_data["results"][0]
                                lat = result.get("latitude")
                                lon = result.get("longitude")
                                city_name = result.get("name", city)
                                country = result.get("country", "N/A")
                                
                                # Get weather data from Open-Meteo (free, no API key needed)
                                weather_url = "https://api.open-meteo.com/v1/forecast"
                                weather_params = {
                                    "latitude": lat,
                                    "longitude": lon,
                                    "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,surface_pressure",
                                    "timezone": "auto"
                                }
                                weather_response = requests.get(weather_url, params=weather_params, timeout=10)
                                
                                if weather_response.status_code == 200:
                                    w_data = weather_response.json()
                                    current = w_data.get("current", {})
                                    
                                    # Map weather codes to descriptions
                                    weather_codes = {
                                        0: "Clear Sky", 1: "Mainly Clear", 2: "Partly Cloudy", 3: "Overcast",
                                        45: "Foggy", 48: "Depositing Rime Fog", 51: "Light Drizzle", 53: "Moderate Drizzle",
                                        56: "Light Freezing Drizzle", 57: "Dense Freezing Drizzle", 61: "Slight Rain",
                                        63: "Moderate Rain", 65: "Heavy Rain", 66: "Light Freezing Rain",
                                        67: "Heavy Freezing Rain", 71: "Slight Snow", 73: "Moderate Snow",
                                        75: "Heavy Snow", 77: "Snow Grains", 80: "Slight Rain Showers",
                                        81: "Moderate Rain Showers", 82: "Violent Rain Showers", 85: "Slight Snow Showers",
                                        86: "Heavy Snow Showers", 95: "Thunderstorm", 96: "Thunderstorm with Hail",
                                        99: "Thunderstorm with Heavy Hail"
                                    }
                                    
                                    weather_code = int(current.get("weather_code", 0))
                                    description = weather_codes.get(weather_code, "Unknown")
                                    
                                    weather_data = {
                                        "city": city_name,
                                        "country": country,
                                        "temp": round(current.get("temperature_2m", 0)),
                                        "feels_like": round(current.get("temperature_2m", 0)),  # Open-Meteo doesn't provide feels_like
                                        "description": description,
                                        "icon": "01d" if weather_code in [0, 1] else "02d" if weather_code == 2 else "03d" if weather_code == 3 else "50d",
                                        "humidity": round(current.get("relative_humidity_2m", 0)),
                                        "wind_speed": round(current.get("wind_speed_10m", 0) * 3.6, 1),  # Convert m/s to km/h
                                        "pressure": round(current.get("surface_pressure", 0))
                                    }
                                else:
                                    error = "Could not fetch weather data from free API."
                            else:
                                error = f"City '{city}' not found. Please try another city name."
                        else:
                            error = "Could not geocode city. Please try again."
                    except Exception as free_api_error:
                        error = f"Error fetching weather data: {str(free_api_error)}"
                        import traceback
                        traceback.print_exc()
            except requests.exceptions.Timeout:
                error = "Request timed out. Please try again."
            except requests.exceptions.RequestException as e:
                error = f"Network error: {str(e)}"
            except Exception as e:
                error = f"Error fetching weather data: {str(e)}"
                import traceback
                traceback.print_exc()
    
    return render_template("weather.html", weather_data=weather_data, error=error, city=city, user=session["user"])

# ---------------------------------------------------
# Currency Converter Page
# ---------------------------------------------------
@app.route("/currency", methods=["GET", "POST"])
def currency():
    if "user_id" not in session:
        return redirect("/login")
    
    result = None
    error = None
    
    # Common currencies
    currencies = [
        ("USD", "US Dollar"), ("EUR", "Euro"), ("GBP", "British Pound"),
        ("JPY", "Japanese Yen"), ("AUD", "Australian Dollar"), ("CAD", "Canadian Dollar"),
        ("CHF", "Swiss Franc"), ("CNY", "Chinese Yuan"), ("INR", "Indian Rupee"),
        ("SGD", "Singapore Dollar"), ("AED", "UAE Dirham"), ("NZD", "New Zealand Dollar")
    ]
    
    if request.method == "POST":
        amount = request.form.get("amount", "")
        from_currency = request.form.get("from_currency", "USD")
        to_currency = request.form.get("to_currency", "EUR")
        
        try:
            amount = float(amount)
            # Try exchangerate-api.io (free, no API key needed)
            try:
                url = f"https://api.exchangerate-api.com/v4/latest/{from_currency}"
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if to_currency in data.get("rates", {}):
                        rate = data["rates"][to_currency]
                        converted = amount * rate
                        result = {
                            "amount": amount,
                            "from": from_currency,
                            "to": to_currency,
                            "rate": round(rate, 4),
                            "converted": round(converted, 2)
                        }
                    else:
                        raise Exception("Currency not found in rates")
                else:
                    raise Exception("API returned non-200 status")
            except Exception as api_error:
                print(f"ExchangeRate API error: {api_error}, using fallback rates")
                # Comprehensive fallback rates (updated approximate rates)
                rates = {
                    "USD": {
                        "EUR": 0.92, "GBP": 0.79, "INR": 83.15, "JPY": 149.50,
                        "AUD": 1.52, "CAD": 1.35, "CHF": 0.88, "CNY": 7.24,
                        "SGD": 1.34, "AED": 3.67, "NZD": 1.64
                    },
                    "EUR": {
                        "USD": 1.09, "GBP": 0.86, "INR": 90.50, "JPY": 162.75,
                        "AUD": 1.65, "CAD": 1.47, "CHF": 0.96, "CNY": 7.88,
                        "SGD": 1.46, "AED": 4.00, "NZD": 1.78
                    },
                    "GBP": {
                        "USD": 1.27, "EUR": 1.16, "INR": 105.50, "JPY": 189.50,
                        "AUD": 1.93, "CAD": 1.71, "CHF": 1.12, "CNY": 9.18,
                        "SGD": 1.70, "AED": 4.66, "NZD": 2.07
                    },
                    "INR": {
                        "USD": 0.012, "EUR": 0.011, "GBP": 0.0095, "JPY": 1.80,
                        "AUD": 0.018, "CAD": 0.016, "CHF": 0.011, "CNY": 0.087,
                        "SGD": 0.016, "AED": 0.044, "NZD": 0.020
                    },
                    "JPY": {
                        "USD": 0.0067, "EUR": 0.0061, "GBP": 0.0053, "INR": 0.56,
                        "AUD": 0.010, "CAD": 0.0090, "CHF": 0.0059, "CNY": 0.048,
                        "SGD": 0.0090, "AED": 0.025, "NZD": 0.011
                    }
                }
                # Add reverse rates for common currencies
                for base_curr, targets in rates.items():
                    for target_curr, rate_val in targets.items():
                        if target_curr not in rates:
                            rates[target_curr] = {}
                        rates[target_curr][base_curr] = 1 / rate_val if rate_val != 0 else 1.0
                
                rate = rates.get(from_currency, {}).get(to_currency, 1.0)
                result = {
                    "amount": amount,
                    "from": from_currency,
                    "to": to_currency,
                    "rate": round(rate, 4),
                    "converted": round(amount * rate, 2)
                }
        except ValueError:
            error = "Please enter a valid number"
        except Exception as e:
            error = f"Error: {str(e)}"
    
    return render_template("currency.html", result=result, error=error, currencies=currencies, user=session["user"])

# ---------------------------------------------------
# Translator Page
# ---------------------------------------------------
@app.route("/translator", methods=["GET", "POST"])
def translator():
    if "user_id" not in session:
        return redirect("/login")
    
    translated_text = None
    pronunciation = None
    error = None
    
    languages = [
        ("en", "English"), ("es", "Spanish"), ("fr", "French"), ("de", "German"),
        ("it", "Italian"), ("pt", "Portuguese"), ("ru", "Russian"), ("ja", "Japanese"),
        ("ko", "Korean"), ("zh", "Chinese"), ("ar", "Arabic"), ("hi", "Hindi")
    ]
    
    if request.method == "POST":
        text = request.form.get("text", "")
        from_lang = request.form.get("from_lang", "en")
        to_lang = request.form.get("to_lang", "es")
        
        if text:
            translated_text = None
            # Try Gemini API first if available
            if GEMINI_AVAILABLE and GEMINI_API_KEY and GEMINI_API_KEY.strip():
                try:
                    # Get language names for better prompts
                    lang_names = dict(languages)
                    from_lang_name = lang_names.get(from_lang, from_lang)
                    to_lang_name = lang_names.get(to_lang, to_lang)
                    
                    # Initialize model - use simple approach
                    model = None
                    for model_name in ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']:
                        try:
                            model = genai.GenerativeModel(model_name)
                            print(f"Translator: Successfully initialized model: {model_name}")
                            break
                        except Exception as e:
                            error_msg = str(e)
                            print(f"Translator: Failed {model_name}: {error_msg[:100]}")
                            # If it's an API key error, don't try other models
                            if "api" in error_msg.lower() and "key" in error_msg.lower():
                                print("Translator: API key issue detected, skipping other models")
                                break
                            continue
                    
                    if model:
                        # Always request pronunciation for better user experience
                        prompt = f"""Translate the following text from {from_lang_name} to {to_lang_name}. 

Provide your response in this exact format:
TRANSLATION: [the translation in {to_lang_name}]
PRONUNCIATION: [how to pronounce it in English using Latin alphabet]

Text to translate: {text}"""
                        
                        try:
                            response = model.generate_content(prompt)
                        except Exception as gen_error:
                            error_msg = str(gen_error)
                            print(f"Translator: Error generating content: {error_msg[:200]}")
                            # If it's an API key or quota error, raise it to trigger fallback
                            if any(keyword in error_msg.lower() for keyword in ["api", "key", "quota", "permission", "unauthorized"]):
                                raise Exception(f"API error: {error_msg[:100]}")
                            raise
                        
                        result_text = None
                        if hasattr(response, 'text'):
                            result_text = response.text.strip()
                        elif hasattr(response, 'candidates') and len(response.candidates) > 0:
                            if hasattr(response.candidates[0], 'content'):
                                if hasattr(response.candidates[0].content, 'parts'):
                                    if len(response.candidates[0].content.parts) > 0:
                                        if hasattr(response.candidates[0].content.parts[0], 'text'):
                                            result_text = response.candidates[0].content.parts[0].text.strip()
                        
                        if not result_text:
                            result_text = str(response).strip() if response else ""
                        
                        # Parse the response to extract translation and pronunciation
                        if result_text:
                            # Look for TRANSLATION: and PRONUNCIATION: markers
                            translation_marker = "TRANSLATION:"
                            pronunciation_marker = "PRONUNCIATION:"
                            
                            if translation_marker in result_text.upper() or pronunciation_marker in result_text.upper():
                                # Split by markers (case insensitive)
                                import re
                                parts = re.split(r'(?i)(TRANSLATION:|PRONUNCIATION:)', result_text)
                                
                                current_section = None
                                translation_parts = []
                                pronunciation_parts = []
                                
                                for part in parts:
                                    part = part.strip()
                                    if not part:
                                        continue
                                    if part.upper() == "TRANSLATION:":
                                        current_section = "translation"
                                    elif part.upper() == "PRONUNCIATION:":
                                        current_section = "pronunciation"
                                    else:
                                        if current_section == "translation":
                                            translation_parts.append(part)
                                        elif current_section == "pronunciation":
                                            pronunciation_parts.append(part)
                                
                                if translation_parts:
                                    translated_text = ' '.join(translation_parts).strip()
                                else:
                                    translated_text = result_text
                                
                                if pronunciation_parts:
                                    pronunciation = ' '.join(pronunciation_parts).strip()
                                    # Clean up pronunciation
                                    for prefix in ['pronunciation:', 'pronounced:', 'sounds like:']:
                                        if pronunciation.lower().startswith(prefix):
                                            pronunciation = pronunciation[len(prefix):].strip()
                            else:
                                # Try to parse by looking for common patterns
                                lines = [line.strip() for line in result_text.split('\n') if line.strip()]
                                if len(lines) >= 2:
                                    # First line is usually translation, look for pronunciation in subsequent lines
                                    translated_text = lines[0]
                                    # Look for pronunciation in remaining lines
                                    for line in lines[1:]:
                                        if any(word in line.lower() for word in ['pronunciation', 'pronounce', 'sounds', 'read as']):
                                            pronunciation = line
                                            # Remove common prefixes
                                            for prefix in ['pronunciation:', 'pronounced:', 'sounds like:', 'read as:']:
                                                if pronunciation.lower().startswith(prefix):
                                                    pronunciation = pronunciation[len(prefix):].strip()
                                            break
                                    # If no pronunciation found, use second line
                                    if not pronunciation and len(lines) > 1:
                                        pronunciation = lines[1]
                                else:
                                    translated_text = result_text
                            
                            # Clean up translation - remove common prefixes
                            if translated_text:
                                prefixes = ["Translation:", "Translation", f"[{to_lang_name}]", f"[{to_lang.upper()}]"]
                                for prefix in prefixes:
                                    if translated_text.startswith(prefix):
                                        translated_text = translated_text[len(prefix):].strip()
                            
                            # If translation is same as original, it might have failed
                            if translated_text and translated_text.lower() == text.lower():
                                translated_text = None
                                pronunciation = None
                except Exception as gemini_error:
                    print(f"Gemini translation error: {gemini_error}")
                    translated_text = None
            
            # Fallback to MyMemory Translation API if Gemini failed or not available
            if not translated_text:
                try:
                    # Try MyMemory Translation API (free, no key needed)
                    url = "https://api.mymemory.translated.net/get"
                    params = {
                        "q": text,
                        "langpair": f"{from_lang}|{to_lang}"
                    }
                    response = requests.get(url, params=params, timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("responseStatus") == 200:
                            translated_text = data.get("responseData", {}).get("translatedText", "")
                            if translated_text and translated_text != text:
                                # MyMemory doesn't provide pronunciation, but translation works
                                pass
                            else:
                                translated_text = None
                        else:
                            translated_text = None
                    else:
                        translated_text = None
                    
                    # If MyMemory failed, try LibreTranslate as last resort
                    if not translated_text:
                        try:
                            url = "https://libretranslate.de/translate"
                            payload = {
                                "q": text,
                                "source": from_lang,
                                "target": to_lang,
                                "format": "text"
                            }
                            response = requests.post(url, data=payload, timeout=10)
                            if response.status_code == 200:
                                data = response.json()
                                translated_text = data.get("translatedText", text)
                                if translated_text == text:
                                    translated_text = None
                        except:
                            pass
                    
                    if not translated_text:
                        error = "Translation service unavailable. Please try again later."
                except requests.exceptions.Timeout:
                    error = "Translation request timed out. Please try again."
                except requests.exceptions.RequestException as e:
                    error = f"Network error: {str(e)}"
                except Exception as e:
                    error = f"Translation error: {str(e)}"
                    import traceback
                    traceback.print_exc()
        else:
            error = "Please enter text to translate"
    
    # Preserve form values
    original_text = request.form.get("text", "") if request.method == "POST" else ""
    from_lang_val = request.form.get("from_lang", "en") if request.method == "POST" else "en"
    to_lang_val = request.form.get("to_lang", "es") if request.method == "POST" else "es"
    
    return render_template(
        "translator.html", 
        translated_text=translated_text, 
        pronunciation=pronunciation, 
        error=error, 
        languages=languages, 
        user=session["user"],
        original_text=original_text,
        from_lang=from_lang_val,
        to_lang=to_lang_val
    )

# ---------------------------------------------------
# Wallet Page
# ---------------------------------------------------
@app.route("/wallet")
def wallet():
    if "user_id" not in session:
        return redirect("/login")
    
    user_id = session["user_id"]
    wallet_items = db.get_wallet_items(user_id)
    
    return render_template("wallet.html", wallet_items=wallet_items, user=session["user"])

# ---------------------------------------------------
# Live Transport API using free OpenStreetMap Overpass API
# ---------------------------------------------------
@app.route("/api/transport/live")
def transport_live():
    """Fetch real transport stops for a city using the free Overpass API"""
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401

    city = request.args.get("city", "").strip()
    if not city:
        return jsonify({"error": "City name required"}), 400

    try:
        # Step 1: Geocode city to get bounding box via Nominatim
        geocode_url = "https://nominatim.openstreetmap.org/search"
        geocode_params = {
            "q": city,
            "format": "json",
            "limit": 1,
            "featuretype": "city"
        }
        geo_resp = requests.get(geocode_url, params=geocode_params,
                                headers={"User-Agent": "TravelPlanAI/1.0"}, timeout=8)
        geo_data = geo_resp.json()

        if not geo_data:
            return jsonify({"error": f"City '{city}' not found", "stops": []})

        loc = geo_data[0]
        lat = float(loc["lat"])
        lon = float(loc["lon"])
        # Build a bounding box ~5km around city center
        delta = 0.05
        bbox = f"{lat-delta},{lon-delta},{lat+delta},{lon+delta}"

        # Step 2: Query Overpass for transit stops (subway, bus, train, tram)
        overpass_url = "https://overpass-api.de/api/interpreter"
        # Slightly larger bbox for dense cities like Mumbai
        delta2 = 0.07
        bbox2 = f"{lat-delta2},{lon-delta2},{lat+delta2},{lon+delta2}"
        overpass_query = f"""
        [out:json][timeout:20];
        (
          node["railway"="station"]({bbox2});
          node["railway"="subway_entrance"]({bbox2});
          node["railway"="subway_station"]({bbox2});
          node["highway"="bus_stop"]({bbox2});
          node["amenity"="bus_station"]({bbox2});
          node["railway"="tram_stop"]({bbox2});
        );
        out body 100;
        """
        ov_resp = requests.post(overpass_url, data={"data": overpass_query}, timeout=25)
        ov_data = ov_resp.json()

        stops = []
        seen = set()
        for element in ov_data.get("elements", []):
            tags = element.get("tags", {})
            name = tags.get("name") or tags.get("name:en", "")
            if not name or name in seen:
                continue
            seen.add(name)

            railway = tags.get("railway", "")
            station_tag = tags.get("station", "")
            subway_tag = tags.get("subway", "")

            # Determine transport type properly:
            # Metro/Subway = explicitly tagged subway, or subway_entrance/subway_station
            # Train/Rail   = generic railway=station that is NOT a subway
            # Tram         = tram_stop
            # Bus          = bus_stop or bus_station
            if railway in ("subway_entrance", "subway_station") or station_tag == "subway" or subway_tag == "yes":
                stop_type = "metro"
                icon = "🚇"
            elif railway == "tram_stop":
                stop_type = "tram"
                icon = "🚋"
            elif railway == "station":
                stop_type = "train"
                icon = "�"
            else:
                stop_type = "bus"
                icon = "🚌"

            stops.append({
                "name": name,
                "type": stop_type,
                "icon": icon,
                "lat": element["lat"],
                "lon": element["lon"],
                "lines": tags.get("ref", "") or tags.get("network", "") or tags.get("operator", "")
            })

        return jsonify({
            "success": True,
            "city": city,
            "lat": lat,
            "lon": lon,
            "stops": stops[:100]  # limit to 100 stops
        })

    except requests.Timeout:
        return jsonify({"error": "Transport data request timed out. Please try again."}), 504
    except Exception as e:
        print(f"Transport live API error: {e}")
        return jsonify({"error": "Could not fetch live transport data"}), 500


# ---------------------------------------------------
# Add to Wallet API
# ---------------------------------------------------
@app.route("/add_to_wallet", methods=["POST"])
def add_to_wallet():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Not logged in"}), 401
    
    data = request.json
    user_id = session["user_id"]
    
    try:
        item_id = db.add_wallet_item(
            user_id=user_id,
            item_type=data.get("item_type"),
            title=data.get("title"),
            description=data.get("description"),
            destination=data.get("destination"),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            amount=data.get("amount"),
            currency=data.get("currency", "USD"),
            status=data.get("status", "active"),
            metadata=str(data.get("metadata", {}))
        )
        return jsonify({"success": True, "item_id": item_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

# ---------------------------------------------------
# Remove from Wallet API
# ---------------------------------------------------
@app.route("/remove_from_wallet", methods=["POST"])
def remove_from_wallet():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Not logged in"}), 401
    
    data = request.json
    user_id = session["user_id"]
    item_id = data.get("item_id")
    
    try:
        success = db.delete_wallet_item(item_id, user_id)
        if success:
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": "Item not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

# ---------------------------------------------------
# Generate QR Code for Wallet Item
# ---------------------------------------------------
@app.route("/wallet/qr/<int:item_id>")
def generate_wallet_qr(item_id):
    if "user_id" not in session:
        return redirect("/login")
    
    user_id = session["user_id"]
    wallet_items = db.get_wallet_items(user_id)
    
    # Find the item - sqlite3.Row objects use [] not .get()
    item = None
    for w_item in wallet_items:
        # sqlite3.Row can be accessed like a dict with [] or converted to dict
        try:
            # Access sqlite3.Row with [] syntax
            if w_item["id"] == item_id:
                # Convert Row to dict for easier access with .get()
                item = dict(w_item)
                break
        except (KeyError, TypeError, IndexError):
            continue
    
    if not item:
        return "Item not found", 404
    
    # Create QR code data
    qr_data = {
        "type": item.get("item_type", "travel_item"),
        "title": item.get("title", ""),
        "destination": item.get("destination", ""),
        "dates": f"{item.get('start_date', '')} to {item.get('end_date', '')}",
        "amount": f"{item.get('amount', 0)} {item.get('currency', 'USD')}",
        "status": item.get("status", "active")
    }
    
    # Convert to string for QR code
    qr_string = f"TravelPlan Item\nType: {qr_data['type']}\nTitle: {qr_data['title']}\n"
    qr_string += f"Destination: {qr_data['destination']}\n"
    qr_string += f"Dates: {qr_data['dates']}\n"
    qr_string += f"Amount: {qr_data['amount']}\n"
    qr_string += f"Status: {qr_data['status']}"
    
    # Generate QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_string)
    qr.make(fit=True)
    
    # Create image
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Convert to base64
    img_buffer = io.BytesIO()
    img.save(img_buffer, format='PNG')
    img_buffer.seek(0)
    img_base64 = base64.b64encode(img_buffer.getvalue()).decode()
    
    return f'<html><body style="text-align:center; padding:2rem;"><h2>QR Code for: {item.get("title", "Item")}</h2><img src="data:image/png;base64,{img_base64}" style="max-width:400px; border:2px solid #2193b0; padding:1rem; border-radius:8px;"/><p style="margin-top:1rem;">Scan this QR code to view travel item details</p></body></html>'

# ---------------------------------------------------
# AI Chatbot API
# ---------------------------------------------------
def strip_markdown(text):
    """Remove markdown formatting from text"""
    if not text:
        return text
    
    # Remove bold/italic markers (**text**, *text*, __text__, _text_)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)
    text = re.sub(r'_([^_]+)_', r'\1', text)
    
    # Remove code blocks (```code```)
    text = re.sub(r'```[^`]*```', '', text, flags=re.DOTALL)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    
    # Remove headers (# Header)
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
    
    # Remove links [text](url)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    
    # Remove horizontal rules (---, ***)
    text = re.sub(r'^[-*]{3,}$', '', text, flags=re.MULTILINE)
    
    # Clean up extra whitespace
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = text.strip()
    
    return text

@app.route("/chat", methods=["POST"])
def chat():
    try:
        # Check if request has JSON data
        if not request.is_json:
            return jsonify({"reply": "Invalid request. Please send JSON data."}), 400
        
        msg = request.json.get("message", "") if request.json else ""
        
        if not msg:
            return jsonify({"reply": "Please provide a message."}), 400
        
        # Use Gemini API if available and configured
        if GEMINI_AVAILABLE and GEMINI_API_KEY and GEMINI_API_KEY.strip():
            try:
                model = None
                
                # Try common model names directly (deprecated package uses these names)
                for model_name in ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']:
                    try:
                        model = genai.GenerativeModel(model_name)
                        # Test if model is actually usable by checking if it can be called
                        print(f"Successfully initialized model: {model_name}")
                        break
                    except Exception as e:
                        error_msg = str(e)
                        print(f"Failed to initialize {model_name}: {error_msg[:100]}")
                        # If it's an API key error, don't try other models
                        if "api" in error_msg.lower() and "key" in error_msg.lower():
                            print("API key issue detected, skipping other models")
                            break
                        continue
                
                if not model:
                    # Last resort: try listing models (only if we haven't hit API key issues)
                    try:
                        available_models = list(genai.list_models())
                        for m in available_models:
                            if hasattr(m, 'name'):
                                model_name = m.name.split('/')[-1] if '/' in m.name else m.name
                                try:
                                    model = genai.GenerativeModel(model_name)
                                    print(f"Using model from list: {model_name}")
                                    break
                                except Exception as model_error:
                                    print(f"Failed to use model {model_name}: {str(model_error)[:50]}")
                                    continue
                    except Exception as list_error:
                        error_msg = str(list_error)
                        print(f"Could not list models: {error_msg[:100]}")
                        # If it's an API key error, don't continue
                        if "api" in error_msg.lower() and "key" in error_msg.lower():
                            raise Exception("Invalid API key. Please check your GEMINI_API_KEY.")
                
                if not model:
                    raise Exception("Could not initialize any Gemini model. Please check your API key.")
                
                # Create a context-aware prompt for travel assistance
                prompt = f"""You are a helpful travel assistant for a travel planning platform called TravelPlan. 
The platform helps users with:
- Destination recommendations (based on travel type and budget)
- Food recommendations for cities
- Transportation information
- Travel itinerary generation
- Weather information: Users can check weather forecasts for any city using the Weather page
- Currency conversion: Users can convert between currencies using the Currency Converter page with real-time exchange rates
- Translation tools
- Travel wallet to save bookings and destinations

When users ask about:
- Currency or exchange rates: Guide them to use the Currency Converter page, or provide general information about currency exchange. Mention that the platform has a currency converter tool.
- Weather or climate: Guide them to use the Weather page to check current weather for any city, or provide general weather information about destinations. Mention that the platform has a weather tool.

Provide helpful, concise, and friendly responses about travel planning. 
Keep your responses conversational and avoid using markdown formatting (no **, no *, no #, no __, no _, no ```, etc.).
Just use plain text without any formatting symbols.

User question: {msg}

Assistant response:"""
                
                # Generate response with timeout handling
                try:
                    response = model.generate_content(prompt)
                except Exception as gen_error:
                    error_msg = str(gen_error)
                    print(f"Error generating content: {error_msg[:200]}")
                    # If it's an API key or quota error, raise it
                    if any(keyword in error_msg.lower() for keyword in ["api", "key", "quota", "permission", "unauthorized"]):
                        raise Exception(f"API error: {error_msg[:100]}")
                    raise
                
                # Handle different response structures
                reply = None
                if hasattr(response, 'text'):
                    reply = response.text
                elif hasattr(response, 'candidates') and len(response.candidates) > 0:
                    if hasattr(response.candidates[0], 'content'):
                        if hasattr(response.candidates[0].content, 'parts'):
                            if len(response.candidates[0].content.parts) > 0:
                                if hasattr(response.candidates[0].content.parts[0], 'text'):
                                    reply = response.candidates[0].content.parts[0].text
                elif isinstance(response, str):
                    reply = response
                
                if not reply:
                    reply = str(response) if response else None
                
                if not reply or not reply.strip():
                    reply = "I'm sorry, I couldn't generate a response. Please try again."
                
                # Strip any remaining markdown formatting
                reply = strip_markdown(reply)

                return jsonify({"reply": reply})
                
            except Exception as e:
                # Fallback to simple responses if Gemini API fails
                error_details = f"Gemini API error: {str(e)}"
                print(error_details)
                import traceback
                traceback.print_exc()  # Print full traceback for debugging
                # Use fallback response
                reply = get_fallback_response(msg)
                return jsonify({"reply": reply})
        else:
            # Fallback to simple rule-based responses
            reply = get_fallback_response(msg)
            return jsonify({"reply": reply})
        
    except Exception as e:
        # Error handling - always return valid JSON
        error_msg = f"Chat error: {str(e)}"
        print(error_msg)  # Log for debugging
        import traceback
        traceback.print_exc()  # Print full traceback for debugging
        return jsonify({"reply": "I'm sorry, I encountered an error. Please try again later."})

# ---------------------------------------------------
# AI Chatbot Route (Gemini-powered)
# ---------------------------------------------------
@app.route("/chatbot", methods=["POST"])
def chatbot():
    """AI-powered travel chatbot using Gemini"""
    if "user_id" not in session:
        return jsonify({"response": "Please log in to use the chatbot."}), 401
    
    try:
        data = request.json
        user_message = data.get("message", "").strip()
        
        if not user_message:
            return jsonify({"response": "Please enter a message."})
        
        # Try to use Gemini AI
        if GEMINI_AVAILABLE and GEMINI_API_KEY:
            try:
                model = genai.GenerativeModel('gemini-pro')
                
                # Create context-aware prompt
                prompt = f"""You are an expert travel assistant helping users plan their trips. 
Be friendly, concise, and helpful. Keep responses under 150 words.

User question: {user_message}

Provide practical travel advice. If asked about specific destinations, include:
- Best time to visit
- Must-see attractions
- Transportation tips
- Budget considerations
- Local customs or tips

If the question is not travel-related, politely redirect to travel topics."""

                response = model.generate_content(prompt)
                ai_response = response.text
                
                return jsonify({"response": ai_response})
                
            except Exception as e:
                print(f"Gemini API error: {e}")
                # Fall back to rule-based responses
                return jsonify({"response": get_fallback_response(user_message)})
        else:
            # Use fallback responses if Gemini not available
            return jsonify({"response": get_fallback_response(user_message)})
            
    except Exception as e:
        print(f"Chatbot error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"response": "Sorry, I encountered an error. Please try again."})

def get_fallback_response(msg):
    """Fallback response when Gemini API is not available"""
    msg_lower = msg.lower()
    
    # Enhanced fallback responses
    if "destination" in msg_lower or "place" in msg_lower or "where" in msg_lower:
        return "I can help you find the perfect destination! Go to the Destinations page and select your travel type (adventure, beach, culture, etc.) and budget. Our AI will recommend the best places for you."
    elif "food" in msg_lower or "cuisine" in msg_lower or "eat" in msg_lower:
        return "Explore local cuisines on the Food page! You can search by city to discover authentic dishes and popular restaurants. Each destination has unique culinary experiences waiting for you."
    elif "transport" in msg_lower or "metro" in msg_lower or "bus" in msg_lower or "taxi" in msg_lower:
        return "Check the Transport page for detailed information about metro systems, bus networks, and taxi options. I provide city-specific recommendations with maps and routes."
    elif "itinerary" in msg_lower or "plan" in msg_lower or "schedule" in msg_lower:
        return "Use the Destinations page to generate a personalized day-by-day itinerary! Just select a city and your travel dates, and I'll create a detailed plan with activities for morning, afternoon, and evening."
    elif "budget" in msg_lower or "cost" in msg_lower or "price" in msg_lower or "cheap" in msg_lower or "expensive" in msg_lower:
        return "Budget planning is easy! Choose low, medium, or high budget when selecting destinations. I'll recommend places that match your budget. Generally: Low ($20-50/day), Medium ($50-150/day), High ($150+/day)."
    elif "currency" in msg_lower or "exchange" in msg_lower or "convert" in msg_lower or "money" in msg_lower:
        return "Use the Currency Converter page to convert between different currencies with real-time exchange rates. It supports USD, EUR, GBP, JPY, INR, and many more currencies."
    elif "weather" in msg_lower or "climate" in msg_lower or "temperature" in msg_lower or "rain" in msg_lower:
        return "Check the Weather page for current weather conditions and forecasts for any city worldwide. It shows temperature, humidity, wind speed, and weather conditions to help you pack appropriately."
    elif "best time" in msg_lower or "when to visit" in msg_lower or "season" in msg_lower:
        return "The best time to visit depends on the destination! Generally: Europe (May-Sep), Southeast Asia (Nov-Mar), North America (Jun-Sep), South America (May-Oct). Check destination details for specific recommendations."
    elif "visa" in msg_lower or "passport" in msg_lower:
        return "Visa requirements vary by country and nationality. Always check with the embassy or consulate of your destination country at least 2-3 months before travel. Some countries offer visa-on-arrival or e-visas."
    elif "safety" in msg_lower or "safe" in msg_lower or "dangerous" in msg_lower:
        return "Safety varies by destination. Research your destination, register with your embassy, keep copies of documents, avoid displaying valuables, and stay in well-lit areas. Check travel advisories before booking."
    elif "packing" in msg_lower or "pack" in msg_lower or "luggage" in msg_lower:
        return "Packing tips: Check weather forecast, pack versatile clothing, bring essential medications, keep valuables in carry-on, and leave room for souvenirs. Don't forget chargers, adapters, and travel documents!"
    elif "hello" in msg_lower or "hi" in msg_lower or "hey" in msg_lower:
        return "Hello! I'm your AI travel assistant. I can help you with destination recommendations, itinerary planning, transport options, weather info, currency conversion, and travel tips. What would you like to know?"
    elif "thank" in msg_lower:
        return "You're welcome! Have a wonderful trip! Feel free to ask if you need any more travel advice. 🌍✈️"
    else:
        return "I'm your AI travel assistant! I can help with: 🗺️ Destination recommendations, 📅 Itinerary planning, 🚇 Transport options, 🌤️ Weather info, 💱 Currency conversion, 🍽️ Food suggestions, and 💡 Travel tips. What would you like to know?"

# ---------------------------------------------------
# Enhanced Transport with Gemini AI
# ---------------------------------------------------
def get_ai_transport_tips(city):
    """Get AI-generated transport tips using Gemini"""
    if not GEMINI_AVAILABLE or not GEMINI_API_KEY:
        return None
    
    try:
        model = genai.GenerativeModel('gemini-pro')
        prompt = f"""Provide 5 specific, practical transport tips for travelers in {city}. 
Keep each tip to one sentence. Focus on:
- Payment methods
- Peak hours to avoid
- Best transport apps
- Money-saving tricks
- Safety tips

Format as a simple list."""

        response = model.generate_content(prompt)
        tips_text = response.text.strip()
        
        # Parse the response into a list
        tips = [tip.strip().lstrip('•-*123456789. ') for tip in tips_text.split('\n') if tip.strip()]
        return tips[:7]  # Return up to 7 tips
        
    except Exception as e:
        print(f"Gemini transport tips error: {e}")
        return None

# ---------------------------------------------------
# Run Server
# ---------------------------------------------------
if __name__ == "__main__":
    # Exempt JSON API routes from CSRF (they use fetch + JSON, can't include CSRF tokens)
    csrf_exempt_json_routes()
    # Use port 8080 to avoid conflict with macOS AirPlay Receiver (port 5000)
    app.run(debug=True, host='0.0.0.0', port=8080)
