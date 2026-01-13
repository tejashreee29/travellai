import pandas as pd

def safe_load(path):
    try:
        return pd.read_csv(path)
    except:
        return pd.DataFrame()

bus_df = safe_load("transport/bus_routes.csv")
road_df = safe_load("transport/road_segments.csv")
traffic_df = safe_load("transport/traffic_flow_data.csv")
commuter_df = safe_load("transport/commuter_patterns.csv")

# -----------------------------
# Best Transport Mode Suggestion
# -----------------------------
def recommend_transport(city):
    suggestion = {}

    if not bus_df.empty and "City" in bus_df.columns:
        buses = bus_df[bus_df["City"].str.contains(city, case=False, na=False)]
        if not buses.empty:
            suggestion["bus_routes"] = buses.sample(min(5, len(buses))).to_dict(orient="records")

    if not traffic_df.empty and "City" in traffic_df.columns:
        traffic = traffic_df[traffic_df["City"].str.contains(city, case=False, na=False)]
        if not traffic.empty and "Congestion_Level" in traffic.columns:
            avg_congestion = traffic["Congestion_Level"].mean()
            suggestion["avg_congestion"] = round(avg_congestion, 2)

    if not commuter_df.empty and "City" in commuter_df.columns:
        commuters = commuter_df[commuter_df["City"].str.contains(city, case=False, na=False)]
        if not commuters.empty and "Peak_Hour" in commuters.columns:
            peak_hour = commuters["Peak_Hour"].mode()
            if len(peak_hour) > 0:
                suggestion["best_travel_time"] = peak_hour.iloc[0]

    return suggestion
