# YOUTUBE AI LONG landing

This folder contains the static product landing page for the repository.

Open `landing/index.html` directly in a browser, or publish the whole `landing/`
folder to any static hosting service. The page links to the local FastAPI docs at
`http://localhost:8000/docs`, so that link works after the backend is running.

GitHub Pages deployment is configured through
`.github/workflows/deploy-landing.yml`. After the workflow runs successfully on
`main`, the expected public URL is:
`https://milliardwb-sys.github.io/YOUTUBE-AI-LONG/`.

The hero visual is generated from a product dashboard concept and stored as
`landing/assets/hero-dashboard.png`.
