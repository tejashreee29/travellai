import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error
import joblib
import os

print("Current folder:", os.getcwd())

# Load dataset
df = pd.read_csv("worldwide_travel_cities.csv")
print("Dataset loaded successfully!")

print("Columns:", df.columns)

# Keep only numeric columns
df_numeric = df.select_dtypes(include=[np.number])

# Fill missing values
df_numeric = df_numeric.fillna(df_numeric.mean())

# Use first numeric column as target temporarily
TARGET = df_numeric.columns[-1]
print("Target column:", TARGET)

X = df_numeric.drop(TARGET, axis=1)
y = df_numeric[TARGET]

# Scale features
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# Train-test split
X_train, X_test, y_train, y_test = train_test_split(
    X_scaled, y, test_size=0.2, random_state=42
)

# Train model
model = RandomForestRegressor(n_estimators=200, random_state=42)
model.fit(X_train, y_train)

# Evaluate
y_pred = model.predict(X_test)
print("MAE:", mean_absolute_error(y_test, y_pred))

# Save model
joblib.dump(model, "travel_city_model.pkl")
joblib.dump(scaler, "scaler.pkl")

print("Model trained and saved successfully!")
