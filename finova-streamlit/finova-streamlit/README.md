# Finova — Streamlit Edition

A Streamlit rebuild of the supplied Finova Intelligent Wealth & Stock Market OS.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

Optional environment variables:
- `GEMINI_API_KEY` for AI responses
- `RESEND_API_KEY` / SMTP variables for live email OTP
- `EMAIL_FROM` for the sender address

The app stores demo accounts and user workspaces locally in `finova_data.json`.
