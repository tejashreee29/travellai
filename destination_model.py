import pandas as pd
import numpy as np
import joblib
from datetime import datetime
import os
# -----------------------------
# Load trained model & scaler
# -----------------------------
model = joblib.load("travel_city_model.pkl")
scaler = joblib.load("scaler.pkl")

# -----------------------------
# Load dataset
# -----------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "worldwide_travel _cities.csv")
ITINERARY_DATA_PATH = os.path.join(BASE_DIR, "tourism_iternary_dataset.csv")

df = pd.read_csv(DATA_PATH)

# Load tourism itinerary dataset if available
itinerary_df = None
try:
    itinerary_df = pd.read_csv(ITINERARY_DATA_PATH)
    print(f"Loaded tourism itinerary dataset with {len(itinerary_df)} entries")
except Exception as e:
    print(f"Could not load tourism itinerary dataset: {e}")
    itinerary_df = None


# Keep numeric columns for prediction
df_numeric = df.select_dtypes(include=[np.number])
df_numeric = df_numeric.fillna(df_numeric.mean())

# Remove target column used during training
if "seclusion" in df_numeric.columns:
    df_features = df_numeric.drop("seclusion", axis=1)
else:
    df_features = df_numeric

# Scale features
X_scaled = scaler.transform(df_features)

# Predict AI scores
df["PredictedScore"] = model.predict(X_scaled)

# -----------------------------
# Smart Destination Recommendation
# -----------------------------
def recommend_destinations(travel_type, budget_level, top_n=5):
    try:
        data = df.copy()
        
        # Validate inputs
        if not travel_type or not budget_level:
            raise ValueError("Travel type and budget level are required")
        
        # Ensure we have required columns
        if "city" not in data.columns or "country" not in data.columns:
            raise ValueError("Dataset must contain 'city' and 'country' columns")
        
        # Normalize PredictedScore to 0-1 range for better weighting
        if "PredictedScore" in data.columns:
            min_score = data["PredictedScore"].min()
            max_score = data["PredictedScore"].max()
            if max_score > min_score:
                data["normalized_ai_score"] = (data["PredictedScore"] - min_score) / (max_score - min_score)
            else:
                data["normalized_ai_score"] = 0.5
        else:
            # If no PredictedScore, use a default value
            data["normalized_ai_score"] = 0.5

            # Handle travel type preference with normalization
        travel_type_score = 0
        if travel_type in data.columns:
            # Normalize travel_type values to 0-1 range
            min_travel = data[travel_type].min()
            max_travel = data[travel_type].max()
            if max_travel > min_travel:
                travel_type_score = (data[travel_type] - min_travel) / (max_travel - min_travel)
            else:
                travel_type_score = 0.5
        else:
            # If travel_type column doesn't exist, check for similar columns
            possible_cols = [col for col in data.columns if travel_type.lower() in col.lower() or col.lower() in travel_type.lower()]
            if possible_cols:
                travel_type_col = possible_cols[0]
                min_travel = data[travel_type_col].min()
                max_travel = data[travel_type_col].max()
                if max_travel > min_travel:
                    travel_type_score = (data[travel_type_col] - min_travel) / (max_travel - min_travel)
                else:
                    travel_type_score = 0.5
            else:
                travel_type_score = 0.3  # Default moderate score if column not found

        # Budget preference match with better handling
        budget_match_score = 0
        budget_cols = ["budget_level", "budget", "cost_level", "price_level"]
        budget_col = None
        for col in budget_cols:
            if col in data.columns:
                budget_col = col
                break
        
        if budget_col:
            # Handle both string and numeric budget levels
            if data[budget_col].dtype == 'object':
                budget_match_score = (data[budget_col].astype(str).str.lower() == budget_level.lower()).astype(float)
            else:
                # If numeric, map budget levels to ranges
                budget_mapping = {"low": 1, "medium": 2, "high": 3}
                budget_value = budget_mapping.get(budget_level.lower(), 2)
                # Score based on how close the budget level is
                numeric_budget = pd.to_numeric(data[budget_col], errors='coerce').fillna(2)
                budget_match_score = 1 - abs(numeric_budget - budget_value) / 2.0
                budget_match_score = budget_match_score.clip(0, 1)
        else:
            # If no budget column, use a neutral score
            budget_match_score = 0.5

        # Calculate final score with better weighting
        # Weights: AI Score (40%), Travel Type Match (40%), Budget Match (20%)
        # Ensure all scores are Series/arrays of same length
        if isinstance(travel_type_score, pd.Series):
            travel_type_array = travel_type_score.values
        else:
            travel_type_array = np.full(len(data), travel_type_score if isinstance(travel_type_score, (int, float)) else 0.3)
        
        if isinstance(budget_match_score, pd.Series):
            budget_array = budget_match_score.values
        else:
            budget_array = np.full(len(data), budget_match_score if isinstance(budget_match_score, (int, float)) else 0.5)
        
        data["final_score"] = (
            data["normalized_ai_score"] * 0.4 +
            travel_type_array * 0.4 +
            budget_array * 0.2
        )

        # Sort by final score
        data = data.sort_values("final_score", ascending=False)
        
        # Remove duplicates based on city+country combination
        if "city" in data.columns and "country" in data.columns:
            data = data.drop_duplicates(subset=["city", "country"], keep="first")
        elif "city" in data.columns:
            data = data.drop_duplicates(subset=["city"], keep="first")
        
        # Reset index after sorting and deduplication
        data = data.reset_index(drop=True)

        # Get top N results with available columns
        cols_to_select = ["city", "country", "final_score"]
        if "short_description" in data.columns:
            cols_to_select.append("short_description")
        
        result_df = data[cols_to_select].head(top_n).copy()
        
        # Ensure we have valid results
        if len(result_df) == 0:
            # Fallback: return top destinations by AI score only
            if "PredictedScore" in data.columns:
                result_df = data.nlargest(top_n, "PredictedScore")[cols_to_select].copy()
                result_df.rename(columns={"PredictedScore": "final_score"}, inplace=True)
        
        # Use short_description if available, otherwise generate based on travel type
        if "short_description" in result_df.columns:
            result_df["description"] = result_df["short_description"].fillna("")
        else:
            descriptions = {
                "beaches": "Perfect for beach lovers! Enjoy pristine coastlines, crystal-clear waters, and relaxing beachside activities.",
                "culture": "Rich in history and heritage! Explore museums, historical sites, and immerse yourself in local traditions.",
                "adventure": "Thrilling experiences await! Perfect for adrenaline seekers with exciting outdoor activities and adventures.",
                "nature": "Nature's paradise! Discover breathtaking landscapes, wildlife, and serene natural environments.",
                "nightlife": "Vibrant nightlife scene! Experience exciting nightlife, entertainment, and social activities.",
                "cuisine": "Foodie's dream destination! Savor authentic local flavors and culinary experiences.",
                "wellness": "Rejuvenate and relax! Ideal for wellness retreats, spas, and peaceful getaways.",
                "urban": "Modern city experience! Explore urban attractions, shopping, and contemporary culture.",
                "mood": "Perfect for your current mood! A versatile destination offering diverse experiences."
            }
            result_df["description"] = descriptions.get(travel_type, "A wonderful destination offering unique experiences and memorable moments.")
        
        # Add ideal time to visit based on region
        def get_ideal_time(row):
            try:
                city_match = data[data["city"] == row["city"]]
                if len(city_match) > 0:
                    city_data = city_match.iloc[0]
                    if "region" in data.columns and pd.notna(city_data.get("region")):
                        region = str(city_data["region"]).lower()
                        if "europe" in region:
                            return "Best time: May to September"
                        elif "asia" in region:
                            if "south" in region or "southeast" in region:
                                return "Best time: November to March"
                            else:
                                return "Best time: April to June, September to November"
                        elif "tropical" in region or "equator" in region:
                            return "Best time: December to April"
                        elif "america" in region:
                            if "north" in region:
                                return "Best time: June to September"
                            else:
                                return "Best time: May to October"
                        elif "africa" in region:
                            return "Best time: October to April"
                return "Best time: Spring and Autumn (March-May, September-November)"
            except:
                return "Best time: Spring and Autumn"
        
        result_df["ideal_time"] = result_df.apply(get_ideal_time, axis=1)
        
        return result_df
    
    except Exception as e:
        # Fallback: return top destinations by AI score or random if no scores
        print(f"Error in recommend_destinations: {str(e)}")
        descriptions = {
            "beaches": "Perfect for beach lovers! Enjoy pristine coastlines, crystal-clear waters, and relaxing beachside activities.",
            "culture": "Rich in history and heritage! Explore museums, historical sites, and immerse yourself in local traditions.",
            "adventure": "Thrilling experiences await! Perfect for adrenaline seekers with exciting outdoor activities and adventures.",
            "nature": "Nature's paradise! Discover breathtaking landscapes, wildlife, and serene natural environments.",
            "nightlife": "Vibrant nightlife scene! Experience exciting nightlife, entertainment, and social activities.",
            "cuisine": "Foodie's dream destination! Savor authentic local flavors and culinary experiences.",
            "wellness": "Rejuvenate and relax! Ideal for wellness retreats, spas, and peaceful getaways.",
            "urban": "Modern city experience! Explore urban attractions, shopping, and contemporary culture.",
            "mood": "Perfect for your current mood! A versatile destination offering diverse experiences."
        }
        try:
            if "PredictedScore" in df.columns:
                cols = ["city", "country", "PredictedScore"]
                if "short_description" in df.columns:
                    cols.append("short_description")
                fallback_df = df.nlargest(top_n, "PredictedScore")[cols].copy()
                fallback_df.rename(columns={"PredictedScore": "final_score"}, inplace=True)
                if "short_description" in fallback_df.columns:
                    fallback_df["description"] = fallback_df["short_description"].fillna(descriptions.get(travel_type, "A wonderful destination offering unique experiences."))
                else:
                    fallback_df["description"] = descriptions.get(travel_type, "A wonderful destination offering unique experiences.")
                fallback_df["ideal_time"] = "Best time: Spring and Autumn"
                return fallback_df
            else:
                # Last resort: return random sample
                cols = ["city", "country"]
                if "short_description" in df.columns:
                    cols.append("short_description")
                sample_df = df[cols].sample(min(top_n, len(df)))
                sample_df["final_score"] = 0.5
                if "short_description" in sample_df.columns:
                    sample_df["description"] = sample_df["short_description"].fillna(descriptions.get(travel_type, "A wonderful destination offering unique experiences."))
                else:
                    sample_df["description"] = descriptions.get(travel_type, "A wonderful destination offering unique experiences.")
                sample_df["ideal_time"] = "Best time: Spring and Autumn"
                return sample_df
        except:
            # Return empty DataFrame if everything fails
            return pd.DataFrame(columns=["city", "country", "final_score", "description", "ideal_time"])

# -----------------------------
# Itinerary Generator
# -----------------------------
def generate_itinerary(city, start_date, end_date):
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        days = (end - start).days + 1
        
        if days <= 0:
            return []
        
        # First, try to get itinerary from tourism dataset
        if itinerary_df is not None and not itinerary_df.empty:
            try:
                # Clean city name for matching (case-insensitive)
                city_clean = city.strip()
                
                # Find all rows for this city
                # The dataset has destination in first row, then empty destination for subsequent days
                city_rows = []
                found_city = False
                
                for idx, row in itinerary_df.iterrows():
                    # Access pandas Series - use try/except for safety
                    try:
                        destination_val = row['input__destination']
                        destination = str(destination_val).strip().strip('"') if pd.notna(destination_val) else ''
                    except (KeyError, IndexError):
                        destination = ''
                    
                    # If we find the city name, start collecting rows
                    if destination and destination.lower() == city_clean.lower():
                        found_city = True
                        city_rows = []
                    
                    # If we've found the city, collect rows until we hit another city
                    if found_city:
                        try:
                            day_num_val = row['output__optimized_itinerary__days__day']
                            morning_val = row['output__optimized_itinerary__days__morning']
                            afternoon_val = row['output__optimized_itinerary__days__afternoon']
                            evening_val = row['output__optimized_itinerary__days__evening']
                            
                            day_num = str(day_num_val) if pd.notna(day_num_val) else ''
                            morning = str(morning_val).strip().strip('"') if pd.notna(morning_val) else ''
                            afternoon = str(afternoon_val).strip().strip('"') if pd.notna(afternoon_val) else ''
                            evening = str(evening_val).strip().strip('"') if pd.notna(evening_val) else ''
                            
                            # If we have a day number, it's a valid itinerary entry
                            if day_num and day_num.strip() and day_num.lower() != 'nan':
                                try:
                                    day_num_int = int(float(day_num))
                                    # Check if we hit a new city (non-empty destination that's different)
                                    if destination and destination.lower() != city_clean.lower() and destination.lower() != '':
                                        break  # We've moved to a different city
                                    
                                    city_rows.append({
                                        'day': day_num_int,
                                        'morning': morning if morning and morning.lower() != 'nan' else '',
                                        'afternoon': afternoon if afternoon and afternoon.lower() != 'nan' else '',
                                        'evening': evening if evening and evening.lower() != 'nan' else ''
                                    })
                                except (ValueError, TypeError) as e:
                                    pass
                            # If we hit another city with destination, stop
                            elif destination and destination.lower() != city_clean.lower() and destination.lower() != '':
                                break
                        except (KeyError, IndexError):
                            # Missing columns, skip this row
                            pass
                
                # If we found itinerary entries, use them
                if city_rows:
                    # Sort by day number
                    city_rows.sort(key=lambda x: x['day'])
                    
                    # Build the itinerary for the requested date range
                    result_itinerary = []
                    for i in range(days):
                        day_num = i + 1
                        
                        # Find matching day from dataset (cycle if needed)
                        if day_num <= len(city_rows):
                            entry = city_rows[day_num - 1]
                        else:
                            # Cycle through available days
                            cycle_idx = (day_num - 1) % len(city_rows)
                            entry = city_rows[cycle_idx]
                        
                        # Create highlights based on activities
                        highlights_parts = []
                        if entry.get('morning'):
                            highlights_parts.append(entry['morning'][:50])
                        if entry.get('afternoon'):
                            highlights_parts.append(entry['afternoon'][:50])
                        highlights = " | ".join(highlights_parts) if highlights_parts else f"Day {day_num} in {city}"
                        
                        result_itinerary.append({
                            "Day": day_num,
                            "Date": (start + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
                            "City": city,
                            "Morning": entry.get('morning', 'Explore the city') or 'Explore the city',
                            "Afternoon": entry.get('afternoon', 'Visit local attractions') or 'Visit local attractions',
                            "Evening": entry.get('evening', 'Enjoy local dining') or 'Enjoy local dining',
                            "Highlights": highlights
                        })
                    
                    print(f"✓ Using dataset itinerary for {city} ({len(result_itinerary)} days from {len(city_rows)} dataset entries)")
                    return result_itinerary
            except Exception as dataset_error:
                import traceback
                print(f"Error using dataset itinerary: {dataset_error}")
                traceback.print_exc()
        
        # If dataset itinerary not available, use template-based itinerary
        # Detailed activity templates for different days
        activity_templates = {
            1: {  # First day - arrival and orientation
                "morning": "Arrival & hotel check-in",
                "afternoon": "Explore local neighborhood & get oriented",
                "evening": "Welcome dinner at a local restaurant",
                "highlights": "Settle in, exchange currency, get local SIM card"
            },
            2: {
                "morning": "City sightseeing & major landmarks",
                "afternoon": "Visit historical sites & museums",
                "evening": "Evening stroll through city center",
                "highlights": "Must-see attractions and iconic landmarks"
            },
            3: {
                "morning": "Local food exploration & market visit",
                "afternoon": "Cooking class or food tour",
                "evening": "Dinner at recommended local restaurant",
                "highlights": "Authentic local cuisine and flavors"
            },
            4: {
                "morning": "Cultural & heritage tour",
                "afternoon": "Visit art galleries or cultural centers",
                "evening": "Traditional cultural performance",
                "highlights": "Immerse in local culture and traditions"
            },
            5: {
                "morning": "Nature & outdoor activities",
                "afternoon": "Parks, gardens, or nature reserves",
                "evening": "Relaxation & spa time",
                "highlights": "Connect with nature and unwind"
            },
            6: {
                "morning": "Shopping & local markets",
                "afternoon": "Souvenir hunting & local crafts",
                "evening": "Evening entertainment district",
                "highlights": "Find unique souvenirs and local products"
            },
            7: {
                "morning": "Adventure activities or day trip",
                "afternoon": "Explore nearby attractions",
                "evening": "Farewell dinner",
                "highlights": "Adventure and exploration"
            }
        }
        
        # Default template for days beyond 7
        default_template = {
            "morning": "Explore new areas of the city",
            "afternoon": "Visit local attractions",
            "evening": "Enjoy local nightlife or dining",
            "highlights": "Discover hidden gems"
        }
        
        itinerary = []
        for i in range(days):
            day_num = i + 1
            template = activity_templates.get(day_num, default_template)
            
            # For longer trips, cycle through activities
            if day_num > 7:
                cycle_day = ((day_num - 1) % 7) + 1
                template = activity_templates.get(cycle_day, default_template)
            
            itinerary.append({
                "Day": day_num,
                "Date": (start + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
                "City": city,
                "Morning": template["morning"],
                "Afternoon": template["afternoon"],
                "Evening": template["evening"],
                "Highlights": template["highlights"]
            })
        
        return itinerary
    except Exception as e:
        print(f"Error generating itinerary: {str(e)}")
        # Fallback to simple itinerary
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            days = (end - start).days + 1
            
            activities = [
                "City sightseeing & landmarks",
                "Local food exploration",
                "Cultural & heritage tour",
                "Nature & relaxation",
                "Shopping & markets",
                "Adventure activities",
                "Leisure & cafe hopping"
            ]
            
            itinerary = []
            for i in range(days):
                itinerary.append({
                    "Day": i + 1,
                    "Date": (start + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
                    "City": city,
                    "Plan": activities[i % len(activities)]
                })
            return itinerary
        except:
            return []

# -----------------------------
# Main Program
# -----------------------------
def main():
    print("\n--- AI Travel Planner ---\n")

    print("Travel types available:")
    print("culture, adventure, nature, beaches, nightlife, cuisine, wellness, urban")

    travel_type = input("\nEnter travel type: ").lower()
    budget_level = input("Enter budget level (low/medium/high): ").lower()

    print("\nTop Destination Suggestions:\n")
    suggestions = recommend_destinations(travel_type, budget_level)
    print(suggestions)

    city = input("\nSelect a city from above: ")

    start_date = input("Enter start date (YYYY-MM-DD): ")
    end_date = input("Enter end date (YYYY-MM-DD): ")

    itinerary = generate_itinerary(city, start_date, end_date)

    print("\nYour Travel Itinerary:\n")
    for day in itinerary:
        print(f"Day {day['Day']} ({day['Date']}): {day['Plan']} in {day['City']}")

# -----------------------------
# Run Program
# -----------------------------
if __name__ == "__main__":
    main()
