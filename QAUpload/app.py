import streamlit as st
import google.generativeai as genai
import time
import random

# Hide Streamlit menu and footer
hide_st_style = """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    </style>
"""

st.markdown(hide_st_style, unsafe_allow_html=True)

# --- Configure Gemini API directly ---
genai.configure(api_key="AIzaSyBoiCnFfKwTfQLNhPJt6DUQLXcFw3OoaY0")

# --- Streamlit App Setup with Enhanced UI ---
st.set_page_config(
    page_title="Skill Assessment Generator", 
    page_icon="https://orange-space-palm-tree-r4xwj7wjj6rc5rr-8504.app.github.dev/media/3ed033557b827c91afc1f11cac78eb2cdc2b963c214d550ab232c6a5.jpg",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<head>
      <title>Skill Assessment Generator</title>
       <link rel="icon" type="image/png" href="https://orange-space-palm-tree-r4xwj7wjj6rc5rr-8504.app.github.dev/media/3ed033557b827c91afc1f11cac78eb2cdc2b963c214d550ab232c6a5.jpg">
</head>
<style>
    .main-header {
        font-size: 3rem;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
    }
    .sub-header {
        font-size: 1.5rem;
        color: #2e86ab;
        margin-top: 2rem;
    }
    .success-box {
        padding: 1rem;
        border-radius: 10px;
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        color: #155724;
    }
    .info-box {
        padding: 1rem;
        border-radius: 10px;
        background-color: #d1ecf1;
        border: 1px solid #bee5eb;
        color: #0c5460;
    }
    .question-card {
        padding: 1.5rem;
        border-radius: 10px;
        background-color: #f8f9fa;
        border-left: 5px solid #1f77b4;
        margin-bottom: 1rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .score-display {
        font-size: 2rem;
        font-weight: bold;
        text-align: center;
        padding: 2rem;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 15px;
        margin: 1rem 0;
    }
    .stProgress > div > div > div > div {
        background-color: #1f77b4;
    }
</style>
""", unsafe_allow_html=True)

# --- Sidebar ---
with st.sidebar:
    st.title("⚙️ Settings")
    st.markdown("---")
    st.subheader("About")
    st.info("This app uses AI model to generate customized assessment tests based on your topic.")
    
    st.subheader("Instructions")
    st.markdown("""
    1. Enter a topic or paragraph
    2. Select number of questions
    3. Click 'Generate Questions'
    4. Take the test
    5. Submit to see your score
    """)
    
    if "questions" in st.session_state:
        st.markdown("---")
        st.subheader("Test Info")
        st.metric("Questions Generated", len(st.session_state.questions.split("Q")) - 1)
        if "score" in st.session_state:
            st.metric("Your Score", f"{st.session_state.score}%")

# --- Main Content ---
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    st.markdown('<div class="main-header">🧠 Skill Assessment Generator</div>', unsafe_allow_html=True)
    st.markdown("### Create AI-generated assessment tests easily! 🚀")

# --- Step 1: User Inputs with Enhanced UI ---
st.markdown("---")
st.markdown('<div class="sub-header">📝 Step 1: Create Your Assessment</div>', unsafe_allow_html=True)

input_col1, input_col2 = st.columns([3, 1])

with input_col1:
    topic = st.text_area(
        "**Enter a topic or paragraph:**",
        placeholder="e.g., Machine Learning, World War II, Python Programming...",
        height=100,
        help="Provide a detailed topic for better question generation"
    )

with input_col2:
    num_q = st.number_input(
        "**Number of questions:**",
        min_value=1,
        max_value=20,
        value=5,
        help="Choose between 1-20 questions"
    )
    
    difficulty = st.selectbox(
        "**Difficulty level:**",
        ["Easy", "Medium", "Hard"],
        help="Select the difficulty of questions"
    )

generate_col1, generate_col2, generate_col3 = st.columns([1, 2, 1])
with generate_col2:
    generate_btn = st.button(
        "🎯 Generate Questions", 
        use_container_width=True,
        type="primary"
    )

# --- Step 2: Generate Questions from Gemini with Loading Animation ---
if generate_btn and topic:
    try:
        with st.spinner(""):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Simulate progress for better UX
            for i in range(100):
                progress_bar.progress(i + 1)
                status_text.text(f"✨ Generating questions... {i+1}%")
                time.sleep(0.02)
            
            status_text.text("🔍 Finalizing your assessment...")
            
            model = genai.GenerativeModel("models/gemini-2.5-flash")
            prompt = f"""
            Create {num_q} multiple choice questions about the topic "{topic}" at {difficulty.lower()} difficulty level.
            Follow this format strictly:

            Q1. Question text
            a) Option A
            b) Option B
            c) Option C
            d) Option D
            Answer: a

            Continue this pattern for all {num_q} questions.
            Make sure the questions are relevant and the answer choices are plausible.
            """

            response = model.generate_content(prompt)
            q_text = response.text.strip()

            st.session_state.questions = q_text
            st.session_state.generated_topic = topic
            st.session_state.difficulty = difficulty
            
            progress_bar.empty()
            status_text.empty()
            
            # Success message with animation
            success_placeholder = st.empty()
            with success_placeholder.container():
                st.markdown('<div class="success-box">✅ Questions generated successfully!</div>', unsafe_allow_html=True)
                time.sleep(2)
            success_placeholder.empty()
            
            # Auto-scroll to questions
            st.markdown("<div id='questions-section'></div>", unsafe_allow_html=True)

    except Exception as e:
        st.error(f"❌ Error calling Gemini: {e}")

# --- Step 3: Display Questions and Take Answers with Enhanced UI ---
if "questions" in st.session_state:
    st.markdown("---")
    
    # Header with topic info
    header_col1, header_col2, header_col3 = st.columns([2, 1, 1])
    with header_col1:
        st.markdown(f'<div class="sub-header">📝 Assessment: {st.session_state.generated_topic}</div>', unsafe_allow_html=True)
    with header_col2:
        st.metric("Difficulty", st.session_state.difficulty)
    with header_col3:
        st.metric("Total Questions", len(st.session_state.questions.split("Q")) - 1)
    
    # Questions display
    questions_block = st.session_state.questions.split("Q")
    user_answers = {}
    
    with st.form("assessment_form"):
        for i, q in enumerate(questions_block):
            if q.strip():
                lines = q.strip().split("\n")
                q_title = "Q" + lines[0]
                options = [l for l in lines[1:] if l.startswith(("a", "b", "c", "d"))]
                correct = [l for l in lines if l.lower().startswith("answer")]
                
                with st.container():
                    st.markdown(f'<div class="question-card">', unsafe_allow_html=True)
                    st.subheader(q_title)
                    choice = st.radio(
                        "Choose your answer:",
                        options,
                        key=f"q_{i}",
                        index=None
                    )
                    user_answers[q_title] = {
                        "choice": choice, 
                        "correct": correct[0] if correct else None,
                        "options": options
                    }
                    st.markdown('</div>', unsafe_allow_html=True)
        
        # Submit button
        submit_col1, submit_col2, submit_col3 = st.columns([1, 2, 1])
        with submit_col2:
            submitted = st.form_submit_button(
                "📤 Submit Assessment", 
                use_container_width=True,
                type="primary"
            )
    
    # Handle submission
    if submitted:
        correct_count = 0
        total = len(user_answers)
        
        # Calculate score with progress animation
        score_placeholder = st.empty()
        with score_placeholder.container():
            st.markdown('<div class="score-display">Calculating your score...</div>', unsafe_allow_html=True)
        
        for q, data in user_answers.items():
            if data["correct"] and data["choice"] and data["choice"][0].lower() in data["correct"].lower():
                correct_count += 1
        
        score_percentage = (correct_count / total) * 100 if total > 0 else 0
        st.session_state.score = int(score_percentage)
        
        # Display final score with animation
        score_placeholder.empty()
        time.sleep(0.5)
        
        # Color code based on performance
        if score_percentage >= 80:
            score_color = "🟢"
            message = "Excellent! 🎉"
        elif score_percentage >= 60:
            score_color = "🟡"
            message = "Good job! 👍"
        else:
            score_color = "🔴"
            message = "Keep practicing! 💪"
        
        st.markdown(f"""
        <div class="score-display">
            {score_color} Your Score: {correct_count}/{total} ({int(score_percentage)}%)<br>
            <small>{message}</small>
        </div>
        """, unsafe_allow_html=True)
        
        # Detailed results
        with st.expander("📊 View Detailed Results", expanded=True):
            for q, data in user_answers.items():
                user_choice = data["choice"] or "Not answered"
                correct_answer = data["correct"] or "Not specified"
                is_correct = data["choice"] and data["correct"] and data["choice"][0].lower() in data["correct"].lower()
                
                status = "✅ Correct" if is_correct else "❌ Incorrect"
                st.write(f"**{q}** - {status}")
                st.write(f"Your answer: {user_choice}")
                st.write(f"Correct answer: {correct_answer}")
                st.write("---")
        
        # Download button
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.download_button(
                "💾 Download Questions", 
                st.session_state.questions, 
                file_name=f"assessment_{st.session_state.generated_topic.replace(' ', '_')}.txt",
                use_container_width=True,
                mime="text/plain"
            )

# --- Footer ---
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: #666;'>"
    "Built with ❤️ using  AI Model"
    "</div>", 
    unsafe_allow_html=True

)
