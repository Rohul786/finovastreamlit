# Finova — Streamlit Edition

This is an end-to-end Streamlit rebuild of the supplied Finova React/TypeScript app. It preserves the Finova dark visual language, authentication, user-scoped workspace, dashboard, finance, transactions, goals, risk assessment, AI planner, SIP simulator, What-If analysis, analytics, stock market, AI co-pilot, KYC flow and settings.

## Run

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

## Optional environment

Copy `.env.example` to `.env` and configure `GEMINI_API_KEY` for AI features. Configure either `RESEND_API_KEY` or SMTP variables for real email OTP delivery.

## Notes

- Data is stored in `finova.db` using SQLite, giving each registered email an isolated workspace.
- The stock/market data is the supplied Finova demo dataset and is not live market data.
- Browser camera/face-liveness APIs from the React implementation are represented by the Streamlit KYC upload/review flow. For production KYC, connect a dedicated identity provider.
- The `chatgpt-4o` selector is retained for UI compatibility; if an OpenAI provider is added later, it can be wired into `ai_generate`.
- This application is for educational/personal planning and is not financial advice.
