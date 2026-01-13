from flask import Flask, render_template, request, redirect, session, jsonify, flash
import pandas as pd
from destination_model import recommend_destinations, generate_itinerary
import database as db
import os
import requests
import re
import warnings

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
app.secret_key = os.environ.get("SECRET_KEY", "travelplan_secret_key_dev_change_in_production")

# API Keys (set these as environment variables or use free APIs)
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "")
CURRENCY_API_KEY = os.environ.get("CURRENCY_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Configure Gemini API if available
if GEMINI_AVAILABLE and GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Warning: Could not configure Gemini API: {e}")

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
def login():
    error = None

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = db.verify_user(username, password)
        if user:
            session["user_id"] = user["id"]
            session["user"] = user["username"]
            return redirect("/dashboard")
        else:
            error = "Invalid username or password"

    return render_template("login.html", error=error)

# ---------------------------------------------------
# Signup
# ---------------------------------------------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    error = None

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        email = request.form.get("email", None)

        user_id = db.create_user(username, password, email)
        if user_id:
            return redirect("/login")
        else:
            error = "Username already exists. Please choose a different one."

    return render_template("signup.html", error=error)

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
                                    
                                    # Keep results from session if we want to show them again
                                    # For now, clear results after itinerary is created
                                    results = None
                                    print(f"Itinerary generated successfully: {len(itinerary)} days for {selected_city}")
                                else:
                                    error = "Failed to generate itinerary. Please try again."
                                    print("Itinerary generation returned empty result")
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
    print(f"Rendering template - results: {results is not None}, itinerary: {itinerary is not None}, selected_city: {selected_city}, error: {error}")
    if itinerary:
        print(f"Itinerary has {len(itinerary)} days")

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

    if request.method == "POST":
        city = request.form["city"]
        if city and not bus_df.empty:
            bus_data = bus_df[bus_df["city"].str.lower() == city.lower()].to_dict(orient="records") if "city" in bus_df.columns else []
            road_data = road_df[road_df["city"].str.lower() == city.lower()].to_dict(orient="records") if "city" in road_df.columns else []
            traffic_data = traffic_df[traffic_df["city"].str.lower() == city.lower()].to_dict(orient="records") if "city" in traffic_df.columns else []
            commuter_data = commuter_df[commuter_df["city"].str.lower() == city.lower()].to_dict(orient="records") if "city" in commuter_df.columns else []

    return render_template(
        "transport.html",
        city=city,
        bus_data=bus_data,
        road_data=road_data,
        traffic_data=traffic_data,
        commuter_data=commuter_data,
        user=session["user"]
    )

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
                            # Invalid API key, fall through to free API
                            print("OpenWeatherMap API key invalid, using free API")
                        elif response.status_code == 404:
                            error = f"City '{city}' not found. Please try another city name."
                        else:
                            # Other error, try free API
                            print(f"OpenWeatherMap error {response.status_code}, trying free API")
                    except Exception as e:
                        print(f"OpenWeatherMap API error: {e}, trying free API")
                
                # Fallback to free weather API (Open-Meteo or wttr.in)
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
            if CURRENCY_API_KEY:
                # Using exchangerate-api.com (free tier)
                url = f"https://v6.exchangerate-api.com/v6/{CURRENCY_API_KEY}/latest/{from_currency}"
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if to_currency in data.get("conversion_rates", {}):
                        rate = data["conversion_rates"][to_currency]
                        converted = amount * rate
                        result = {
                            "amount": amount,
                            "from": from_currency,
                            "to": to_currency,
                            "rate": rate,
                            "converted": round(converted, 2)
                        }
                    else:
                        error = "Currency conversion failed"
                else:
                    error = "API error. Using estimated rates."
                    # Fallback: approximate rates (for demo)
                    rate = 0.85 if from_currency == "USD" and to_currency == "EUR" else 1.0
                    result = {
                        "amount": amount,
                        "from": from_currency,
                        "to": to_currency,
                        "rate": rate,
                        "converted": round(amount * rate, 2)
                    }
            else:
                # Demo mode with approximate rates
                rates = {
                    "USD": {"EUR": 0.85, "GBP": 0.79, "INR": 83.0, "JPY": 150.0},
                    "EUR": {"USD": 1.18, "GBP": 0.93, "INR": 97.5, "JPY": 176.0},
                    "GBP": {"USD": 1.27, "EUR": 1.08, "INR": 105.0, "JPY": 190.0}
                }
                rate = rates.get(from_currency, {}).get(to_currency, 1.0)
                result = {
                    "amount": amount,
                    "from": from_currency,
                    "to": to_currency,
                    "rate": rate,
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
            if GEMINI_AVAILABLE and GEMINI_API_KEY:
                try:
                    # Get language names for better prompts
                    lang_names = dict(languages)
                    from_lang_name = lang_names.get(from_lang, from_lang)
                    to_lang_name = lang_names.get(to_lang, to_lang)
                    
                    # Initialize model
                    model = None
                    try:
                        available_models = list(genai.list_models())
                        supported_models = []
                        for m in available_models:
                            if hasattr(m, 'supported_generation_methods'):
                                if 'generateContent' in m.supported_generation_methods:
                                    model_name = m.name.split('/')[-1] if '/' in m.name else m.name
                                    supported_models.append(model_name)
                        
                        if supported_models:
                            model = genai.GenerativeModel(supported_models[0])
                        else:
                            for test_name in ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']:
                                try:
                                    model = genai.GenerativeModel(test_name)
                                    break
                                except:
                                    continue
                    except:
                        # Fallback to direct model initialization
                        for test_name in ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']:
                            try:
                                model = genai.GenerativeModel(test_name)
                                break
                            except:
                                continue
                    
                    if model:
                        # Always request pronunciation for better user experience
                        prompt = f"""Translate the following text from {from_lang_name} to {to_lang_name}. 

Provide your response in this exact format:
TRANSLATION: [the translation in {to_lang_name}]
PRONUNCIATION: [how to pronounce it in English using Latin alphabet]

Text to translate: {text}"""
                        
                        response = model.generate_content(prompt)
                        
                        if hasattr(response, 'text'):
                            result_text = response.text.strip()
                        elif hasattr(response, 'candidates') and len(response.candidates) > 0:
                            result_text = response.candidates[0].content.parts[0].text.strip()
                        else:
                            result_text = str(response).strip()
                        
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
            
            # Fallback to LibreTranslate API if Gemini failed or not available
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
                    else:
                        error = f"Translation service error. Status code: {response.status_code}"
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
    
    return render_template("translator.html", translated_text=translated_text, pronunciation=pronunciation, error=error, languages=languages, user=session["user"])

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
        if GEMINI_AVAILABLE and GEMINI_API_KEY:
            try:
                # Try to list and use available models
                model = None
                
                # First, try to list available models
                try:
                    available_models = list(genai.list_models())
                    # Filter models that support generateContent
                    supported_models = []
                    for m in available_models:
                        if hasattr(m, 'supported_generation_methods'):
                            if 'generateContent' in m.supported_generation_methods:
                                # Extract model name (format is usually 'models/gemini-xxx')
                                model_name = m.name.split('/')[-1] if '/' in m.name else m.name
                                supported_models.append(model_name)
                    
                    print(f"Found {len(supported_models)} supported models")
                    if supported_models:
                        print(f"Available models: {supported_models[:3]}")
                        # Try the first available model
                        model = genai.GenerativeModel(supported_models[0])
                        print(f"Using model: {supported_models[0]}")
                except Exception as list_error:
                    print(f"Could not list models: {list_error}")
                
                # If listing failed, try common model names directly
                if not model:
                    # Try these in order - these are common model names
                    for model_name in ['gemini-1.5-flash-002', 'gemini-1.5-pro-002', 'gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']:
                        try:
                            model = genai.GenerativeModel(model_name)
                            print(f"Successfully using model: {model_name}")
                            break
                        except Exception as e:
                            print(f"Failed {model_name}: {str(e)[:100]}")
                            continue
                
                if not model:
                    raise Exception("Could not initialize any Gemini model. Please check your API key and model availability.")
                
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
                
                # Generate response
                response = model.generate_content(prompt)
                
                # Handle different response structures
                if hasattr(response, 'text'):
                    reply = response.text
                elif hasattr(response, 'candidates') and len(response.candidates) > 0:
                    reply = response.candidates[0].content.parts[0].text
                elif isinstance(response, str):
                    reply = response
                else:
                    reply = str(response) if response else "I'm sorry, I couldn't generate a response. Please try again."
                
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

def get_fallback_response(msg):
    """Fallback response when Gemini API is not available"""
    msg_lower = msg.lower()
    
    if "destination" in msg_lower or "place" in msg_lower:
        return "Go to Destinations and select your travel type and budget."
    elif "food" in msg_lower:
        return "Open the Food page to explore local cuisines."
    elif "transport" in msg_lower:
        return "Check the Transport page for metro, bus and taxi options."
    elif "itinerary" in msg_lower:
        return "Use the Destinations page to generate your travel itinerary."
    elif "budget" in msg_lower:
        return "Select your budget while choosing destinations."
    elif "currency" in msg_lower or "exchange" in msg_lower or "convert" in msg_lower:
        return "Use the Currency Converter page to convert between different currencies with real-time exchange rates."
    elif "weather" in msg_lower or "climate" in msg_lower or "temperature" in msg_lower:
        return "Use the Weather page to check current weather conditions and forecasts for any city worldwide."
    else:
        return "I can help with destinations, food, transport, weather, currency conversion, and travel planning."

# ---------------------------------------------------
# Run Server
# ---------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
