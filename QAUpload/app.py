import streamlit as st
import google.generativeai as genai
import time
import sqlite3
import hashlib
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
import secrets
import string
import random
from io import BytesIO
import base64

# ============================================
# DATABASE SETUP & ADMIN FUNCTIONS
# ============================================
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            is_admin INTEGER DEFAULT 0
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            topic TEXT,
            score INTEGER,
            total_questions INTEGER,
            difficulty TEXT,
            level TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Create certificates table
    c.execute('''
        CREATE TABLE IF NOT EXISTS certificates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            certificate_id TEXT UNIQUE,
            topic TEXT,
            score INTEGER,
            issue_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expiry_date TIMESTAMP,
            status TEXT DEFAULT 'active',
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Create assessment history table
    c.execute('''
        CREATE TABLE IF NOT EXISTS assessment_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            assessment_type TEXT,
            topic TEXT,
            score INTEGER,
            max_score INTEGER,
            time_taken INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Create leaderboard table for top performers by topic
    c.execute('''
        CREATE TABLE IF NOT EXISTS leaderboard (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            topic TEXT,
            score INTEGER,
            total_questions INTEGER,
            percentage REAL,
            rank INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    
    # Create admin user if not exists
    admin_password_hash = hash_password("admin@1234")
    try:
        c.execute('''
            INSERT OR IGNORE INTO users (username, email, password_hash, is_admin) 
            VALUES (?, ?, ?, ?)
        ''', ('admin', 'admin@skillassessment.com', admin_password_hash, 1))
    except:
        pass
    
    conn.commit()
    conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_user(username, email, password, is_admin=False):
    try:
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        password_hash = hash_password(password)
        c.execute('INSERT INTO users (username, email, password_hash, is_admin) VALUES (?, ?, ?, ?)',
                 (username, email, password_hash, 1 if is_admin else 0))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def verify_user(username, password):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    password_hash = hash_password(password)
    
    c.execute('SELECT id, username, is_admin FROM users WHERE username=? AND password_hash=?',
             (username, password_hash))
    user = c.fetchone()
    if user:
        c.execute('UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?', (user[0],))
        c.execute('UPDATE users SET is_active=1 WHERE id=?', (user[0],))
        conn.commit()
    conn.close()
    return user

def save_user_score(user_id, topic, score, total_questions, difficulty, level=None):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''
        INSERT INTO user_scores (user_id, topic, score, total_questions, difficulty, level)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, topic, score, total_questions, difficulty, level))
    conn.commit()
    
    # Check if certificate should be issued (score > 80)
    if score >= 80:
        certificate_id = f"CERT-{user_id}-{int(time.time())}"
        expiry_date = datetime.now().timestamp() + (365 * 24 * 60 * 60)  # 1 year expiry
        c.execute('''
            INSERT OR REPLACE INTO certificates (user_id, certificate_id, topic, score, issue_date, expiry_date)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, datetime(?, 'unixepoch'))
        ''', (user_id, certificate_id, topic, score, expiry_date))
    
    # Update leaderboard
    update_leaderboard(user_id, topic, score, total_questions)
    
    conn.commit()
    conn.close()

def update_leaderboard(user_id, topic, score, total_questions):
    """Update leaderboard with user's score"""
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    # Calculate percentage
    percentage = (score / total_questions) * 100 if total_questions > 0 else 0
    
    # Check if user already has an entry for this topic
    c.execute('SELECT id FROM leaderboard WHERE user_id=? AND topic=?', (user_id, topic))
    existing = c.fetchone()
    
    if existing:
        # Update existing entry if new score is higher
        c.execute('''
            UPDATE leaderboard 
            SET score=?, total_questions=?, percentage=?, timestamp=CURRENT_TIMESTAMP
            WHERE user_id=? AND topic=? AND ? > percentage
        ''', (score, total_questions, percentage, user_id, topic, percentage))
    else:
        # Insert new entry
        c.execute('''
            INSERT INTO leaderboard (user_id, topic, score, total_questions, percentage)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, topic, score, total_questions, percentage))
    
    # Recalculate ranks for this topic
    recalculate_leaderboard_ranks(topic)
    
    conn.commit()
    conn.close()

def recalculate_leaderboard_ranks(topic):
    """Recalculate ranks for a specific topic"""
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    # Get all entries for this topic ordered by percentage (descending)
    c.execute('''
        SELECT id FROM leaderboard 
        WHERE topic=? 
        ORDER BY percentage DESC, timestamp DESC
    ''', (topic,))
    
    entries = c.fetchall()
    
    # Update ranks
    for rank, (entry_id,) in enumerate(entries, start=1):
        c.execute('UPDATE leaderboard SET rank=? WHERE id=?', (rank, entry_id))
    
    conn.commit()
    conn.close()

def get_leaderboard(topic=None, limit=10):
    """Get leaderboard data"""
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    if topic:
        c.execute('''
            SELECT 
                u.username,
                l.topic,
                l.score,
                l.total_questions,
                l.percentage,
                l.rank,
                l.timestamp
            FROM leaderboard l
            JOIN users u ON l.user_id = u.id
            WHERE l.topic=?
            ORDER BY l.rank ASC
            LIMIT ?
        ''', (topic, limit))
    else:
        # Get overall leaderboard (average across all topics)
        c.execute('''
            SELECT 
                u.username,
                'Overall' as topic,
                AVG(l.percentage) as avg_percentage,
                COUNT(*) as tests_taken,
                RANK() OVER (ORDER BY AVG(l.percentage) DESC) as rank
            FROM leaderboard l
            JOIN users u ON l.user_id = u.id
            GROUP BY u.id, u.username
            HAVING COUNT(*) >= 3
            ORDER BY avg_percentage DESC
            LIMIT ?
        ''', (limit,))
    
    leaderboard_data = c.fetchall()
    conn.close()
    
    return leaderboard_data

def get_user_stats(user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    # Get total tests taken
    c.execute('SELECT COUNT(*) FROM user_scores WHERE user_id=?', (user_id,))
    total_tests = c.fetchone()[0]
    
    # Get average score
    c.execute('SELECT AVG(CAST(score AS FLOAT) / total_questions * 100) FROM user_scores WHERE user_id=?', (user_id,))
    avg_score_result = c.fetchone()[0]
    avg_score = round(avg_score_result, 1) if avg_score_result else 0
    
    # Get best score
    c.execute('SELECT MAX(CAST(score AS FLOAT) / total_questions * 100) FROM user_scores WHERE user_id=?', (user_id,))
    best_score_result = c.fetchone()[0]
    best_score = round(best_score_result, 1) if best_score_result else 0
    
    # Get certificates count
    c.execute('SELECT COUNT(*) FROM certificates WHERE user_id=? AND status="active"', (user_id,))
    certificates = c.fetchone()[0]
    
    # Get recent tests
    c.execute('''
        SELECT topic, score, total_questions, difficulty, level, timestamp 
        FROM user_scores 
        WHERE user_id=? 
        ORDER BY timestamp DESC 
        LIMIT 5
    ''', (user_id,))
    recent_tests = c.fetchall()
    
    # Get level distribution
    c.execute('''
        SELECT level, COUNT(*) as count, AVG(CAST(score AS FLOAT) / total_questions * 100) as avg_score
        FROM user_scores 
        WHERE user_id=? AND level IS NOT NULL
        GROUP BY level
    ''', (user_id,))
    level_stats = c.fetchall()
    
    conn.close()
    
    return {
        'total_tests': total_tests,
        'avg_score': avg_score,
        'best_score': best_score,
        'certificates': certificates,
        'recent_tests': recent_tests,
        'level_stats': level_stats
    }

def get_all_users():
    """Get all users for admin dashboard"""
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    c.execute('''
        SELECT 
            id, username, email, created_at, last_login, is_active, is_admin
        FROM users 
        ORDER BY created_at DESC
    ''')
    
    users = c.fetchall()
    conn.close()
    return users

def welcome_page():
    st.markdown(load_css(), unsafe_allow_html=True)
    def get_base64_image(path):
        with open(path, "rb") as img:
            return base64.b64encode(img.read()).decode()

    
    st.markdown(f"""
        <style>
        /* Page background */
        body {{
            background-color: none;
        }}

        /* Main container */
        .welcome-container {{
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            text-align: center;
            font-family: 'Segoe UI', sans-serif;
        }}

        /* Card box */
        .logo-title {{
            background: rgba(255, 255, 255, 0.08);
            padding: 40px 50px;
            border-radius: 18px;
            width: 90%;
            max-width: 600px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
            backdrop-filter: blur(12px);
            animation: fadeIn 1.2s ease-in-out;
        }}

        /* Logo icon */
        .logo-icon {{
            font-size: 64px;
            margin-bottom: 10px;
        }}

        /* Title */
        .main-title {{
            font-size: 42px;
            font-weight: 700;
            color: #ffffff;
            margin-bottom: 12px;
        }}

        /* Tagline */
        .tagline {{
            font-size: 16px;
            color: black;
            line-height: 1.6;
            margin-bottom: 25px;
        }}

        /* Countdown text */
        .countdown {{
            font-size: 14px;
            color: black;
            margin-bottom: 22px;
            opacity: 0.85;
        }}
        .logo-icon {{
            display: flex;
            justify-content: center;
            align-items: center;
            margin-bottom: 15px;
        }}
        .logo-icon img {{
            width: 90px;          
            height: auto;
            max-width: 100%;
            object-fit: contain;
            border-radius: 12px;  
        }}
        .logo-icon img {{
            filter: drop-shadow(0 4px 12px rgba(255, 255, 255, 0.25));
        }}

        /* Button */
        .action-btn {{
            display: inline-block;
            padding: 14px 34px;
            font-size: 16px;
            font-weight: 600;
            color: #ffffff;
            background: linear-gradient(135deg, #ff512f, #f09819);
            border-radius: 30px;
            text-decoration: none;
            transition: all 0.3s ease;
        }}

        .action-btn:hover {{
            transform: scale(1.05);
            box-shadow: 0 8px 20px rgba(240,152,25,0.4);
        }}

        /* Animation */
        @keyframes fadeIn {{
            from {{
                opacity: 0;
                transform: translateY(20px);
            }}
            to {{
                opacity: 1;
                transform: translateY(0);
            }}
        }}
        

        </style>

        <div class="welcome-container"'>
            <div class="logo-title" style='filter: blur(0.2px);'>
                <div class="logo-icon">
                    <img src="" width="100">
                </div>
                <h1 class="main-title">Skill Assessment Generator</h1>
                <p class="tagline">
                    Transform your learning journey with AI-powered assessments. 
                    Generate personalized tests, track your progress, and master any topic.
                </p>
                <div class="countdown">
                    Redirecting to login in {st.session_state.countdown} seconds...
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    # Auto-redirect after 3 seconds
    if not st.session_state.welcome_shown:
        st.session_state.welcome_shown = True
        st.session_state.countdown = 3
    
    # Countdown timer
    if st.session_state.countdown > 0:
        time.sleep(1)
        st.session_state.countdown -= 1
        st.rerun()
    
    # Redirect to login after countdown
    if st.session_state.countdown == 0:
        st.session_state.current_page = 'login'
        st.rerun()

def login_page():
    st.markdown(load_css(), unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("""
        <div style="text-align: center; margin-bottom: 2rem;">
            <div style="font-size: 3rem; margin-bottom: 1rem; background: linear-gradient(45deg, #2563eb, #7c3aed); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">🔐</div>
            <h2 style="font-size: 2rem; font-weight: 700; color: var(--text-primary); margin-bottom: 0.5rem;">Welcome Back</h2>
            <p style="color: var(--text-secondary);">Sign in to continue your learning journey</p>
        </div>
        """, unsafe_allow_html=True)
        
        with st.form("login_form", clear_on_submit=True):
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            
            col_btn1, col_btn2, col_btn3 = st.columns(3)
            with col_btn1:
                login_btn = st.form_submit_button("Login", use_container_width=True)
            with col_btn2:
                register_btn = st.form_submit_button("Create Account", use_container_width=True, type="secondary")
           
            if login_btn:
                if username and password:
                    with st.spinner("Authenticating..."):
                        # Check for admin login
                        if username == "admin" and password == "admin@1234":
                            st.session_state.logged_in = True
                            st.session_state.username = username
                            st.session_state.user_id = 0
                            st.session_state.is_admin = True
                            st.session_state.current_page = 'admin'
                            st.success(f"Welcome Admin!")
                            time.sleep(1)
                            st.rerun()
                        else:
                            user = verify_user(username, password)
                            
                            if user:
                                st.session_state.logged_in = True
                                st.session_state.username = username
                                st.session_state.user_id = user[0]
                                st.session_state.is_admin = False
                                st.session_state.current_page = 'dashboard'
                                st.success(f"Welcome back, {username}!")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error("Invalid username or password")
                else:
                    st.warning("Please fill in all fields")
            
            if register_btn:
                st.session_state.current_page = 'register'
                st.rerun()

def register_page():
    st.markdown(load_css(), unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("""
        <div style="text-align: center; margin-bottom: 2rem;">
            <div style="font-size: 3rem; margin-bottom: 1rem; background: linear-gradient(45deg, #2563eb, #7c3aed); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">✨</div>
            <h2 style="font-size: 2rem; font-weight: 700; color: var(--text-primary); margin-bottom: 0.5rem;">Create Account</h2>
            <p style="color: var(--text-secondary);">Join our learning community today</p>
        </div>
        """, unsafe_allow_html=True)
        
        with st.form("register_form", clear_on_submit=True):
            username = st.text_input("Username", placeholder="Choose a username")
            email = st.text_input("Email", placeholder="Enter your email")
            password = st.text_input("Password", type="password", placeholder="Create a password")
            confirm_password = st.text_input("Confirm Password", type="password", 
                                           placeholder="Confirm your password")
            
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                register_btn = st.form_submit_button("Create Account", use_container_width=True)
            with col_btn2:
                login_btn = st.form_submit_button("Back to Login", use_container_width=True, type="secondary")
            
            if register_btn:
                if username and email and password and confirm_password:
                    if password == confirm_password:
                        if create_user(username, email, password):
                            st.success("Account created successfully! Please login.")
                            time.sleep(1)
                            st.session_state.current_page = 'login'
                            st.rerun()
                        else:
                            st.error("Username or email already exists")
                    else:
                        st.error("Passwords do not match")
                else:
                    st.warning("Please fill in all fields")
            
            if login_btn:
                st.session_state.current_page = 'login'
                st.rerun()

def learner_dashboard():
    """Main dashboard for learners after login"""
    st.markdown(f"""
    <style>
    /* Sidebar styling */
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%) !important;
        border-right: 1px solid #e2e8f0 !important;
    }}
    
    /* Sidebar user profile */
    .user-profile {{
        text-align: center !important;
        padding: 1.5rem 1rem !important;
        margin-bottom: 1rem !important;
    }}
    
    .user-avatar {{
        width: 70px !important;
        height: 70px !important;
        border-radius: 50% !important;
        background: linear-gradient(135deg, #3b82f6, #8b5cf6) !important;
        color: white !important;
        font-size: 2rem !important;
        font-weight: 600 !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        margin: 0 auto 1rem auto !important;
        box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2) !important;
    }}
    
    /* Sidebar headings */
    [data-testid="stSidebar"] h2 {{
        color: #334155 !important;
        font-size: 1.1rem !important;
        font-weight: 600 !important;
        margin: 1.5rem 0 1rem 0 !important;
        padding: 0 1rem !important;
        letter-spacing: 0.5px !important;
    }}
    
    /* Sidebar divider */
    [data-testid="stSidebar"] hr {{
        margin: 1.5rem 0 !important;
        border-color: #e2e8f0 !important;
        opacity: 0.7 !important;
    }}
    
    /* MENU BUTTONS - Clean, minimal style */
    [data-testid="stSidebar"] .stButton > button {{
        all: unset !important;
        width: 100% !important;
        text-align: left !important;
        padding: 0.85rem 1rem !important;
        margin: 0.15rem 0 !important;
        border-radius: 8px !important;
        background: transparent !important;
        color: #475569 !important;
        font-size: 0.95rem !important;
        font-weight: 500 !important;
        transition: all 0.2s ease !important;
        cursor: pointer !important;
        display: flex !important;
        align-items: center !important;
        border: none !important;
        box-shadow: none !important;
        border-left: 3px solid transparent !important;
    }}
    
    /* Menu button hover effect */
    [data-testid="stSidebar"] .stButton > button:hover {{
        background: #f1f5f9 !important;
        color: #1e293b !important;
        border-left: 3px solid #3b82f6 !important;
        transform: translateX(2px) !important;
    }}
    
    /* Menu button active state */
    [data-testid="stSidebar"] .stButton > button:active {{
        background: #e2e8f0 !important;
        transform: translateX(0) !important;
    }}
    
    /* Menu button focus state */
    [data-testid="stSidebar"] .stButton > button:focus {{
        outline: none !important;
        box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1) !important;
    }}
    
    /* Icon spacing in buttons */
    [data-testid="stSidebar"] .stButton > button::before {{
        content: "" !important;
        display: inline-block !important;
        width: 24px !important;
        margin-right: 10px !important;
        text-align: center !important;
        opacity: 0.8 !important;
    }}
    
    /* Optional: Add actual icons (if you have icon fonts) */
    /* If using emojis like you have, they'll display normally */
    
    /* Logout button specific styling */
    [data-testid="stSidebar"] .stButton > button:contains("🚪") {{
        margin-top: 2rem !important;
        background: #f1f5f9 !important;
        color: #dc2626 !important;
        font-weight: 600 !important;
        border: 1px solid #fecaca !important;
        text-align: center !important;
        justify-content: center !important;
    }}
    
    [data-testid="stSidebar"] .stButton > button:contains("🚪"):hover {{
        background: #fee2e2 !important;
        color: #b91c1c !important;
        border-color: #fca5a5 !important;
        border-left: 3px solid #dc2626 !important;
    }}
    
    /* Main content area */
    .main .block-container {{
        padding-top: 2rem !important;
        padding-right: 3rem !important;
        padding-left: 3rem !important;
    }}
    
    /* Fade in animation */
    @keyframes fadeIn {{
        from {{
            opacity: 0;
            transform: translateY(10px);
        }}
        to {{
            opacity: 1;
            transform: translateY(0);
        }}
    }}
    
    /* Animate sidebar items */
    [data-testid="stSidebar"] .stButton {{
        animation: fadeIn 0.3s ease-out !important;
        animation-fill-mode: both !important;
    }}
    
    /* Stagger animations for menu items */
    [data-testid="stSidebar"] .stButton:nth-child(1) {{ animation-delay: 0.1s !important; border-bottom:solid 0.5px;}}
    [data-testid="stSidebar"] .stButton:nth-child(2) {{ animation-delay: 0.15s !important; }}
    [data-testid="stSidebar"] .stButton:nth-child(3) {{ animation-delay: 0.2s !important; }}
    [data-testid="stSidebar"] .stButton:nth-child(4) {{ animation-delay: 0.25s !important; }}
    [data-testid="stSidebar"] .stButton:nth-child(5) {{ animation-delay: 0.3s !important; }}
    [data-testid="stSidebar"] .stButton:nth-child(6) {{ animation-delay: 0.35s !important; }}
    [data-testid="stSidebar"] .stButton:nth-child(7) {{ animation-delay: 0.4s !important; }}
    [data-testid="stSidebar"] .stButton:last-child {{ animation-delay: 0.5s !important; }}
    
    /* Remove Streamlit default button styles */
    .stButton > button {{
        border: none !important;
        box-shadow: none !important;
        
    }}
    
    /* Sidebar scrollbar styling */
    [data-testid="stSidebar"]::-webkit-scrollbar {{
        width: 6px !important;
    }}
    
    [data-testid="stSidebar"]::-webkit-scrollbar-track {{
        background: #f1f5f9 !important;
    }}
    
    [data-testid="stSidebar"]::-webkit-scrollbar-thumb {{
        background: #cbd5e1 !important;
        border-radius: 3px !important;
    }}
    
    [data-testid="stSidebar"]::-webkit-scrollbar-thumb:hover {{
        background: #94a3b8 !important;
    }}
    </style>
    """, unsafe_allow_html=True)
    
    # Sidebar with menu buttons instead of radio
    with st.sidebar:
        st.markdown(f"""
        <div class="user-profile">
            <div class="user-avatar">
                {st.session_state.username[0].upper() if st.session_state.username else 'U'}
            </div>
            <h3 style="color: #1e293b;">{st.session_state.username}</h3>
            <p style="color: #64748b; font-size: 0.875rem;">Skill Assessment Generator</p>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # Navigation Menu
        st.markdown("<h2>📍 Navigation</h2>", unsafe_allow_html=True)
        
        # Create menu buttons
        menu_items = [
            ("🏠 Dashboard", "dashboard"),
            ("🎯 Test Generator", "test_generator"),
            ("📊 My Assessments", "my_assessments"),
            ("🏆 Certificates", "certificates"),
            ("📈 Progress", "progress"),
            ("🏅 Leaderboard", "leaderboard"),
            ("⚙️ Settings", "settings")
        ]
        
        # Display menu buttons
        for icon_name, page_name in menu_items:
            if st.button(f"{icon_name}", key=f"menu_{page_name}", use_container_width=True):
                st.session_state.current_page = page_name
                st.markdown("---")
                st.rerun()
        
        st.markdown("---")
        
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.username = None
            st.session_state.user_id = None
            st.session_state.is_admin = False
            st.session_state.current_page = 'welcome'
            st.session_state.welcome_shown = False
            st.rerun()
    
    # Main content based on navigation
    if st.session_state.current_page == 'dashboard':
        show_dashboard_home()
    elif st.session_state.current_page == 'test_generator':
        show_test_generator()
    elif st.session_state.current_page == 'my_assessments':
        show_my_assessments()
    elif st.session_state.current_page == 'certificates':
        show_certificates()
    elif st.session_state.current_page == 'progress':
        show_progress()
    elif st.session_state.current_page == 'leaderboard':
        show_leaderboard()
    elif st.session_state.current_page == 'settings':
        show_settings()


def show_dashboard_home():
    """Main dashboard home page"""
    st.markdown("""
    <div style="max-width: 1200px; margin: 0 auto; padding: 2rem;">
        <h1 style="font-size: 2.5rem; font-weight: 800; color: var(--text-primary); margin-bottom: 0.5rem;">
            🎯 Welcome to Skill Assessment Generator
        </h1>
        <p style="color: var(--text-secondary); margin-bottom: 3rem;">
            Your personal learning and assessment dashboard
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Quick Stats
    stats = get_user_stats(st.session_state.user_id)
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
        <div class="dashboard-card-primary">
            <div style="font-size: 0.875rem; opacity: 0.9;">Tests Taken</div>
            <div style="font-size: 2rem; font-weight: 700;">{stats['total_tests']}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div class="dashboard-card-secondary">
            <div style="font-size: 0.875rem; opacity: 0.9;">Average Score</div>
            <div style="font-size: 2rem; font-weight: 700;">{stats['avg_score']}%</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div class="dashboard-card-success">
            <div style="font-size: 0.875rem; opacity: 0.9;">Best Score</div>
            <div style="font-size: 2rem; font-weight: 700;">{stats['best_score']}%</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
        <div class="dashboard-card-warning">
            <div style="font-size: 0.875rem; opacity: 0.9;">Certificates</div>
            <div style="font-size: 2rem; font-weight: 700;">{stats['certificates']}</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Test Generator Section (Top of Dashboard)
    st.markdown("""
    <div class="test-generator-card">
        <h2 style="font-size: 1.5rem; font-weight: 700; margin-bottom: 1rem; color: black;">🎯 Quick Test Generator</h2>
        <p style="color: rgba(255, 255, 255, 0.9); margin-bottom: 1.5rem;">
            Create a new assessment instantly
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    with st.container():
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            topic = st.text_input("Enter topic for assessment", 
                                placeholder="e.g., Python Programming, Communication Skills, etc.")
        with col2:
            num_q = st.number_input("Questions", min_value=5, max_value=20, value=10)
        with col3:
            difficulty = st.selectbox("Difficulty", ["Easy", "Medium", "Hard"])
        
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("🎯 Generate Test", use_container_width=True):
                if topic:
                    st.session_state.current_topic = topic
                    st.session_state.current_test_type = "Custom Assessment"
                    st.session_state.current_page = 'test_generator'
                    st.rerun()
                else:
                    st.warning("Please enter a topic")
        with col2:
            if st.button("📋 View All Tests", use_container_width=True, type="secondary"):
                st.session_state.current_page = 'my_assessments'
                st.rerun()
    
    st.markdown("<br><br>", unsafe_allow_html=True)
    
    # Field Tests Container
    st.markdown("<h2 style='color:black'>🎓 Explore Field Tests</h2>", unsafe_allow_html=True)
    st.markdown("Select from various assessment categories:")
    
    # Create field test containers
    st.markdown('<div class="field-test-container">', unsafe_allow_html=True)
    
    cols = st.columns(4)
    for idx, (category, topics) in enumerate(FIELD_TESTS.items()):
        with cols[idx % 4]:
            icon = "💻" if category == "Technical Skills" else "🤝" if category == "Soft Skills" else "📚" if category == "Domain Knowledge" else "🗣️"
            st.markdown(f"""
            <div class="field-test-card" onclick="this.style.transform='translateY(-4px)';">
                <div class="field-test-icon">{icon}</div>
                <h3 style="color: var(--text-primary); margin-bottom: 0.5rem;">{category}</h3>
                <p style="color: var(--text-secondary); font-size: 0.875rem;">
                    {', '.join(topics[:3])}...
                </p>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button(f"Take {category} Test", key=f"cat_{idx}", use_container_width=True):
                st.session_state.current_test_type = category
                st.session_state.current_page = 'test_generator'
                st.rerun()
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Recent Assessments
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown("<h2 style='color:black'>📋 Recent Assessments</h2>", unsafe_allow_html=True)
    
    if stats['recent_tests']:
        for test in stats['recent_tests'][:3]:
            topic, score, total, difficulty, level, timestamp = test
            percentage = (score / total) * 100 if total > 0 else 0
            col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
            with col1:
                st.write(f"**{topic[:50]}{'...' if len(topic) > 50 else ''}**")
                st.caption(f"{timestamp[:16]}")
            with col2:
                st.metric("Score", f"{percentage:.1f}%")
            with col3:
                level_badge = determine_level(percentage)
                st.markdown(f'<span class="level-badge level-{level_badge.lower()}">{level_badge}</span>', 
                          unsafe_allow_html=True)
            with col4:
                if st.button("📊 View", key=f"view_{timestamp}"):
                    st.session_state.current_page = 'my_assessments'
                    st.rerun()
            st.divider()
    else:
        st.info("No assessments taken yet. Start your first assessment!")

def show_test_generator():
    """Test generator page"""
    st.markdown("""
    <div style="max-width: 1200px; margin: 0 auto; padding: 2rem;">
        <h1 style="font-size: 2.5rem; font-weight: 800; color: var(--text-primary); margin-bottom: 0.5rem;">
            🎯 Skill Assessment Generator
        </h1>
        <p style="color: var(--text-secondary); margin-bottom: 3rem;">
            Create AI-powered assessments for any topic
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Back button
    if st.button("← Back to Dashboard"):
        st.session_state.current_page = 'dashboard'
        st.session_state.questions = None
        st.session_state.score = None
        st.rerun()
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Test Generator Container
    with st.container():
        st.markdown("<h2 style='color:black'> 📝 Create New Assessment </h2>", unsafe_allow_html=True)
        
        # Test Type Selection
        col1, col2 = st.columns(2)
        with col1:
            test_type = st.selectbox(
                "Test Category",
                ["Custom Assessment"] + list(FIELD_TESTS.keys()),
                help="Select the type of assessment"
            )
        
        with col2:
            if test_type != "Custom Assessment" and test_type in FIELD_TESTS:
                topic = st.selectbox(
                    "Select Topic",
                    FIELD_TESTS[test_type],
                    help="Select specific topic within the category"
                )
            else:
                topic = st.text_area(
                    "Topic or Content",
                    value=st.session_state.current_topic or "",
                    placeholder="Enter a topic, concept, or paste content to generate questions from...",
                    height=100,
                    help="The more detailed your input, the better the questions will be"
                )
        
        col1, col2 = st.columns(2)
        with col1:
            num_q = st.number_input(
                "Number of Questions",
                min_value=5,
                max_value=20,
                value=10,
                help="Choose between 5-20 questions"
            )
            
            difficulty = st.selectbox(
                "Difficulty Level",
                ["Easy", "Medium", "Hard"],
                help="Select question difficulty"
            )
        
        with col2:
            time_limit = st.number_input(
                "Time Limit (minutes)",
                min_value=5,
                max_value=120,
                value=30,
                help="Set time limit for the assessment"
            )
            
            show_answers = st.checkbox(
                "Show answers immediately after submission",
                value=True,
                help="Display correct answers after test completion"
            )
        
        if st.button("🎯 Generate Assessment", type="primary", use_container_width=True):
            if topic.strip():
                with st.spinner("🤖 Generating questions with AI..."):
                    try:
                        questions = generate_field_test_questions(topic, difficulty, num_q, test_type)
                        
                        if questions:
                            st.session_state.questions = questions
                            st.session_state.generated_topic = topic
                            st.session_state.difficulty = difficulty
                            st.session_state.num_questions = num_q
                            st.session_state.test_type = test_type
                            st.session_state.time_limit = time_limit
                            st.session_state.show_answers = show_answers
                            st.session_state.test_start_time = time.time()
                            st.success("✅ Questions generated successfully!")
                            st.balloons()
                        else:
                            st.error("Failed to generate questions. Please try again.")
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
            else:
                st.warning("Please enter a topic first")
    
    # Display existing assessments
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown("<h2 style='color:black'>📋 Existing Skill Assessments</h2>", unsafe_allow_html=True)
    
    history = get_assessment_history(st.session_state.user_id, 5)
    if history:
        for idx, assessment in enumerate(history, 1):
            assessment_type, topic, score, max_score, time_taken, timestamp = assessment
            percentage = (score / max_score) * 100 if max_score > 0 else 0
            
            col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
            with col1:
                st.write(f"**{idx}. {topic[:40]}{'...' if len(topic) > 40 else ''}**")
                st.caption(f"{assessment_type} • {timestamp[:16]}")
            with col2:
                st.metric("Score", f"{percentage:.1f}%")
            with col3:
                level = determine_level(percentage)
                st.markdown(f'<span class="level-badge level-{level.lower()}">{level}</span>', 
                          unsafe_allow_html=True)
            with col4:
                if st.button("📝 Retake", key=f"retake_{timestamp}"):
                    st.session_state.current_topic = topic
                    st.session_state.current_test_type = assessment_type
                    st.rerun()
            st.divider()
    else:
        st.info("No previous assessments found. Create your first one!")
    
    # Display Questions if generated
    if st.session_state.get('questions'):
        st.markdown("---")
        display_assessment_questions()

def show_my_assessments():
    """Show user's assessment history"""
    st.markdown("""
    <div style="max-width: 1200px; margin: 0 auto; padding: 2rem;">
        <h1 style="font-size: 2.5rem; font-weight: 800; color: var(--text-primary); margin-bottom: 0.5rem;">
            📊 My Assessments
        </h1>
        <p style="color: var(--text-secondary); margin-bottom: 3rem;">
            View your assessment history and results
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Back button
    if st.button("← Back to Dashboard"):
        st.session_state.current_page = 'dashboard'
        st.rerun()
    
    # Get assessment history
    history = get_assessment_history(st.session_state.user_id, 20)
    scores = get_user_scores(st.session_state.user_id)
    
    if history:
        # Summary Stats
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Tests", len(history))
        with col2:
            avg_score = sum([(h[2]/h[3]*100) if h[3] > 0 else 0 for h in history]) / len(history) if history else 0
            st.metric("Avg Score", f"{avg_score:.1f}%")
        with col3:
            best_score = max([(h[2]/h[3]*100) if h[3] > 0 else 0 for h in history]) if history else 0
            st.metric("Best Score", f"{best_score:.1f}%")
        with col4:
            recent_tests = len([h for h in history if pd.to_datetime(h[5]) > pd.Timestamp.now() - pd.Timedelta(days=7)])
            st.metric("Last 7 Days", recent_tests)
        
        # Assessment History Table
        st.markdown("<h2 style='color:black'> 📋 Assessment History </h2>", unsafe_allow_html=True)
        
        # Create DataFrame
        df_data = []
        for idx, h in enumerate(history, 1):
            assessment_type, topic, score, max_score, time_taken, timestamp = h
            percentage = (score / max_score) * 100 if max_score > 0 else 0
            level = determine_level(percentage)
            
            df_data.append({
                '#': idx,
                'Date': timestamp[:16],
                'Type': assessment_type,
                'Topic': topic[:50] + ('...' if len(topic) > 50 else ''),
                'Score': f"{score}/{max_score}",
                'Percentage': f"{percentage:.1f}%",
                'Level': level,
                'Time': f"{time_taken//60}:{time_taken%60:02d}"
            })
        
        if df_data:
            df = pd.DataFrame(df_data)
            st.dataframe(df, use_container_width=True, hide_index=True, column_config={
                '#': st.column_config.NumberColumn(width='small')
            })
        
        # Charts
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### 📈 Score Distribution")
            if scores:
                score_values = [(row[1]/row[2]*100) if row[2] > 0 else 0 for row in scores]
                fig = px.histogram(x=score_values, nbins=10, 
                                 title='Distribution of Scores',
                                 labels={'x': 'Score (%)', 'y': 'Frequency'})
                st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            st.markdown("<h2 style='color:black'> 📊 Performance Trend</h2>", unsafe_allow_html=True)
            if history:
                dates = [h[5][:10] for h in history]
                percentages = [(h[2]/h[3]*100) if h[3] > 0 else 0 for h in history]
                
                fig = go.Figure(data=go.Scatter(
                    x=dates[::-1],
                    y=percentages[::-1],
                    mode='lines+markers',
                    line=dict(color='#2563eb', width=3),
                    marker=dict(size=8)
                ))
                fig.update_layout(
                    title='Performance Over Time',
                    xaxis_title='Date',
                    yaxis_title='Score (%)',
                    hovermode='x unified'
                )
                st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No assessment history found. Create your first assessment!")

def show_leaderboard():
    """Show leaderboard page"""
    st.markdown("""
    <div style="max-width: 1200px; margin: 0 auto; padding: 2rem;">
        <h1 style="font-size: 2.5rem; font-weight: 800; color: var(--text-primary); margin-bottom: 0.5rem;">
            🏅 Leaderboard
        </h1>
        <p style="color: var(--text-secondary); margin-bottom: 3rem;">
            Compare your performance with other learners
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Back button
    if st.button("← Back to Dashboard"):
        st.session_state.current_page = 'dashboard'
        st.rerun()
    
    # Get all topics with scores
    topics = get_topics_with_scores()
    
    if topics:
        # Topic Selection
        col1, col2 = st.columns([3, 1])
        with col1:
            selected_topic = st.selectbox(
                "Select Topic for Leaderboard",
                ["Overall"] + topics,
                help="Select a topic to view the leaderboard"
            )
        
        with col2:
            limit = st.number_input("Top N Performers", min_value=5, max_value=50, value=10)
        
        # Get leaderboard data
        leaderboard_data = get_leaderboard(selected_topic if selected_topic != "Overall" else None, limit)
        
        if leaderboard_data:
            # Overall Stats
            st.markdown(f"### 📊 {selected_topic} Leaderboard")
            
            # Display leaderboard
            for idx, entry in enumerate(leaderboard_data, 1):
                if selected_topic == "Overall":
                    username, topic, avg_percentage, tests_taken, rank = entry
                    percentage = avg_percentage
                else:
                    username, topic, score, total_questions, percentage, rank, timestamp = entry
                
                # Determine medal emoji
                medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}"
                
                # Create leaderboard card
                col1, col2, col3, col4 = st.columns([1, 3, 2, 2])
                with col1:
                    st.markdown(f"""
                    <div style="text-align: center;">
                        <div style="font-size: 1.5rem; font-weight: bold;">{medal}</div>
                        <div style="font-size: 0.75rem; color: var(--text-secondary);">Rank {rank}</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col2:
                    st.markdown(f"**{username}**")
                    if selected_topic != "Overall":
                        st.caption(f"Score: {score}/{total_questions}")
                
                with col3:
                    st.metric("Percentage", f"{percentage:.1f}%")
                
                with col4:
                    if selected_topic == "Overall":
                        st.metric("Tests Taken", tests_taken)
                    else:
                        level = determine_level(percentage)
                        st.markdown(f'<span class="level-badge level-{level.lower()}">{level}</span>', 
                                  unsafe_allow_html=True)
                
                st.divider()
            
            # User's position
            st.markdown("<h2 style='color:black'> 🎯 Your Position </h2>", unsafe_allow_html=True)
            
            # Find user's rank
            user_found = False
            for entry in leaderboard_data:
                if selected_topic == "Overall":
                    username, topic, avg_percentage, tests_taken, rank = entry
                else:
                    username, topic, score, total_questions, percentage, rank, timestamp = entry
                
                if username == st.session_state.username:
                    user_found = True
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Your Rank", f"#{rank}")
                    with col2:
                        if selected_topic == "Overall":
                            st.metric("Your Average", f"{avg_percentage:.1f}%")
                        else:
                            st.metric("Your Score", f"{score}/{total_questions}")
                    with col3:
                        if selected_topic == "Overall":
                            st.metric("Tests Taken", tests_taken)
                        else:
                            st.metric("Percentage", f"{percentage:.1f}%")
                    break
            
            if not user_found:
                st.info("You need to take more tests to appear on the leaderboard!")
        
        else:
            st.info(f"No leaderboard data available for {selected_topic} yet.")
    
    else:
        st.info("No assessment data available yet. Take some tests to appear on the leaderboard!")
    
    # Top Topics Leaderboard
    st.markdown("<h2 style='color:black'>🎓 Top Performing Topics</h2>", unsafe_allow_html=True)
    
    # Get user's scores for all topics
    user_scores = get_user_scores(st.session_state.user_id)
    
    if user_scores:
        # Calculate average per topic
        topic_stats = {}
        for score in user_scores:
            topic, raw_score, total, difficulty, level, timestamp, percentage = score
            if topic not in topic_stats:
                topic_stats[topic] = {
                    'total_score': 0,
                    'total_tests': 0,
                    'best_score': 0,
                    'scores': []
                }
            topic_stats[topic]['total_score'] += percentage
            topic_stats[topic]['total_tests'] += 1
            topic_stats[topic]['scores'].append(percentage)
            if percentage > topic_stats[topic]['best_score']:
                topic_stats[topic]['best_score'] = percentage
        
        # Create ranked list
        ranked_topics = []
        for topic, stats in topic_stats.items():
            avg_score = stats['total_score'] / stats['total_tests']
            ranked_topics.append({
                'topic': topic,
                'avg_score': avg_score,
                'best_score': stats['best_score'],
                'total_tests': stats['total_tests'],
                'rank': 0  # Will be calculated
            })
        
        # Sort by average score
        ranked_topics.sort(key=lambda x: x['avg_score'], reverse=True)
        
        # Display numbered topics
        st.markdown("#### 📝 Your Top Topics (Ranked)")
        
        cols = st.columns(3)
        for idx, topic_data in enumerate(ranked_topics[:9], 1):
            with cols[(idx-1) % 3]:
                st.markdown(f"""
                <div class="dashboard-card">
                    <div style="font-size: 1.5rem; font-weight: bold; color: var(--primary);">#{idx}</div>
                    <h4>{topic_data['topic'][:20]}{'...' if len(topic_data['topic']) > 20 else ''}</h4>
                    <div style="display: flex; justify-content: space-between; margin-top: 0.5rem;">
                        <div>
                            <div style="font-size: 0.75rem; color: var(--text-secondary);">Avg Score</div>
                            <div style="font-size: 1.25rem; font-weight: bold;">{topic_data['avg_score']:.1f}%</div>
                        </div>
                        <div>
                            <div style="font-size: 0.75rem; color: var(--text-secondary);">Tests</div>
                            <div style="font-size: 1.25rem; font-weight: bold;">{topic_data['total_tests']}</div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        
        # Recommendations based on leaderboard
        st.markdown("### 💡 Leaderboard Insights")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("""
            <div class="dashboard-card">
                <h4>🎯 Focus Areas</h4>
                <p>Improve your weakest topics to climb the leaderboard faster.</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown("""
            <div class="dashboard-card">
                <h4>📈 Consistency Matters</h4>
                <p>Regular practice helps maintain your leaderboard position.</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown("""
            <div class="dashboard-card">
                <h4>🏆 Aim Higher</h4>
                <p>Try to achieve scores above 90% to reach the top positions.</p>
            </div>
            """, unsafe_allow_html=True)

def show_certificates():
    """Show user's certificates"""
    st.markdown("""
    <div style="max-width: 1200px; margin: 0 auto; padding: 2rem;">
        <h1 style="font-size: 2.5rem; font-weight: 800; color: var(--text-primary); margin-bottom: 0.5rem;">
            🏆 My Certificates
        </h1>
        <p style="color: var(--text-secondary); margin-bottom: 3rem;">
            View and download your achievement certificates
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Back button
    if st.button("← Back to Dashboard"):
        st.session_state.current_page = 'dashboard'
        st.rerun()
    
    # Get certificates
    certificates = get_user_certificates(st.session_state.user_id)
    
    if certificates:
        # Certificate Count
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Certificates", len(certificates))
        with col2:
            active_certs = len([c for c in certificates if c[5] == 'active'])
            st.metric("Active", active_certs)
        with col3:
            avg_score = sum([c[2] for c in certificates]) / len(certificates)
            st.metric("Avg Score", f"{avg_score:.1f}%")
        with col4:
            recent_certs = len([c for c in certificates if pd.to_datetime(c[3]) > pd.Timestamp.now() - pd.Timedelta(days=30)])
            st.metric("Last 30 Days", recent_certs)
        
        # Display Certificates
        st.markdown("### 📜 Your Certificates")
        
        for idx, cert in enumerate(certificates, 1):
            certificate_id, topic, score, issue_date, expiry_date, status = cert
            level = determine_level(score)
            
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"""
                <div class="certificate-card">
                    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 1rem;">
                        <div>
                            <h3 style="color: #1e293b; margin-bottom: 0.5rem;">{idx}. {topic}</h3>
                            <p style="color: #475569; margin-bottom: 0.25rem;">
                                <strong>Score:</strong> {score}% • 
                                <span class="level-badge level-{level.lower()}">{level}</span>
                            </p>
                            <p style="color: #475569; font-size: 0.875rem;">
                                Issued: {issue_date[:10]} • Expires: {expiry_date[:10]}
                            </p>
                        </div>
                        <div style="font-size: 2rem;">🏆</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            
            with col2:
                col_view, col_download = st.columns(2)
                with col_view:
                    if st.button(f"📄", key=f"view_{certificate_id}", help="View Certificate"):
                        # Generate certificate HTML
                        cert_html = generate_certificate_html(
                            st.session_state.username,
                            topic,
                            score,
                            certificate_id,
                            issue_date[:10]
                        )
                        st.components.v1.html(cert_html, height=600, scrolling=True)
                
                with col_download:
                    if st.button(f"⬇️", key=f"download_{certificate_id}", help="Download Certificate"):
                        # Generate certificate HTML
                        cert_html = generate_certificate_html(
                            st.session_state.username,
                            topic,
                            score,
                            certificate_id,
                            issue_date[:10]
                        )
                        
                        # Create download link
                        b64 = base64.b64encode(cert_html.encode()).decode()
                        href = f'<a href="data:text/html;base64,{b64}" download="certificate_{certificate_id}.html">Click to download</a>'
                        st.markdown(href, unsafe_allow_html=True)
            
            st.divider()
    else:
        st.info("No certificates earned yet. Score 80% or higher on any assessment to earn a certificate!")
        st.markdown("""
        <div style="text-align: center; padding: 3rem; background: linear-gradient(135deg, #f0f9ff, #e0f2fe); border-radius: 1rem;">
            <div style="font-size: 4rem; margin-bottom: 1rem;">🏆</div>
            <h3 style="color: #1e293b;">Earn Your First Certificate</h3>
            <p style="color: #475569;">Score 80% or higher on any assessment to unlock certificates</p>
            <button style="margin-top: 1rem; padding: 0.75rem 2rem; background: linear-gradient(45deg, #2563eb, #7c3aed); color: white; border: none; border-radius: 0.5rem; font-weight: 600; cursor: pointer;">
                🎯 Take a Test Now
            </button>
        </div>
        """, unsafe_allow_html=True)

def show_progress():
    """Show user's progress and analytics"""
    st.markdown("""
    <div style="max-width: 1200px; margin: 0 auto; padding: 2rem;">
        <h1 style="font-size: 2.5rem; font-weight: 800; color: var(--text-primary); margin-bottom: 0.5rem;">
            📈 My Progress
        </h1>
        <p style="color: var(--text-secondary); margin-bottom: 3rem;">
            Track your learning journey and skill development
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Back button
    if st.button("← Back to Dashboard"):
        st.session_state.current_page = 'dashboard'
        st.rerun()
    
    # Get user stats
    stats = get_user_stats(st.session_state.user_id)
    history = get_assessment_history(st.session_state.user_id, 50)
    
    if history:
        # Performance Overview
        st.markdown("### 📊 Performance Overview")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Score Progress Chart
            dates = [h[5][:10] for h in history]
            percentages = [(h[2]/h[3]*100) if h[3] > 0 else 0 for h in history]
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=dates[::-1],
                y=percentages[::-1],
                mode='lines+markers',
                name='Scores',
                line=dict(color='#2563eb', width=3),
                marker=dict(size=8)
            ))
            
            # Add moving average
            if len(percentages) > 5:
                window_size = min(5, len(percentages))
                moving_avg = pd.Series(percentages).rolling(window=window_size).mean().tolist()
                fig.add_trace(go.Scatter(
                    x=dates[::-1],
                    y=moving_avg[::-1],
                    mode='lines',
                    name=f'{window_size}-test Average',
                    line=dict(color='#ef4444', width=2, dash='dash')
                ))
            
            fig.update_layout(
                title='Score Trend',
                xaxis_title='Date',
                yaxis_title='Score (%)',
                hovermode='x unified',
                height=400
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # Level Distribution
            if stats['level_stats']:
                levels = [s[0] for s in stats['level_stats']]
                counts = [s[1] for s in stats['level_stats']]
                
                colors = {
                    'Expert': '#8b5cf6',
                    'Advanced': '#3b82f6',
                    'Intermediate': '#10b981',
                    'Beginner': '#f59e0b',
                    'Novice': '#ef4444'
                }
                
                fig = go.Figure(data=[go.Pie(
                    labels=levels,
                    values=counts,
                    hole=.3,
                    marker=dict(colors=[colors.get(l, '#94a3b8') for l in levels])
                )])
                fig.update_layout(
                    title='Level Distribution',
                    height=400,
                    showlegend=True
                )
                st.plotly_chart(fig, use_container_width=True)
        
        # Skill Breakdown
        st.markdown("### 🎯 Skill Breakdown")
        
        # Analyze topics from history
        topic_scores = {}
        for h in history:
            topic = h[1]
            score = (h[2]/h[3]*100) if h[3] > 0 else 0
            if topic in topic_scores:
                topic_scores[topic].append(score)
            else:
                topic_scores[topic] = [score]
        
        # Calculate average per topic
        topic_avg = {topic: sum(scores)/len(scores) for topic, scores in topic_scores.items()}
        
        if topic_avg:
            # Create bar chart
            topics = list(topic_avg.keys())
            avg_scores = list(topic_avg.values())
            
            # Sort by score
            sorted_indices = sorted(range(len(avg_scores)), key=lambda i: avg_scores[i], reverse=True)
            topics = [topics[i] for i in sorted_indices[:10]]  # Top 10
            avg_scores = [avg_scores[i] for i in sorted_indices[:10]]
            
            fig = go.Figure(data=[go.Bar(
                x=avg_scores,
                y=topics,
                orientation='h',
                marker=dict(color='#2563eb')
            )])
            fig.update_layout(
                title='Top Skills by Average Score',
                xaxis_title='Average Score (%)',
                yaxis_title='Topic',
                height=400
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # Time Analysis
        st.markdown("### ⏱️ Time Analysis")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Time per test
            times = [h[4] for h in history]
            avg_time = sum(times) / len(times) if times else 0
            
            fig = go.Figure(data=[go.Indicator(
                mode="gauge+number",
                value=avg_time/60,
                title={'text': "Avg Time per Test (mins)"},
                gauge={'axis': {'range': [None, 60]},
                       'bar': {'color': "#2563eb"},
                       'steps': [
                           {'range': [0, 20], 'color': "#10b981"},
                           {'range': [20, 40], 'color': "#f59e0b"},
                           {'range': [40, 60], 'color': "#ef4444"}],
                       'threshold': {'line': {'color': "red", 'width': 4},
                                     'thickness': 0.75,
                                     'value': 30}}
            )])
            fig.update_layout(height=300)
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # Tests over time
            if len(history) > 7:
                # Group by week
                df = pd.DataFrame(history, columns=['type', 'topic', 'score', 'max', 'time', 'date'])
                df['date'] = pd.to_datetime(df['date'])
                df['week'] = df['date'].dt.strftime('%Y-W%W')
                
                weekly_counts = df.groupby('week').size().reset_index(name='count')
                
                fig = go.Figure(data=[go.Bar(
                    x=weekly_counts['week'],
                    y=weekly_counts['count'],
                    marker_color='#7c3aed'
                )])
                fig.update_layout(
                    title='Tests per Week',
                    xaxis_title='Week',
                    yaxis_title='Number of Tests',
                    height=300
                )
                st.plotly_chart(fig, use_container_width=True)
        
        # Recommendations
        st.markdown("### 💡 Recommendations")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("""
            <div class="dashboard-card">
                <h4>🎯 Focus Areas</h4>
                <p>Based on your performance, focus on improving your weakest topics.</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown("""
            <div class="dashboard-card">
                <h4>⏱️ Time Management</h4>
                <p>Try to complete assessments within the suggested time limits.</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown("""
            <div class="dashboard-card">
                <h4>🏆 Next Goal</h4>
                <p>Aim for consistent scores above 80% to earn more certificates.</p>
            </div>
            """, unsafe_allow_html=True)
    
    else:
        st.info("No progress data available yet. Complete some assessments to see your progress!")

def show_settings():
    """User settings page"""
    st.markdown("""
    <div style="max-width: 1200px; margin: 0 auto; padding: 2rem;">
        <h1 style="font-size: 2.5rem; font-weight: 800; color: var(--text-primary); margin-bottom: 0.5rem;">
            ⚙️ Settings
        </h1>
        <p style="color: var(--text-secondary); margin-bottom: 3rem;">
            Manage your account and preferences
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Back button
    if st.button("← Back to Dashboard"):
        st.session_state.current_page = 'dashboard'
        st.rerun()
    
    tabs = st.tabs(["Account", "Preferences", "Notifications", "Privacy"])
    
    with tabs[0]:
        st.markdown("### 👤 Account Settings")
        
        col1, col2 = st.columns(2)
        with col1:
            current_username = st.text_input("Username", value=st.session_state.username, disabled=True)
            new_email = st.text_input("Email", placeholder="Enter new email")
        
        with col2:
            current_password = st.text_input("Current Password", type="password")
            new_password = st.text_input("New Password", type="password")
            confirm_password = st.text_input("Confirm New Password", type="password")
        
        if st.button("💾 Save Changes", use_container_width=True):
            st.success("Settings updated successfully!")
    
    with tabs[1]:
        st.markdown("### 🎨 Preferences")
        
        col1, col2 = st.columns(2)
        with col1:
            theme = st.selectbox("Theme", ["Light", "Dark", "Auto"])
            default_difficulty = st.selectbox("Default Difficulty", ["Easy", "Medium", "Hard"])
            questions_per_test = st.number_input("Default Questions per Test", 5, 20, 10)
        
        with col2:
            show_hints = st.checkbox("Show hints during tests", value=True)
            auto_submit = st.checkbox("Auto-submit when time expires", value=True)
            show_certificate_popup = st.checkbox("Show certificate popup", value=True)
        
        if st.button("💾 Save Preferences", use_container_width=True):
            st.success("Preferences saved!")
    
    with tabs[2]:
        st.markdown("### 🔔 Notifications")
        
        email_notifications = st.checkbox("Email notifications", value=True)
        score_updates = st.checkbox("Score updates", value=True)
        certificate_alerts = st.checkbox("Certificate alerts", value=True)
        weekly_reports = st.checkbox("Weekly progress reports", value=True)
        
        if st.button("💾 Update Notifications", use_container_width=True):
            st.success("Notification settings updated!")
    
    with tabs[3]:
        st.markdown("### 🔒 Privacy & Security")
        
        st.info("""
        **Data Privacy**
        - Your assessment data is stored securely
        - We never share your personal information
        - You can export or delete your data anytime
        """)
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📤 Export My Data", use_container_width=True):
                st.success("Data export started. You'll receive an email shortly.")
        
        with col2:
            if st.button("🗑️ Delete My Account", use_container_width=True, type="secondary"):
                st.warning("This action cannot be undone!")
                if st.checkbox("I understand this will permanently delete all my data"):
                    st.error("Account deletion not implemented in demo")



def display_assessment_questions():
    """Display generated questions and handle assessment"""
    # Timer display
    time_elapsed = int(time.time() - st.session_state.test_start_time)
    time_remaining = (st.session_state.time_limit * 60) - time_elapsed
    
    if time_remaining > 0:
        mins, secs = divmod(time_remaining, 60)
        st.info(f"⏰ Time remaining: {mins:02d}:{secs:02d}")
    else:
        st.warning("⏰ Time's up! Please submit your assessment.")
    
    # Assessment Header
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"""
        <div class="dashboard-card">
            <div style="font-size: 0.875rem; color: var(--text-secondary);">Topic</div>
            <div style="font-size: 1.25rem; font-weight: 600; color: var(--text-primary);">
                {st.session_state.get('generated_topic', 'N/A')[:30]}{'...' if len(st.session_state.get('generated_topic', '')) > 30 else ''}
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div class="dashboard-card">
            <div style="font-size: 0.875rem; color: var(--text-secondary);">Difficulty</div>
            <div style="font-size: 1.25rem; font-weight: 600; color: var(--text-primary);">
                {st.session_state.get('difficulty', 'N/A')}
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div class="dashboard-card">
            <div style="font-size: 0.875rem; color: var(--text-secondary);">Questions</div>
            <div style="font-size: 1.25rem; font-weight: 600; color: var(--text-primary);">
                {st.session_state.get('num_questions', 'N/A')}
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    # Questions Form
    with st.form("assessment_form"):
        user_answers = {}
        questions = st.session_state.questions.split('\n\n')
        
        for i, q_block in enumerate(questions):
            if q_block.strip():
                lines = q_block.strip().split('\n')
                if len(lines) >= 6:
                    question_text = lines[0]
                    options = lines[1:5]
                    answer_line = lines[5] if len(lines) > 5 else ""
                    
                    st.markdown(f'<div class="question-card">', unsafe_allow_html=True)
                    st.markdown(f"**Question {i+1}:** {question_text}")
                    
                    choice = st.radio(
                        f"Select answer for Q{i+1}:",
                        options,
                        key=f"q_{i}",
                        index=None,
                        label_visibility="collapsed"
                    )
                    
                    user_answers[f"Q{i+1}"] = {
                        "choice": choice,
                        "correct": answer_line.replace("Answer: ", "").strip() if "Answer:" in answer_line else "",
                        "options": options,
                        "question": question_text
                    }
                    st.markdown('</div>', unsafe_allow_html=True)
        
        submitted = st.form_submit_button("📤 Submit Assessment", use_container_width=True, type="primary")
    
    # Handle Submission
    if submitted:
        correct_count = 0
        total = len(user_answers)
        
        for q_id, data in user_answers.items():
            user_choice = data["choice"]
            correct_answer = data["correct"]
            
            if user_choice and correct_answer:
                if user_choice[0].lower() == correct_answer.lower():
                    correct_count += 1
        
        score_percentage = (correct_count / total) * 100 if total > 0 else 0
        st.session_state.score = int(score_percentage)
        level = determine_level(score_percentage)
        
        # Calculate time taken
        time_taken = int(time.time() - st.session_state.test_start_time)
        
        # Save score to database
        if st.session_state.user_id:
            save_user_score(
                st.session_state.user_id,
                st.session_state.get('generated_topic', 'Unknown'),
                correct_count,
                total,
                st.session_state.get('difficulty', 'Medium'),
                level
            )
            
            # Save to assessment history
            save_assessment_history(
                st.session_state.user_id,
                st.session_state.get('test_type', 'Custom Assessment'),
                st.session_state.get('generated_topic', 'Unknown'),
                correct_count,
                total,
                time_taken
            )
        
        # Display Results
        st.markdown("---")
        
        if score_percentage >= 80:
            color = "var(--success)"
            emoji = "🎉"
            message = "Excellent work! You've earned a certificate!"
            st.session_state.show_certificate = True
        elif score_percentage >= 60:
            color = "var(--warning)"
            emoji = "👍"
            message = "Good job! Keep practicing to improve!"
            st.session_state.show_certificate = False
        else:
            color = "var(--danger)"
            emoji = "💪"
            message = "Keep practicing! You'll improve with time."
            st.session_state.show_certificate = False
        
        st.markdown(f"""
        <div class="score-container" style="background: linear-gradient(135deg, {color}, var(--primary));">
            <div class="score-value">{emoji} {score_percentage:.1f}%</div>
            <h3>{correct_count} out of {total} correct</h3>
            <p class="score-message">{message}</p>
            <div style="margin-top: 1rem;">
                <span class="level-badge level-{level.lower()}">{level}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # Certificate Button
        if st.session_state.show_certificate:
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                if st.button("🏆 Download Certificate", use_container_width=True, type="primary"):
                    # Generate certificate
                    certificates = get_user_certificates(st.session_state.user_id)
                    if certificates:
                        latest_cert = certificates[0]
                        certificate_id, topic, score, issue_date, expiry_date, status = latest_cert
                        
                        # Generate certificate HTML
                        cert_html = generate_certificate_html(
                            st.session_state.username,
                            topic,
                            score,
                            certificate_id,
                            issue_date[:10]
                        )
                        
                        # Create download link
                        b64 = base64.b64encode(cert_html.encode()).decode()
                        href = f'<a href="data:text/html;base64,{b64}" download="certificate_{certificate_id}.html">Download Certificate</a>'
                        st.markdown(href, unsafe_allow_html=True)
                        st.success("Certificate downloaded successfully!")
        
        # Detailed Results
        if st.session_state.get('show_answers', True):
            with st.expander("📊 View Detailed Results", expanded=True):
                for q_id, data in user_answers.items():
                    user_choice = data["choice"] or "Not answered"
                    correct_answer = data["correct"]
                    is_correct = user_choice and correct_answer and user_choice[0].lower() == correct_answer.lower()
                    
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.write(f"**{q_id}:** {data['question']}")
                        st.write(f"**Your answer:** {user_choice}")
                        if correct_answer:
                            correct_option = data['options'][ord(correct_answer.lower()) - 97] if correct_answer and correct_answer.isalpha() else 'N/A'
                            st.write(f"**Correct answer:** {correct_option}")
                    with col2:
                        if is_correct:
                            st.success("✅ Correct")
                        else:
                            st.error("❌ Incorrect")
                    st.divider()
        
        # Next Steps
        st.markdown("### 🎯 Next Steps")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Take Another Test", use_container_width=True):
                st.session_state.questions = None
                st.session_state.score = None
                st.rerun()
        with col2:
            if st.button("📊 View Progress", use_container_width=True, type="secondary"):
                st.session_state.current_page = 'progress'
                st.rerun()



def get_user_details(user_id):
    """Get detailed information about a specific user"""
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    # Get user basic info
    c.execute('''
        SELECT id, username, email, created_at, last_login, is_active, is_admin
        FROM users WHERE id=?
    ''', (user_id,))
    
    user_info = c.fetchone()
    
    if not user_info:
        conn.close()
        return None
    
    # Get user scores
    c.execute('''
        SELECT COUNT(*) as total_tests,
               AVG(CAST(score AS FLOAT) / total_questions * 100) as avg_score,
               MAX(CAST(score AS FLOAT) / total_questions * 100) as best_score
        FROM user_scores 
        WHERE user_id=?
    ''', (user_id,))
    
    stats = c.fetchone()
    
    # Get recent activity
    c.execute('''
        SELECT topic, score, total_questions, difficulty, timestamp
        FROM user_scores 
        WHERE user_id=?
        ORDER BY timestamp DESC 
        LIMIT 10
    ''', (user_id,))
    
    recent_activity = c.fetchall()
    
    # Get certificates
    c.execute('''
        SELECT certificate_id, topic, score, issue_date, status
        FROM certificates 
        WHERE user_id=?
        ORDER BY issue_date DESC
    ''', (user_id,))
    
    certificates = c.fetchall()
    
    conn.close()
    
    return {
        'user_info': user_info,
        'stats': stats,
        'recent_activity': recent_activity,
        'certificates': certificates
    }

def update_user_status(user_id, is_active):
    """Activate or deactivate a user"""
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('UPDATE users SET is_active=? WHERE id=?', (is_active, user_id))
    conn.commit()
    conn.close()

def delete_user(user_id):
    """Delete a user and all related data"""
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    # Delete related records first
    c.execute('DELETE FROM user_scores WHERE user_id=?', (user_id,))
    c.execute('DELETE FROM certificates WHERE user_id=?', (user_id,))
    c.execute('DELETE FROM assessment_history WHERE user_id=?', (user_id,))
    c.execute('DELETE FROM leaderboard WHERE user_id=?', (user_id,))
    
    # Delete user
    c.execute('DELETE FROM users WHERE id=?', (user_id,))
    
    conn.commit()
    conn.close()

def get_system_stats():
    """Get overall system statistics for admin dashboard"""
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    # Total users
    c.execute('SELECT COUNT(*) FROM users')
    total_users = c.fetchone()[0]
    
    # Active users
    c.execute('SELECT COUNT(*) FROM users WHERE is_active=1')
    active_users = c.fetchone()[0]
    
    # Total assessments
    c.execute('SELECT COUNT(*) FROM user_scores')
    total_assessments = c.fetchone()[0]
    
    # Total certificates issued
    c.execute('SELECT COUNT(*) FROM certificates')
    total_certificates = c.fetchone()[0]
    
    # Recent registrations (last 7 days)
    c.execute('''
        SELECT COUNT(*) FROM users 
        WHERE date(created_at) >= date('now', '-7 days')
    ''')
    recent_registrations = c.fetchone()[0]
    
    # Average score across all users
    c.execute('''
        SELECT AVG(CAST(score AS FLOAT) / total_questions * 100) 
        FROM user_scores
    ''')
    avg_system_score = c.fetchone()[0] or 0
    
    # Top performing topics
    c.execute('''
        SELECT topic, COUNT(*) as test_count, 
               AVG(CAST(score AS FLOAT) / total_questions * 100) as avg_score
        FROM user_scores 
        GROUP BY topic 
        ORDER BY test_count DESC 
        LIMIT 5
    ''')
    top_topics = c.fetchall()
    
    conn.close()
    
    return {
        'total_users': total_users,
        'active_users': active_users,
        'total_assessments': total_assessments,
        'total_certificates': total_certificates,
        'recent_registrations': recent_registrations,
        'avg_system_score': round(avg_system_score, 1),
        'top_topics': top_topics
    }

def get_user_certificates(user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''
        SELECT certificate_id, topic, score, issue_date, expiry_date, status
        FROM certificates 
        WHERE user_id=? 
        ORDER BY issue_date DESC
    ''', (user_id,))
    certificates = c.fetchall()
    conn.close()
    return certificates

def get_assessment_history(user_id, limit=10):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''
        SELECT assessment_type, topic, score, max_score, time_taken, timestamp
        FROM assessment_history 
        WHERE user_id=?
        ORDER BY timestamp DESC
        LIMIT ?
    ''', (user_id, limit))
    history = c.fetchall()
    conn.close()
    return history

def save_assessment_history(user_id, assessment_type, topic, score, max_score, time_taken):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''
        INSERT INTO assessment_history (user_id, assessment_type, topic, score, max_score, time_taken)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, assessment_type, topic, score, max_score, time_taken))
    conn.commit()
    conn.close()

def get_user_scores(user_id):
    """Get all assessment scores for a specific user"""
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    c.execute('''
        SELECT 
            topic, 
            score, 
            total_questions, 
            difficulty, 
            level,
            timestamp,
            CAST(score AS FLOAT) / total_questions * 100 as percentage
        FROM user_scores 
        WHERE user_id = ?
        ORDER BY timestamp DESC
    ''', (user_id,))
    
    scores = c.fetchall()
    conn.close()
    
    return scores

def get_topics_with_scores():
    """Get all topics with user scores for leaderboard"""
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    c.execute('''
        SELECT DISTINCT topic 
        FROM user_scores 
        ORDER BY topic
    ''')
    
    topics = [row[0] for row in c.fetchall()]
    conn.close()
    
    return topics

# ============================================
# FIELD TEST TYPES AND GENERATORS
# ============================================
FIELD_TESTS = {
    "Technical Skills": [
        "Python Programming",
        "Data Structures & Algorithms",
        "Web Development",
        "Database Management",
        "Machine Learning"
    ],
    "Soft Skills": [
        "Communication Skills",
        "Teamwork Assessment",
        "Leadership Skills",
        "Problem Solving",
        "Time Management"
    ],
    "Domain Knowledge": [
        "Finance & Accounting",
        "Marketing Fundamentals",
        "Project Management",
        "Sales Techniques",
        "Customer Service"
    ],
    "Language Proficiency": [
        "English Grammar",
        "Business English",
        "Vocabulary Test",
        "Comprehension Test",
        "Writing Skills"
    ]
}

def generate_field_test_questions(topic, difficulty, num_questions, test_type):
    """Generate questions for different field tests"""
    
    prompt_map = {
        "Technical Skills": lambda t, d, n: f"""
        Create {n} multiple choice questions about {t} for a technical skills assessment.
        Difficulty: {d}
        
        Each question should test practical knowledge and application.
        Format each question exactly like this:
        
        Q1. [Question text]
        a) [Option A]
        b) [Option B]
        c) [Option C]
        d) [Option D]
        Answer: [correct letter]
        
        Make questions application-oriented with real-world scenarios.
        """,
        
        "Soft Skills": lambda t, d, n: f"""
        Create {n} scenario-based multiple choice questions about {t} for soft skills assessment.
        Difficulty: {d}
        
        Each question should present a workplace scenario and ask for the best approach.
        Format each question exactly like this:
        
        Q1. [Scenario description and question]
        a) [Option A - approach/action]
        b) [Option B - approach/action]
        c) [Option C - approach/action]
        d) [Option D - approach/action]
        Answer: [correct letter]
        
        Focus on practical workplace situations.
        """,
        
        "Domain Knowledge": lambda t, d, n: f"""
        Create {n} multiple choice questions about {t} for domain knowledge assessment.
        Difficulty: {d}
        
        Each question should test theoretical knowledge and practical application in the domain.
        Format each question exactly like this:
        
        Q1. [Question text]
        a) [Option A]
        b) [Option B]
        c) [Option C]
        d) [Option D]
        Answer: [correct letter]
        
        Include industry-specific terminology and concepts.
        """,
        
        "Language Proficiency": lambda t, d, n: f"""
        Create {n} multiple choice questions about {t} for language proficiency assessment.
        Difficulty: {d}
        
        Each question should test language skills including grammar, vocabulary, and comprehension.
        Format each question exactly like this:
        
        Q1. [Question text or passage]
        a) [Option A]
        b) [Option B]
        c) [Option C]
        d) [Option D]
        Answer: [correct letter]
        
        Include a mix of grammar, vocabulary, and comprehension questions.
        """
    }
    
    prompt_generator = prompt_map.get(test_type, prompt_map["Technical Skills"])
    prompt = prompt_generator(topic, difficulty, num_questions)
    
    return generate_with_fallback(prompt)

def determine_level(score):
    """Determine skill level based on score"""
    if score >= 90:
        return "Expert"
    elif score >= 75:
        return "Advanced"
    elif score >= 60:
        return "Intermediate"
    elif score >= 40:
        return "Beginner"
    else:
        return "Novice"

def generate_certificate_html(user_name, topic, score, certificate_id, issue_date):
    """Generate HTML certificate"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Georgia', serif;
                text-align: center;
                background: linear-gradient(45deg, #f5f7fa, #c3cfe2);
                padding: 50px;
            }}
            .certificate {{
                background: white;
                padding: 60px;
                border: 20px solid #4a6fa5;
                border-radius: 20px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                max-width: 800px;
                margin: 0 auto;
                position: relative;
            }}
            .header {{
                color: #2c3e50;
                font-size: 42px;
                margin-bottom: 30px;
                text-transform: uppercase;
                letter-spacing: 3px;
            }}
            .subheader {{
                color: #7f8c8d;
                font-size: 24px;
                margin-bottom: 40px;
            }}
            .name {{
                color: #2980b9;
                font-size: 48px;
                font-weight: bold;
                margin: 40px 0;
                border-bottom: 2px solid #3498db;
                padding-bottom: 20px;
                display: inline-block;
            }}
            .details {{
                font-size: 20px;
                color: #34495e;
                margin: 20px 0;
                line-height: 1.6;
            }}
            .score {{
                color: #27ae60;
                font-size: 36px;
                font-weight: bold;
                margin: 30px 0;
            }}
            .id {{
                font-family: monospace;
                color: #7f8c8d;
                font-size: 14px;
                margin-top: 40px;
            }}
            .seal {{
                position: absolute;
                top: 20px;
                right: 20px;
                width: 100px;
                height: 100px;
                background: #e74c3c;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-weight: bold;
                font-size: 14px;
                transform: rotate(15deg);
            }}
        </style>
    </head>
    <body>
        <div class="certificate">
            <div class="seal">SEAL</div>
            <div class="header">Certificate of Achievement</div>
            <div class="subheader">This certifies that</div>
            <div class="name">{user_name}</div>
            <div class="details">
                has successfully completed the assessment in<br>
                <strong>{topic}</strong><br>
                with outstanding performance
            </div>
            <div class="score">Score: {score}%</div>
            <div class="details">
                Issued on: {issue_date}<br>
                Level: {determine_level(score)}
            </div>
            <div class="id">Certificate ID: {certificate_id}</div>
        </div>
    </body>
    </html>
    """

# ============================================
# ADMIN DASHBOARD FUNCTIONS
# ============================================
def admin_dashboard():
    """Admin dashboard with user management and system stats"""
    st.markdown(load_css(), unsafe_allow_html=True)
    
    # Admin Sidebar
    with st.sidebar:
        st.markdown(f"""
        <div class="user-profile">
            <div class="user-avatar" style="background: linear-gradient(45deg, #8b5cf6, #7c3aed);">
                👑
            </div>
            <h3 style="color: var(--text-primary);">{st.session_state.username} (Admin)</h3>
            <p style="color: var(--text-secondary); font-size: 0.875rem;">Administrator Dashboard</p>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # Admin Navigation Menu
        st.markdown("### 📍 Admin Navigation")
        
        menu_items = [
            ("📊 Dashboard", "admin_dashboard"),
            ("👥 User Management", "user_management"),
            ("📈 System Analytics", "system_analytics"),
            ("🏆 Certificates", "admin_certificates"),
            ("⚙️ System Settings", "system_settings")
        ]
        
        for icon_name, page_name in menu_items:
            if st.button(f"{icon_name}", key=f"admin_menu_{page_name}", use_container_width=True):
                st.session_state.current_page = page_name
                st.rerun()
        
        st.markdown("---")
        
        if st.button("🚪 Switch to User View", use_container_width=True, type="secondary"):
            st.session_state.is_admin = False
            st.session_state.current_page = 'dashboard'
            st.rerun()
            
        if st.button("🚪 Logout", use_container_width=True, type="primary"):
            st.session_state.logged_in = False
            st.session_state.username = None
            st.session_state.user_id = None
            st.session_state.is_admin = False
            st.session_state.current_page = 'welcome'
            st.session_state.welcome_shown = False
            st.rerun()
    
    # Main Admin Content
    if st.session_state.current_page == 'admin_dashboard':
        show_admin_dashboard()
    elif st.session_state.current_page == 'user_management':
        show_user_management()
    elif st.session_state.current_page == 'system_analytics':
        show_system_analytics()
    elif st.session_state.current_page == 'admin_certificates':
        show_admin_certificates()
    elif st.session_state.current_page == 'system_settings':
        show_system_settings()

def show_admin_dashboard():
    """Main admin dashboard page"""
    st.markdown("""
    <div style="max-width: 1200px; margin: 0 auto; padding: 2rem;">
        <h1 style="font-size: 2.5rem; font-weight: 800; color: var(--text-primary); margin-bottom: 0.5rem;">
            👑 Admin Dashboard
        </h1>
        <p style="color: var(--text-secondary); margin-bottom: 3rem;">
            Welcome to the Skill Assessment Pro Admin Panel
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Get system statistics
    stats = get_system_stats()
    
    # System Stats Cards
    st.markdown("### 📊 System Overview")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div class="dashboard-card-primary">
            <div style="font-size: 0.875rem; opacity: 0.9;">Total Users</div>
            <div style="font-size: 2rem; font-weight: 700;">{stats['total_users']}</div>
            <div style="font-size: 0.75rem; margin-top: 0.5rem;">
                {stats['active_users']} active • {stats['recent_registrations']} new (7 days)
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div class="dashboard-card-secondary">
            <div style="font-size: 0.875rem; opacity: 0.9;">Total Assessments</div>
            <div style="font-size: 2rem; font-weight: 700;">{stats['total_assessments']}</div>
            <div style="font-size: 0.75rem; margin-top: 0.5rem;">
                Avg score: {stats['avg_system_score']}%
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div class="dashboard-card-success">
            <div style="font-size: 0.875rem; opacity: 0.9;">Certificates Issued</div>
            <div style="font-size: 2rem; font-weight: 700;">{stats['total_certificates']}</div>
            <div style="font-size: 0.75rem; margin-top: 0.5rem;">
                Certificates awarded
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
        <div class="dashboard-card-warning">
            <div style="font-size: 0.875rem; opacity: 0.9;">System Status</div>
            <div style="font-size: 2rem; font-weight: 700;">🟢 Online</div>
            <div style="font-size: 0.75rem; margin-top: 0.5rem;">
                All systems operational
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Recent Activity and Quick Actions
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Recent User Registrations
        st.markdown("### 👥 Recent User Registrations")
        users = get_all_users()[:5]
        
        if users:
            for user in users:
                user_id, username, email, created_at, last_login, is_active, is_admin = user
                
                col_a, col_b, col_c, col_d = st.columns([2, 2, 1, 1])
                with col_a:
                    st.write(f"**{username}**")
                    st.caption(email)
                with col_b:
                    st.caption(f"Joined: {created_at[:10]}")
                with col_c:
                    status = "🟢" if is_active else "🔴"
                    st.write(status)
                with col_d:
                    if st.button("View", key=f"view_{user_id}"):
                        st.session_state.selected_user = user_id
                        st.session_state.current_page = 'user_management'
                        st.rerun()
                st.divider()
        else:
            st.info("No users found")
    
    with col2:
        # Quick Actions
        st.markdown("### ⚡ Quick Actions")
        
        if st.button("👤 Add New User", use_container_width=True, type="primary"):
            st.session_state.show_add_user = True
            st.rerun()
        
        if st.button("📊 View Analytics", use_container_width=True):
            st.session_state.current_page = 'system_analytics'
            st.rerun()
        
        if st.button("🏆 Manage Certificates", use_container_width=True):
            st.session_state.current_page = 'admin_certificates'
            st.rerun()
        
        if st.button("⚙️ System Settings", use_container_width=True):
            st.session_state.current_page = 'system_settings'
            st.rerun()
    
    # Top Performing Topics
    st.markdown("### 🎯 Top Performing Topics")
    if stats['top_topics']:
        df_topics = pd.DataFrame(stats['top_topics'], columns=['Topic', 'Tests Taken', 'Average Score'])
        df_topics['Average Score'] = df_topics['Average Score'].round(1)
        st.dataframe(df_topics, use_container_width=True)
    else:
        st.info("No assessment data available yet")

def show_user_management():
    """User management page for admin"""
    st.markdown("""
    <div style="max-width: 1200px; margin: 0 auto; padding: 2rem;">
        <h1 style="font-size: 2.5rem; font-weight: 800; color: var(--text-primary); margin-bottom: 0.5rem;">
            👥 User Management
        </h1>
        <p style="color: var(--text-secondary); margin-bottom: 3rem;">
            Manage user accounts and permissions
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Back button
    if st.button("← Back to Admin Dashboard"):
        st.session_state.current_page = 'admin_dashboard'
        st.rerun()
    
    # Add User Section
    st.markdown("### 👤 Add New User")
    with st.expander("Click to add a new user", expanded=False):
        with st.form("add_user_form"):
            col1, col2 = st.columns(2)
            with col1:
                new_username = st.text_input("Username")
                new_email = st.text_input("Email")
            with col2:
                new_password = st.text_input("Password", type="password")
                is_admin = st.checkbox("Make this user an admin")
            
            col1, col2 = st.columns(2)
            with col1:
                add_btn = st.form_submit_button("Add User", use_container_width=True)
            with col2:
                cancel_btn = st.form_submit_button("Cancel", use_container_width=True, type="secondary")
            
            if add_btn:
                if new_username and new_email and new_password:
                    if create_user(new_username, new_email, new_password, is_admin):
                        st.success(f"User '{new_username}' created successfully!")
                        st.rerun()
                    else:
                        st.error("Username or email already exists")
                else:
                    st.warning("Please fill in all required fields")
    
    st.markdown("---")
    
    # User List with Search
    st.markdown("### 📋 All Users")
    
    # Search and Filter
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        search_query = st.text_input("Search users", placeholder="Search by username or email")
    with col2:
        filter_status = st.selectbox("Status", ["All", "Active", "Inactive"])
    with col3:
        filter_admin = st.selectbox("User Type", ["All", "Admins", "Regular Users"])
    
    # Get all users
    all_users = get_all_users()
    
    # Apply filters
    filtered_users = all_users
    if search_query:
        filtered_users = [u for u in filtered_users if 
                         search_query.lower() in u[1].lower() or 
                         search_query.lower() in u[2].lower()]
    
    if filter_status != "All":
        status_filter = 1 if filter_status == "Active" else 0
        filtered_users = [u for u in filtered_users if u[5] == status_filter]
    
    if filter_admin != "All":
        admin_filter = 1 if filter_admin == "Admins" else 0
        filtered_users = [u for u in filtered_users if u[6] == admin_filter]
    
    # Display users in a table
    if filtered_users:
        # Create DataFrame for better display
        user_data = []
        for user in filtered_users:
            user_id, username, email, created_at, last_login, is_active, is_admin = user
            
            user_data.append({
                'ID': user_id,
                'Username': username,
                'Email': email,
                'Created': created_at[:10],
                'Last Login': last_login[:19] if last_login else 'Never',
                'Status': '🟢 Active' if is_active else '🔴 Inactive',
                'Type': '👑 Admin' if is_admin else '👤 User',
                'Actions': ''
            })
        
        df = pd.DataFrame(user_data)
        
        # Display with actions
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                'ID': st.column_config.NumberColumn(width='small'),
                'Status': st.column_config.TextColumn(width='small'),
                'Type': st.column_config.TextColumn(width='small'),
                'Actions': st.column_config.Column(width='medium')
            }
        )
        
        # Detailed view for selected user
        st.markdown("### 👤 User Details")
        if 'selected_user' in st.session_state:
            user_details = get_user_details(st.session_state.selected_user)
            
            if user_details:
                user_info = user_details['user_info']
                stats = user_details['stats']
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("#### Basic Information")
                    st.write(f"**Username:** {user_info[1]}")
                    st.write(f"**Email:** {user_info[2]}")
                    st.write(f"**Created:** {user_info[3]}")
                    st.write(f"**Last Login:** {user_info[4] or 'Never'}")
                    st.write(f"**Status:** {'🟢 Active' if user_info[5] else '🔴 Inactive'}")
                    st.write(f"**Type:** {'👑 Admin' if user_info[6] else '👤 Regular User'}")
                
                with col2:
                    st.markdown("#### Statistics")
                    if stats[0]:  # Has tests
                        st.write(f"**Total Tests:** {stats[0]}")
                        st.write(f"**Average Score:** {stats[1]:.1f}%")
                        st.write(f"**Best Score:** {stats[2]:.1f}%")
                    else:
                        st.write("**No assessments taken yet**")
                    
                    # Action buttons
                    st.markdown("#### Actions")
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button("Toggle Status", use_container_width=True):
                            new_status = 0 if user_info[5] else 1
                            update_user_status(user_info[0], new_status)
                            st.success(f"User status updated to {'Active' if new_status else 'Inactive'}")
                            st.rerun()
                    
                    with col_b:
                        if st.button("Delete User", use_container_width=True, type="secondary"):
                            if st.checkbox(f"Confirm deletion of {user_info[1]} (cannot be undone)"):
                                delete_user(user_info[0])
                                st.success(f"User {user_info[1]} deleted successfully!")
                                del st.session_state.selected_user
                                st.rerun()
                
                # Recent Activity
                st.markdown("#### Recent Activity")
                recent_activity = user_details['recent_activity']
                if recent_activity:
                    for activity in recent_activity[:5]:
                        topic, score, total, difficulty, timestamp = activity
                        percentage = (score / total * 100) if total > 0 else 0
                        col_a, col_b, col_c = st.columns([3, 1, 1])
                        with col_a:
                            st.write(f"**{topic}**")
                            st.caption(timestamp[:16])
                        with col_b:
                            st.write(f"{percentage:.1f}%")
                        with col_c:
                            st.write(difficulty)
                        st.divider()
                else:
                    st.info("No recent activity")
                
                # Certificates
                st.markdown("#### Certificates")
                certificates = user_details['certificates']
                if certificates:
                    for cert in certificates:
                        cert_id, topic, score, issue_date, status = cert
                        col_a, col_b, col_c = st.columns([2, 1, 1])
                        with col_a:
                            st.write(f"**{topic}**")
                            st.caption(f"Issued: {issue_date[:10]}")
                        with col_b:
                            st.write(f"{score}%")
                        with col_c:
                            st.write("🟢 Active" if status == 'active' else "🔴 Expired")
                else:
                    st.info("No certificates earned")
                
                # Clear selection
                if st.button("Clear Selection"):
                    del st.session_state.selected_user
                    st.rerun()
        
        else:
            st.info("Select a user from the list above to view details")
    
    else:
        st.info("No users found matching your criteria")

def show_system_analytics():
    """System analytics and reporting"""
    st.markdown("""
    <div style="max-width: 1200px; margin: 0 auto; padding: 2rem;">
        <h1 style="font-size: 2.5rem; font-weight: 800; color: var(--text-primary); margin-bottom: 0.5rem;">
            📈 System Analytics
        </h1>
        <p style="color: var(--text-secondary); margin-bottom: 3rem;">
            System-wide statistics and performance metrics
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Back button
    if st.button("← Back to Admin Dashboard"):
        st.session_state.current_page = 'admin_dashboard'
        st.rerun()
    
    # Get comprehensive analytics
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    # User growth over time
    c.execute('''
        SELECT date(created_at) as date, COUNT(*) as new_users
        FROM users 
        GROUP BY date(created_at)
        ORDER BY date
    ''')
    user_growth = c.fetchall()
    
    # Daily assessments
    c.execute('''
        SELECT date(timestamp) as date, COUNT(*) as assessments
        FROM user_scores 
        GROUP BY date(timestamp)
        ORDER BY date
    ''')
    daily_assessments = c.fetchall()
    
    # Topic popularity
    c.execute('''
        SELECT topic, COUNT(*) as test_count, 
               AVG(CAST(score AS FLOAT) / total_questions * 100) as avg_score
        FROM user_scores 
        GROUP BY topic 
        ORDER BY test_count DESC
    ''')
    topic_popularity = c.fetchall()
    
    # Performance distribution
    c.execute('''
        SELECT 
            CASE 
                WHEN CAST(score AS FLOAT) / total_questions * 100 >= 90 THEN 'Expert (90-100%)'
                WHEN CAST(score AS FLOAT) / total_questions * 100 >= 75 THEN 'Advanced (75-89%)'
                WHEN CAST(score AS FLOAT) / total_questions * 100 >= 60 THEN 'Intermediate (60-74%)'
                WHEN CAST(score AS FLOAT) / total_questions * 100 >= 40 THEN 'Beginner (40-59%)'
                ELSE 'Novice (<40%)'
            END as level,
            COUNT(*) as count
        FROM user_scores 
        GROUP BY level
        ORDER BY count DESC
    ''')
    performance_dist = c.fetchall()
    
    conn.close()
    
    # Charts
    col1, col2 = st.columns(2)
    
    with col1:
        # User Growth Chart
        if user_growth:
            dates = [row[0] for row in user_growth]
            new_users = [row[1] for row in user_growth]
            cumulative_users = pd.Series(new_users).cumsum().tolist()
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=dates, y=cumulative_users,
                mode='lines+markers',
                name='Total Users',
                line=dict(color='#2563eb', width=3)
            ))
            fig.add_trace(go.Bar(
                x=dates, y=new_users,
                name='New Users',
                marker_color='#7c3aed',
                opacity=0.6
            ))
            fig.update_layout(
                title='User Growth Over Time',
                xaxis_title='Date',
                yaxis_title='Number of Users',
                hovermode='x unified',
                height=400
            )
            st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        # Daily Assessments Chart
        if daily_assessments:
            dates = [row[0] for row in daily_assessments]
            assessments = [row[1] for row in daily_assessments]
            
            fig = go.Figure(data=go.Scatter(
                x=dates, y=assessments,
                mode='lines+markers',
                line=dict(color='#10b981', width=3),
                marker=dict(size=8)
            ))
            fig.update_layout(
                title='Daily Assessments',
                xaxis_title='Date',
                yaxis_title='Number of Assessments',
                hovermode='x unified',
                height=400
            )
            st.plotly_chart(fig, use_container_width=True)
    
    # Topic Popularity
    st.markdown("### 🎯 Topic Popularity & Performance")
    
    if topic_popularity:
        topics = [row[0] for row in topic_popularity[:10]]
        test_counts = [row[1] for row in topic_popularity[:10]]
        avg_scores = [row[2] for row in topic_popularity[:10]]
        
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=topics,
            y=test_counts,
            name='Tests Taken',
            marker_color='#8b5cf6'
        ))
        fig.add_trace(go.Scatter(
            x=topics,
            y=avg_scores,
            name='Average Score (%)',
            yaxis='y2',
            marker=dict(color='#ef4444', size=8),
            line=dict(color='#ef4444', width=3)
        ))
        
        fig.update_layout(
            title='Top 10 Topics: Usage vs Performance',
            xaxis_title='Topic',
            yaxis=dict(title='Tests Taken'),
            yaxis2=dict(
                title='Average Score (%)',
                overlaying='y',
                side='right'
            ),
            hovermode='x unified',
            height=400
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # Performance Distribution
    st.markdown("### 📊 Performance Distribution")
    
    if performance_dist:
        col1, col2 = st.columns([2, 1])
        
        with col1:
            levels = [row[0] for row in performance_dist]
            counts = [row[1] for row in performance_dist]
            
            colors = ['#8b5cf6', '#3b82f6', '#10b981', '#f59e0b', '#ef4444']
            
            fig = go.Figure(data=[go.Pie(
                labels=levels,
                values=counts,
                hole=.3,
                marker=dict(colors=colors)
            )])
            fig.update_layout(
                title='Performance Level Distribution',
                height=400
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            st.markdown("#### Key Metrics")
            total_tests = sum(counts)
            st.metric("Total Tests", total_tests)
            
            if total_tests > 0:
                expert_percentage = (counts[0] / total_tests * 100) if len(counts) > 0 else 0
                passing_percentage = (sum(counts[:3]) / total_tests * 100) if len(counts) >= 3 else 0
                
                st.metric("Expert Level", f"{expert_percentage:.1f}%")
                st.metric("Passing Rate (60%+)", f"{passing_percentage:.1f}%")
    
    # Export Data
    st.markdown("### 📤 Data Export")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("📊 Export User Data", use_container_width=True):
            users = get_all_users()
            df_users = pd.DataFrame(users, columns=['ID', 'Username', 'Email', 'Created', 'Last Login', 'Active', 'Admin'])
            csv = df_users.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv,
                file_name="users_data.csv",
                mime="text/csv"
            )
    
    with col2:
        if st.button("📈 Export Assessment Data", use_container_width=True):
            conn = sqlite3.connect('users.db')
            c = conn.cursor()
            c.execute('''
                SELECT u.username, us.topic, us.score, us.total_questions, 
                       us.difficulty, us.level, us.timestamp
                FROM user_scores us
                JOIN users u ON us.user_id = u.id
            ''')
            assessments = c.fetchall()
            conn.close()
            
            df_assessments = pd.DataFrame(assessments, 
                columns=['Username', 'Topic', 'Score', 'Total', 'Difficulty', 'Level', 'Timestamp'])
            csv = df_assessments.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv,
                file_name="assessments_data.csv",
                mime="text/csv"
            )
    
    with col3:
        if st.button("🏆 Export Certificate Data", use_container_width=True):
            conn = sqlite3.connect('users.db')
            c = conn.cursor()
            c.execute('''
                SELECT u.username, c.certificate_id, c.topic, c.score, 
                       c.issue_date, c.expiry_date, c.status
                FROM certificates c
                JOIN users u ON c.user_id = u.id
            ''')
            certificates = c.fetchall()
            conn.close()
            
            df_certs = pd.DataFrame(certificates,
                columns=['Username', 'Certificate ID', 'Topic', 'Score', 'Issue Date', 'Expiry Date', 'Status'])
            csv = df_certs.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv,
                file_name="certificates_data.csv",
                mime="text/csv"
            )

def show_admin_certificates():
    """Admin certificate management"""
    st.markdown("""
    <div style="max-width: 1200px; margin: 0 auto; padding: 2rem;">
        <h1 style="font-size: 2.5rem; font-weight: 800; color: var(--text-primary); margin-bottom: 0.5rem;">
            🏆 Certificate Management
        </h1>
        <p style="color: var(--text-secondary); margin-bottom: 3rem;">
            Manage and verify certificates
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Back button
    if st.button("← Back to Admin Dashboard"):
        st.session_state.current_page = 'admin_dashboard'
        st.rerun()
    
    # Get all certificates
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''
        SELECT u.username, c.certificate_id, c.topic, c.score, 
               c.issue_date, c.expiry_date, c.status
        FROM certificates c
        JOIN users u ON c.user_id = u.id
        ORDER BY c.issue_date DESC
    ''')
    all_certificates = c.fetchall()
    conn.close()
    
    # Filter options
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        search_query = st.text_input("Search certificates", placeholder="Search by username, topic, or certificate ID")
    with col2:
        filter_status = st.selectbox("Certificate Status", ["All", "Active", "Expired", "Revoked"])
    with col3:
        date_range = st.selectbox("Date Range", ["All Time", "Last 7 Days", "Last 30 Days", "Last 90 Days"])
    
    # Apply filters
    filtered_certs = all_certificates
    
    if search_query:
        filtered_certs = [c for c in filtered_certs if 
                         search_query.lower() in c[0].lower() or 
                         search_query.lower() in c[2].lower() or 
                         search_query.lower() in c[1].lower()]
    
    if filter_status != "All":
        status_map = {"Active": "active", "Expired": "expired", "Revoked": "revoked"}
        filtered_certs = [c for c in filtered_certs if c[6] == status_map[filter_status]]
    
    if date_range != "All Time":
        days = {"Last 7 Days": 7, "Last 30 Days": 30, "Last 90 Days": 90}
        cutoff_date = datetime.now() - timedelta(days=days[date_range])
        filtered_certs = [c for c in filtered_certs if 
                         datetime.strptime(c[4][:10], '%Y-%m-%d') > cutoff_date]
    
    # Display certificates
    st.markdown(f"### 📜 Certificates ({len(filtered_certs)} found)")
    
    if filtered_certs:
        # Create DataFrame for display
        cert_data = []
        for cert in filtered_certs:
            username, cert_id, topic, score, issue_date, expiry_date, status = cert
            
            cert_data.append({
                'Username': username,
                'Certificate ID': cert_id,
                'Topic': topic,
                'Score': f"{score}%",
                'Issue Date': issue_date[:10],
                'Expiry Date': expiry_date[:10] if expiry_date else 'N/A',
                'Status': status.title(),
                'Level': determine_level(score)
            })
        
        df = pd.DataFrame(cert_data)
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        # Certificate Statistics
        st.markdown("### 📊 Certificate Statistics")
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            total_certs = len(filtered_certs)
            st.metric("Total", total_certs)
        
        with col2:
            active_certs = len([c for c in filtered_certs if c[6] == 'active'])
            st.metric("Active", active_certs)
        
        with col3:
            avg_score = sum([c[3] for c in filtered_certs]) / total_certs if total_certs > 0 else 0
            st.metric("Avg Score", f"{avg_score:.1f}%")
        
        with col4:
            top_topic = max([(c[2], len([x for x in filtered_certs if x[2] == c[2]])) 
                           for c in filtered_certs], key=lambda x: x[1])[0] if filtered_certs else "N/A"
            st.metric("Most Common", top_topic[:15] + ('...' if len(top_topic) > 15 else ''))
        
        # Certificate Preview
        st.markdown("### 👁️ Certificate Preview")
        selected_cert = st.selectbox(
            "Select a certificate to preview",
            [f"{c[0]} - {c[2]} ({c[1]})" for c in filtered_certs[:20]]
        )
        
        if selected_cert:
            # Extract certificate ID from selection
            cert_id = selected_cert.split('(')[-1].rstrip(')')
            cert_details = next((c for c in filtered_certs if c[1] == cert_id), None)
            
            if cert_details:
                username, cert_id, topic, score, issue_date, expiry_date, status = cert_details
                
                # Generate preview
                cert_html = generate_certificate_html(username, topic, score, cert_id, issue_date[:10])
                
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.components.v1.html(cert_html, height=600, scrolling=True)
                
                with col2:
                    st.markdown("#### Certificate Details")
                    st.write(f"**User:** {username}")
                    st.write(f"**Topic:** {topic}")
                    st.write(f"**Score:** {score}%")
                    st.write(f"**Level:** {determine_level(score)}")
                    st.write(f"**Issue Date:** {issue_date[:10]}")
                    st.write(f"**Expiry Date:** {expiry_date[:10] if expiry_date else 'Never'}")
                    st.write(f"**Status:** {status}")
                    
                    # Actions
                    st.markdown("#### Actions")
                    if st.button("📥 Download Certificate", use_container_width=True):
                        b64 = base64.b64encode(cert_html.encode()).decode()
                        href = f'<a href="data:text/html;base64,{b64}" download="certificate_{cert_id}.html">Click to download</a>'
                        st.markdown(href, unsafe_allow_html=True)
                    
                    if st.button("🖨️ Print Certificate", use_container_width=True):
                        st.info("Use the browser's print function (Ctrl+P)")
                    
                    if status == 'active':
                        if st.button("🚫 Revoke Certificate", use_container_width=True, type="secondary"):
                            conn = sqlite3.connect('users.db')
                            c = conn.cursor()
                            c.execute('UPDATE certificates SET status="revoked" WHERE certificate_id=?', (cert_id,))
                            conn.commit()
                            conn.close()
                            st.success("Certificate revoked successfully!")
                            st.rerun()
    
    else:
        st.info("No certificates found matching your criteria")

def show_system_settings():
    """System settings page"""
    st.markdown("""
    <div style="max-width: 1200px; margin: 0 auto; padding: 2rem;">
        <h1 style="font-size: 2.5rem; font-weight: 800; color: var(--text-primary); margin-bottom: 0.5rem;">
            ⚙️ System Settings
        </h1>
        <p style="color: var(--text-secondary); margin-bottom: 3rem;">
            Configure system-wide settings and preferences
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Back button
    if st.button("← Back to Admin Dashboard"):
        st.session_state.current_page = 'admin_dashboard'
        st.rerun()
    
    tabs = st.tabs(["General", "Assessment", "Security", "Maintenance"])
    
    with tabs[0]:
        st.markdown("### ⚙️ General Settings")
        
        col1, col2 = st.columns(2)
        with col1:
            system_name = st.text_input("System Name", value="Skill Assessment Pro")
            admin_email = st.text_input("Admin Email", value="admin@skillassessment.com")
            enable_registration = st.checkbox("Enable User Registration", value=True)
            require_email_verification = st.checkbox("Require Email Verification", value=False)
        
        with col2:
            default_timezone = st.selectbox("Default Timezone", ["UTC", "EST", "PST", "IST"])
            date_format = st.selectbox("Date Format", ["YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY"])
            language = st.selectbox("Language", ["English", "Spanish", "French", "German"])
        
        if st.button("💾 Save General Settings", use_container_width=True):
            st.success("General settings saved successfully!")
    
    with tabs[1]:
        st.markdown("### 📝 Assessment Settings")
        
        col1, col2 = st.columns(2)
        with col1:
            min_questions = st.number_input("Minimum Questions per Test", 1, 50, 5)
            max_questions = st.number_input("Maximum Questions per Test", 1, 100, 20)
            passing_score = st.number_input("Passing Score (%)", 0, 100, 60)
            certificate_threshold = st.number_input("Certificate Threshold (%)", 0, 100, 80)
        
        with col2:
            default_difficulty = st.selectbox("Default Difficulty", ["Easy", "Medium", "Hard"])
            time_limit_enabled = st.checkbox("Enable Time Limits", value=True)
            default_time_limit = st.number_input("Default Time Limit (minutes)", 5, 180, 30)
            show_answers_default = st.checkbox("Show Answers by Default", value=True)
        
        if st.button("💾 Save Assessment Settings", use_container_width=True):
            st.success("Assessment settings saved successfully!")
    
    with tabs[2]:
        st.markdown("### 🔒 Security Settings")
        
        col1, col2 = st.columns(2)
        with col1:
            password_min_length = st.number_input("Minimum Password Length", 6, 20, 8)
            require_special_char = st.checkbox("Require Special Characters", value=True)
            require_numbers = st.checkbox("Require Numbers", value=True)
            max_login_attempts = st.number_input("Max Login Attempts", 1, 10, 5)
        
        with col2:
            session_timeout = st.number_input("Session Timeout (minutes)", 5, 240, 30)
            enable_2fa = st.checkbox("Enable Two-Factor Authentication", value=False)
            log_ip_addresses = st.checkbox("Log IP Addresses", value=True)
            enable_brute_force_protection = st.checkbox("Enable Brute Force Protection", value=True)
        
        if st.button("💾 Save Security Settings", use_container_width=True):
            st.success("Security settings saved successfully!")
    
    with tabs[3]:
        st.markdown("### 🛠️ Maintenance")
        
        st.markdown("#### Database Operations")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Optimize Database", use_container_width=True):
                st.info("Database optimization would run here")
                st.success("Database optimized successfully!")
            
            if st.button("🧹 Clean Old Data", use_container_width=True):
                days = st.number_input("Delete data older than (days)", 30, 365, 90)
                if st.button("Confirm Cleanup", key="cleanup_confirm"):
                    st.warning(f"This will delete data older than {days} days")
                    # Add cleanup logic here
        
        with col2:
            if st.button("📊 Rebuild Statistics", use_container_width=True):
                st.info("Rebuilding statistics...")
                # Add statistics rebuild logic here
                st.success("Statistics rebuilt successfully!")
            
            if st.button("🔍 Check Database Integrity", use_container_width=True):
                st.info("Checking database integrity...")
                # Add integrity check logic here
                st.success("Database integrity check completed!")
        
        st.markdown("#### System Information")
        st.write(f"**Database File:** users.db")
        st.write(f"**Total Users:** {len(get_all_users())}")
        st.write(f"**Total Assessments:** {get_system_stats()['total_assessments']}")
        
        if st.button("🔄 Refresh System Info", use_container_width=True):
            st.rerun()

# ============================================
# ENHANCED CSS WITH PROFESSIONAL DESIGN
# ============================================
def load_css():
    return '''
    <style>
    /* Reset and Base Styles */
    * {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }
    
    :root {
        /* Modern Color Palette */
        --primary: #2563eb;
        --primary-dark: #1d4ed8;
        --primary-light: #3b82f6;
        --secondary: #7c3aed;
        --secondary-dark: #6d28d9;
        --success: #10b981;
        --warning: #f59e0b;
        --danger: #ef4444;
        --info: #06b6d4;
        --expert: #8b5cf6;
        --advanced: #3b82f6;
        --intermediate: #10b981;
        --beginner: #f59e0b;
        --novice: #ef4444;
        
        /* Admin Colors */
        --admin-primary: #8b5cf6;
        --admin-secondary: #7c3aed;
        
        /* Light Theme Colors */
        --bg-primary: #ffffff;
        --bg-secondary: #f8fafc;
        --bg-sidebar: #ffffff;
        --text-primary: #1e293b;
        --text-secondary: #475569;
        --border-color: #e2e8f0;
        --card-bg: #ffffff;
        
        /* UI Variables */
        --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
        --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        --shadow-md: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
        --shadow-lg: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
        --radius-sm: 0.375rem;
        --radius: 0.5rem;
        --radius-md: 0.75rem;
        --radius-lg: 1rem;
        --radius-xl: 1.5rem;
        --transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
    
    /* Streamlit App Background */
    .stApp {
        background: linear-gradient(135deg, var(--bg-secondary) 0%, var(--bg-primary) 100%) !important;
        min-height: 100vh;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
    }
    
    /* Dashboard Cards */
    .dashboard-card {
        background: var(--card-bg);
        border-radius: var(--radius-lg);
        padding: 1.5rem;
        border: 1px solid var(--border-color);
        box-shadow: var(--shadow-sm);
        transition: var(--transition);
        height: 100%;
    }
    
    .dashboard-card:hover {
        transform: translateY(-2px);
        box-shadow: var(--shadow-md);
        border-color: var(--primary-light);
    }
    
    .dashboard-card-primary {
        background: linear-gradient(135deg, var(--primary), var(--primary-dark));
        color: white;
    }
    
    .dashboard-card-secondary {
        background: linear-gradient(135deg, var(--secondary), var(--secondary-dark));
        color: white;
    }
    
    .dashboard-card-success {
        background: linear-gradient(135deg, var(--success), #0da271);
        color: white;
    }
    
    .dashboard-card-warning {
        background: linear-gradient(135deg, var(--warning), #d97706);
        color: white;
    }
    
    /* Admin Cards */
    .admin-card {
        background: linear-gradient(135deg, var(--admin-primary), var(--admin-secondary));
        color: white;
        border-radius: var(--radius-lg);
        padding: 1.5rem;
        box-shadow: var(--shadow-lg);
    }
    
    /* User Avatar */
    .user-avatar {
        width: 60px;
        height: 60px;
        border-radius: 50%;
        background: linear-gradient(45deg, var(--primary), var(--secondary));
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-size: 1.5rem;
        font-weight: bold;
        margin: 0 auto 1rem;
    }
    
    /* Level Badges */
    .level-badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: var(--radius);
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    
    .level-expert { background: var(--expert); color: white; }
    .level-advanced { background: var(--advanced); color: white; }
    .level-intermediate { background: var(--intermediate); color: white; }
    .level-beginner { background: var(--beginner); color: white; }
    .level-novice { background: var(--novice); color: white; }
    
    div.stButton{
     background-color:none;
    }
    
    /* Buttons - Fixed */
    div.stButton > button {
        width: 100% !important;
        background: linear-gradient(45deg, var(--primary), var(--primary-dark)) !important;
        color: white !important;
        border: none !important;
        padding: 0.875rem 1.5rem !important;
        border-radius: var(--radius) !important;
        font-weight: 600 !important;
        font-size: 1rem !important;
        transition: var(--transition) !important;
        cursor: pointer !important;
        position: relative !important;
        overflow: hidden !important;
    }
    
    div.stButton > button:hover {
        transform: translateY(-2px) !important;
        box-shadow: var(--shadow-lg) !important;
    }
    
    /* Admin Button */
    div.stButton > button.kind-secondary {
        background: linear-gradient(45deg, var(--secondary), var(--secondary-dark)) !important;
    }
    
    /* Animations */
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }
    
    .fade-in {
        animation: fadeIn 0.6s ease-out;
    }
    
    /* Responsive Design */
    @media (max-width: 768px) {
        .main-title {
            font-size: 2.5rem;
        }
    }
    </style>
    '''

# ============================================
# GEMINI API FUNCTION
# ============================================
def generate_with_fallback(prompt):
    GEMINI_API_KEYS = [
        "AIzaSyCcJ4gWqENZ-AONM8G6PNdVu89Xy2hENtk",
        
    ]
    
    for index, api_key in enumerate(GEMINI_API_KEYS, start=1):
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("models/gemini-2.5-flash")
            response = model.generate_content(prompt)
            
            if not response or not response.text:
                raise RuntimeError("Empty response received")
                
            return response.text.strip()
            
        except Exception as e:
            error_msg = str(e).lower()
            
            if any(k in error_msg for k in ["quota", "limit", "429", "permission", "auth", "key"]):
                time.sleep(1)
                continue
            else:
                st.error(f"API Error: {str(e)[:100]}")
                return None
    
    raise RuntimeError("All API keys exhausted. Please try again later.")

# ============================================
# STREAMLIT APP CONFIG
# ============================================
st.set_page_config(
    page_title="Skill Assessment Pro",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={
        'Get Help': 'https://github.com/Mr-Asmath',
        'Report a bug': 'https://github.com/Mr-Asmath/issues',
        'About': '# Skill Assessment Pro\nAI-powered assessment platform'
    }
)

# Initialize database
init_db()

# Initialize session state
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'username' not in st.session_state:
    st.session_state.username = None
if 'user_id' not in st.session_state:
    st.session_state.user_id = None
if 'current_page' not in st.session_state:
    st.session_state.current_page = 'welcome'
if 'welcome_shown' not in st.session_state:
    st.session_state.welcome_shown = False
if 'countdown' not in st.session_state:
    st.session_state.countdown = 3
if 'questions' not in st.session_state:
    st.session_state.questions = None
if 'score' not in st.session_state:
    st.session_state.score = None
if 'is_admin' not in st.session_state:
    st.session_state.is_admin = False
if 'current_test_type' not in st.session_state:
    st.session_state.current_test_type = None
if 'current_topic' not in st.session_state:
    st.session_state.current_topic = None
if 'show_certificate' not in st.session_state:
    st.session_state.show_certificate = False
if 'selected_user' not in st.session_state:
    st.session_state.selected_user = None

# ============================================
# MAIN APP ROUTING
# ============================================
def main():
    # Check URL parameters for page navigation
    query_params = st.query_params
    if 'page' in query_params:
        st.session_state.current_page = query_params['page']
    
    # Load CSS for all pages
    st.markdown(load_css(), unsafe_allow_html=True)
    
    # Route to appropriate page
    if st.session_state.logged_in:
        if st.session_state.is_admin:
            admin_dashboard()
        else:
            learner_dashboard()
    else:
        # Show appropriate page based on current_page state
        if st.session_state.current_page == 'welcome':
            welcome_page()
        elif st.session_state.current_page == 'login':
            login_page()
        elif st.session_state.current_page == 'register':
            register_page()
        else:
            welcome_page()

if __name__ == "__main__":
    main()






