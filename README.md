# LinkedIn Scrapper — Frontend

Streamlit dashboard for author bylines (filter by user + date).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
copy .env.example .env
```

## Run

Start the **backend** first (port 8000), then:

```bash
python -m streamlit run app.py
```

UI: http://localhost:8501

## Backend

Runs separately. See **linkedIn-Scrapper-backend**.
