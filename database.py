import sqlite3
import hashlib
from datetime import datetime
from contextlib import contextmanager

DATABASE = 'travelplan.db'

def init_db():
    """Initialize the database with required tables"""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    
    # Users table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # User preferences table
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            travel_type TEXT,
            budget_preference TEXT,
            favorite_cities TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # User travel history
    c.execute('''
        CREATE TABLE IF NOT EXISTS travel_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            destination TEXT NOT NULL,
            travel_type TEXT,
            budget TEXT,
            start_date TEXT,
            end_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # Saved destinations
    c.execute('''
        CREATE TABLE IF NOT EXISTS saved_destinations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            city TEXT NOT NULL,
            country TEXT NOT NULL,
            score REAL,
            travel_type TEXT,
            saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # Wallet items (bookings, cards, etc.)
    c.execute('''
        CREATE TABLE IF NOT EXISTS wallet_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            destination TEXT,
            start_date TEXT,
            end_date TEXT,
            amount REAL,
            currency TEXT DEFAULT 'USD',
            status TEXT DEFAULT 'active',
            metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    conn.commit()
    conn.close()

def hash_password(password):
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

@contextmanager
def get_db():
    """Context manager for database connections"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def create_user(username, password, email=None):
    """Create a new user"""
    password_hash = hash_password(password)
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''
                INSERT INTO users (username, email, password_hash)
                VALUES (?, ?, ?)
            ''', (username, email, password_hash))
            return c.lastrowid
    except sqlite3.IntegrityError:
        return None

def verify_user(username, password):
    """Verify user credentials"""
    password_hash = hash_password(password)
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            SELECT id, username, email FROM users
            WHERE username = ? AND password_hash = ?
        ''', (username, password_hash))
        return c.fetchone()

def get_user_by_id(user_id):
    """Get user by ID"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT id, username, email FROM users WHERE id = ?', (user_id,))
        return c.fetchone()

def save_preferences(user_id, travel_type=None, budget_preference=None, favorite_cities=None):
    """Save or update user preferences"""
    with get_db() as conn:
        c = conn.cursor()
        # Check if preferences exist
        c.execute('SELECT id FROM user_preferences WHERE user_id = ?', (user_id,))
        existing = c.fetchone()
        
        if existing:
            c.execute('''
                UPDATE user_preferences
                SET travel_type = ?, budget_preference = ?, favorite_cities = ?
                WHERE user_id = ?
            ''', (travel_type, budget_preference, favorite_cities, user_id))
        else:
            c.execute('''
                INSERT INTO user_preferences (user_id, travel_type, budget_preference, favorite_cities)
                VALUES (?, ?, ?, ?)
            ''', (user_id, travel_type, budget_preference, favorite_cities))

def get_preferences(user_id):
    """Get user preferences"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM user_preferences WHERE user_id = ?', (user_id,))
        return c.fetchone()

def add_travel_history(user_id, destination, travel_type, budget, start_date, end_date):
    """Add travel history entry"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO travel_history (user_id, destination, travel_type, budget, start_date, end_date)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, destination, travel_type, budget, start_date, end_date))
        return c.lastrowid

def get_travel_history(user_id, limit=10):
    """Get user's travel history"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            SELECT * FROM travel_history
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        ''', (user_id, limit))
        return c.fetchall()

def save_destination(user_id, city, country, score, travel_type, description=None, ideal_time=None):
    """Save a destination to user's favorites"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO saved_destinations (user_id, city, country, score, travel_type, description, ideal_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, city, country, score, travel_type, description, ideal_time))
        return c.lastrowid

def get_saved_destinations(user_id):
    """Get user's saved destinations"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            SELECT * FROM saved_destinations
            WHERE user_id = ?
            ORDER BY saved_at DESC
        ''', (user_id,))
        return c.fetchall()

def delete_travel_history(travel_id, user_id):
    """Delete a travel history entry"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            DELETE FROM travel_history
            WHERE id = ? AND user_id = ?
        ''', (travel_id, user_id))
        return c.rowcount > 0

def add_wallet_item(user_id, item_type, title, description=None, destination=None, start_date=None, end_date=None, amount=None, currency='USD', status='active', metadata=None):
    """Add an item to user's wallet"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO wallet_items (user_id, item_type, title, description, destination, start_date, end_date, amount, currency, status, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, item_type, title, description, destination, start_date, end_date, amount, currency, status, metadata))
        return c.lastrowid

def get_wallet_items(user_id, item_type=None):
    """Get user's wallet items, optionally filtered by type"""
    with get_db() as conn:
        c = conn.cursor()
        if item_type:
            c.execute('''
                SELECT * FROM wallet_items
                WHERE user_id = ? AND item_type = ?
                ORDER BY created_at DESC
            ''', (user_id, item_type))
        else:
            c.execute('''
                SELECT * FROM wallet_items
                WHERE user_id = ?
                ORDER BY created_at DESC
            ''', (user_id,))
        return c.fetchall()

def delete_wallet_item(item_id, user_id):
    """Delete a wallet item"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            DELETE FROM wallet_items
            WHERE id = ? AND user_id = ?
        ''', (item_id, user_id))
        return c.rowcount > 0

def update_wallet_item_status(item_id, user_id, status):
    """Update wallet item status"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            UPDATE wallet_items
            SET status = ?
            WHERE id = ? AND user_id = ?
        ''', (status, item_id, user_id))
        return c.rowcount > 0

# Initialize database on import
init_db()
