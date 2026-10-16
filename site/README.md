# Marketing site

Static HTML/CSS, no build step. Preview with `python3 -m http.server -d site`.

## Deploying to GitHub Pages

Set Settings → Pages → Source to "GitHub Actions", then add
`.github/workflows/pages.yml` (an automated agent can't write workflow files):

```yaml
name: Pages
on:
  push:
    branches: [main]
    paths: ["site/**"]
  workflow_dispatch:
permissions:
  contents: read
  pages: write
  id-token: write
concurrency:
  group: pages
  cancel-in-progress: false
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site
      - id: deployment
        uses: actions/deploy-pages@v4
```
