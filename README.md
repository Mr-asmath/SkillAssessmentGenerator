# Skill Assessment Generator

AI-powered Streamlit app for generating skill assessment questions, tracking learner scores, issuing certificates, and viewing admin analytics.

## Features

- Learner registration and login
- AI-generated MCQ assessments for technical, soft skill, domain, and language topics
- Score history, levels, certificates, and leaderboards
- Admin dashboard for users, assessments, certificates, reports, and settings

## Run Locally

```bash
cd QAUpload
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Configure Gemini

Create `QAUpload/.streamlit/secrets.toml` from the example file:

```toml
GEMINI_API_KEY = "your-gemini-api-key"
```

You can also use environment variables:

```bash
set GEMINI_API_KEY=your-gemini-api-key
streamlit run QAUpload/app.py
```

For multiple fallback keys, set `GEMINI_API_KEYS` as a comma-separated list.

## Deploy On Streamlit Community Cloud

1. Set the app entrypoint to `QAUpload/app.py`.
2. Add `GEMINI_API_KEY` in Streamlit app secrets.
3. Keep local files such as `users.db` and `.streamlit/secrets.toml` out of Git.

## Free AI API Options

Good free or free-tier options for this project:

- Google Gemini API: easiest fit because the app already uses `google-generativeai`.
- Groq API: fast hosted inference with a free developer tier, but needs code changes.
- OpenRouter: offers some free models, but availability can change.
- Hugging Face Inference Providers: useful for open models, with free monthly credits depending on account and provider.

For the current codebase, Gemini is the simplest choice.
