# Marketing site

Static HTML/CSS, no build step. Preview with `python3 -m http.server -d site`.

## Deploying to GitHub Pages

`.github/workflows/pages.yml` publishes `site/` on every push to `main` that
touches it (or by hand from the Actions tab). One-time setup: Settings → Pages →
Source → "GitHub Actions".
