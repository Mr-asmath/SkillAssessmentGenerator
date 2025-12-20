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
            is_active INTEGER DEFAULT 1
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
            INSERT OR IGNORE INTO users (username, email, password_hash) 
            VALUES (?, ?, ?)
        ''', ('admin', 'admin@skillassessment.com', admin_password_hash))
    except:
        pass
    
    conn.commit()
    conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_user(username, email, password):
    try:
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        password_hash = hash_password(password)
        c.execute('INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)',
                 (username, email, password_hash))
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
    
    c.execute('SELECT id, username FROM users WHERE username=? AND password_hash=?',
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
        
        /* Light Theme Colors */
        --bg-primary: #ffffff;
        --bg-secondary: #f8fafc;
        --bg-sidebar: #ffffff;
        --text-primary: #1e293b;
        --text-secondary: #475569;
        --border-color: #e2e8f0;
        --card-bg: #ffffff;
        
        /* Admin Colors */
        --admin-primary: #8b5cf6;
        --admin-secondary: #7c3aed;
        
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
    
    /* Test Generator Card */
    .test-generator-card {
        background: linear-gradient(135deg, #8b5cf6, #7c3aed);
        color: white;
        border-radius: var(--radius-lg);
        padding: 2rem;
        margin-bottom: 2rem;
        box-shadow: var(--shadow-lg);
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
    
    /* Certificate Card */
    .certificate-card {
        background: linear-gradient(135deg, #fef3c7, #fde68a);
        border: 2px solid #f59e0b;
        border-radius: var(--radius-lg);
        padding: 1.5rem;
        margin: 1rem 0;
        position: relative;
        overflow: hidden;
    }
    
    .certificate-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: url("data:image/svg+xml,%3Csvg width='100' height='100' viewBox='0 0 100 100' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M11 18c3.866 0 7-3.134 7-7s-3.134-7-7-7-7 3.134-7 7 3.134 7 7 7zm48 25c3.866 0 7-3.134 7-7s-3.134-7-7-7-7 3.134-7 7 3.134 7 7 7zm-43-7c1.657 0 3-1.343 3-3s-1.343-3-3-3-3 1.343-3 3 1.343 3 3 3zm63 31c1.657 0 3-1.343 3-3s-1.343-3-3-3-3 1.343-3 3 1.343 3 3 3zM34 90c1.657 0 3-1.343 3-3s-1.343-3-3-3-3 1.343-3 3 1.343 3 3 3zm56-76c1.657 0 3-1.343 3-3s-1.343-3-3-3-3 1.343-3 3 1.343 3 3 3zM12 86c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm28-65c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm23-11c2.76 0 5-2.24 5-5s-2.24-5-5-5-5 2.24-5 5 2.24 5 5 5zm-6 60c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm29 22c2.76 0 5-2.24 5-5s-2.24-5-5-5-5 2.24-5 5 2.24 5 5 5zM32 63c2.76 0 5-2.24 5-5s-2.24-5-5-5-5 2.24-5 5 2.24 5 5 5zm57-13c2.76 0 5-2.24 5-5s-2.24-5-5-5-5 2.24-5 5 2.24 5 5 5zm-9-21c1.105 0 2-.895 2-2s-.895-2-2-2-2 .895-2 2 .895 2 2 2zM60 91c1.105 0 2-.895 2-2s-.895-2-2-2-2 .895-2 2 .895 2 2 2zM35 41c1.105 0 2-.895 2-2s-.895-2-2-2-2 .895-2 2 .895 2 2 2zM12 60c1.105 0 2-.895 2-2s-.895-2-2-2-2 .895-2 2 .895 2 2 2z' fill='%23fbbf24' fill-opacity='0.1' fill-rule='evenodd'/%3E%3C/svg%3E");
        opacity: 0.3;
    }
    
    /* Field Test Container */
    .field-test-container {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
        gap: 1.5rem;
        margin: 2rem 0;
    }
    
    .field-test-card {
        background: var(--card-bg);
        border-radius: var(--radius-lg);
        padding: 1.5rem;
        border: 1px solid var(--border-color);
        box-shadow: var(--shadow-sm);
        transition: var(--transition);
        cursor: pointer;
    }
    
    .field-test-card:hover {
        transform: translateY(-4px);
        box-shadow: var(--shadow-lg);
        border-color: var(--primary);
    }
    
    .field-test-icon {
        font-size: 2.5rem;
        margin-bottom: 1rem;
    }
    
    /* Leaderboard Styles */
    .leaderboard-card {
        background: linear-gradient(135deg, #1e293b, #334155);
        color: white;
        border-radius: var(--radius-lg);
        padding: 1.5rem;
        margin: 1rem 0;
    }
    
    .rank-1 { background: linear-gradient(135deg, #fbbf24, #d97706); }
    .rank-2 { background: linear-gradient(135deg, #94a3b8, #64748b); }
    .rank-3 { background: linear-gradient(135deg, #f59e0b, #b45309); }
    
    .rank-badge {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: bold;
        font-size: 1.25rem;
        margin-right: 1rem;
    }
    
    /* Progress Ring */
    .progress-ring {
        width: 100px;
        height: 100px;
        margin: 0 auto;
    }
    
    /* Test History Table */
    .test-history-table {
        width: 100%;
        border-collapse: collapse;
        margin: 1rem 0;
    }
    
    .test-history-table th {
        background: var(--bg-secondary);
        padding: 0.75rem;
        text-align: left;
        font-weight: 600;
        color: var(--text-secondary);
        border-bottom: 2px solid var(--border-color);
    }
    
    .test-history-table td {
        padding: 0.75rem;
        border-bottom: 1px solid var(--border-color);
    }
    
    .test-history-table tr:hover {
        background: var(--bg-secondary);
    }
    
    /* Welcome Page */
    .welcome-container {
        min-height: 100vh;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%);
        padding: 3rem 2rem;
        position: relative;
        overflow: hidden;
    }
    
    .welcome-container::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='0.05'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");
    }
    
    .logo-title {
        text-align: center;
        position: relative;
        z-index: 1;
        animation: float 6s ease-in-out infinite;
    }
    
    .logo-icon {
        font-size: 5rem;
        margin-bottom: 1.5rem;
        background: linear-gradient(45deg, #ffffff, #f1f5f9);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        filter: drop-shadow(0 4px 6px rgba(0, 0, 0, 0.1));
    }
    
    .main-title {
        font-size: 3.5rem;
        font-weight: 800;
        background: linear-gradient(45deg, #ffffff, #f1f5f9);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 1rem;
        line-height: 1.2;
        letter-spacing: -0.025em;
    }
    
    .tagline {
        font-size: 1.25rem;
        color: rgba(255, 255, 255, 0.9);
        margin-bottom: 2rem;
        max-width: 600px;
        line-height: 1.6;
        font-weight: 300;
    }
    
    .countdown {
        font-size: 1rem;
        color: rgba(255, 255, 255, 0.8);
        margin-top: 1rem;
        background: rgba(255, 255, 255, 0.1);
        padding: 0.5rem 1rem;
        border-radius: var(--radius);
        backdrop-filter: blur(10px);
    }
    
    .action-btn {
        background: linear-gradient(45deg, #ffffff, #f1f5f9);
        color: var(--primary);
        border: none;
        padding: 1rem 2.5rem;
        font-size: 1.125rem;
        font-weight: 600;
        border-radius: var(--radius-lg);
        cursor: pointer;
        transition: var(--transition);
        text-decoration: none;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0.5rem;
        box-shadow: var(--shadow-lg);
        position: relative;
        overflow: hidden;
        z-index: 1;
        margin-top: 1rem;
    }
    
    .action-btn::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: linear-gradient(45deg, #f1f5f9, #ffffff);
        opacity: 0;
        transition: var(--transition);
        z-index: -1;
    }
    
    .action-btn:hover {
        transform: translateY(-2px);
        box-shadow: var(--shadow-xl);
        color: var(--primary-dark);
    }
    
    .action-btn:hover::before {
        opacity: 1;
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
    
    /* Animations */
    @keyframes float {
        0%, 100% { transform: translateY(0px); }
        50% { transform: translateY(-10px); }
    }
    
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
        
        .field-test-container {
            grid-template-columns: 1fr;
        }
    }
    </style>
    '''

# ============================================
# GEMINI API FUNCTION
# ============================================
def generate_with_fallback(prompt):
    GEMINI_API_KEYS = [
        "AIzaSyB55YBQ6x97ah4rZgs8F-6UhZtCS90xK6k",
        "AIzaSyDway_4FY72fOG9Fz_Y56LjOvLg6wIdD7k"
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

# ============================================
# PAGE FUNCTIONS
# ============================================
def welcome_page():
    st.markdown(load_css(), unsafe_allow_html=True)
    
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
    
    st.markdown(f"""
    <div class="welcome-container">
        <div class="logo-title">
            <div class="logo-icon">🎯</div>
            <h1 class="main-title">Skill Assessment Pro</h1>
            <p class="tagline">
                Transform your learning journey with AI-powered assessments. 
                Generate personalized tests, track your progress, and master any topic.
            </p>
            <div class="countdown">
                Redirecting to login in {st.session_state.countdown} seconds...
            </div>
            <a href="?page=login" class="action-btn">
                🚀 Get Started Now
            </a>
        </div>
    </div>
    """, unsafe_allow_html=True)

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
    st.markdown(load_css(), unsafe_allow_html=True)
    
    # Sidebar with menu buttons instead of radio
    with st.sidebar:
        st.markdown(f"""
        <div class="user-profile">
            <div class="user-avatar">
                {st.session_state.username[0].upper() if st.session_state.username else 'U'}
            </div>
            <h3 style="color: var(--text-primary);">{st.session_state.username}</h3>
            <p style="color: var(--text-secondary); font-size: 0.875rem;">Skill Assessment Platform</p>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # Navigation Menu
        st.markdown("### 📍 Navigation")
        
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
                st.rerun()
        
        st.markdown("---")
        
        if st.button("🚪 Logout", use_container_width=True, type="primary"):
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
            🎯 Welcome to Skill Assessment Pro
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
        <h2 style="font-size: 1.5rem; font-weight: 700; margin-bottom: 1rem; color: white;">🎯 Quick Test Generator</h2>
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
    st.markdown("### 🎓 Explore Field Tests")
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
    st.markdown("### 📋 Recent Assessments")
    
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
        st.markdown("### 📝 Create New Assessment")
        
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
    st.markdown("### 📋 Existing Skill Assessments")
    
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
        st.markdown("### 📋 Assessment History")
        
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
            st.markdown("### 📊 Performance Trend")
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
            st.markdown("### 🎯 Your Position")
            
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
    st.markdown("### 🎓 Top Performing Topics")
    
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
            # admin_dashboard() would go here - kept as placeholder
            st.error("Admin dashboard not implemented in this version")
            if st.button("Go to Learner Dashboard"):
                st.session_state.is_admin = False
                st.session_state.current_page = 'dashboard'
                st.rerun()
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
