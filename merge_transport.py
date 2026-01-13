import pandas as pd

print("Loading transport datasets...")

bus = pd.read_csv("transport/bus_routes.csv")
roads = pd.read_csv("transport/road_segments.csv")
traffic = pd.read_csv("transport/traffic_flow_data.csv")
commuter = pd.read_csv("transport/commuter_patterns.csv")

print("Files loaded successfully!")

# Standardize column names (adjust if needed)
bus = bus.rename(columns=str.lower)
roads = roads.rename(columns=str.lower)
traffic = traffic.rename(columns=str.lower)
commuter = commuter.rename(columns=str.lower)

# Keep only useful columns
bus = bus[["city", "country"]] if "country" in bus.columns else bus[["city"]]
roads = roads[["city", "country"]] if "country" in roads.columns else roads[["city"]]
traffic = traffic[["city", "country"]] if "country" in traffic.columns else traffic[["city"]]
commuter = commuter[["city", "country"]] if "country" in commuter.columns else commuter[["city"]]

# Add transport flags
bus["bus"] = "Yes"
roads["road_network"] = "Yes"
traffic["traffic_data"] = "Yes"
commuter["public_transport"] = "Yes"

# Merge all
df = bus.merge(roads, on=["city","country"], how="outer") \
        .merge(traffic, on=["city","country"], how="outer") \
        .merge(commuter, on=["city","country"], how="outer")

# Fill missing with No
df = df.fillna("No")

# Save final dataset
df.to_csv("transport_dataset.csv", index=False)

print("transport_dataset.csv created successfully!")
