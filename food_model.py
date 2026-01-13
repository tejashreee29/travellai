import pandas as pd

# Load food dataset
food_df = pd.read_csv("food_dataset.csv")

def recommend_food(city=None, country=None, category=None, max_price=None):
    df = food_df.copy()

    # Filtering
    if city:
        df = df[df["Region/City"].str.contains(city, case=False, na=False)]

    if country:
        df = df[df["Country"].str.contains(country, case=False, na=False)]

    if category:
        df = df[df["Category"].str.contains(category, case=False, na=False)]

    if max_price:
        df = df[df["Price Range"] <= max_price]

    # Return top 10
    return df.sample(min(10, len(df))).to_dict(orient="records")
