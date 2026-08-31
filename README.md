# lukeofwales.github.io

My personal projects hub / portfolio home page, live at
**https://lukeofwales.github.io/**.

It's a self-updating static page: a scheduled GitHub Action runs `build.py`,
which queries the GitHub API for my public repositories that have a **live
GitHub Pages site**, gathers metadata for each (description, languages, topics,
stars, licence, last updated), and renders `index.html`. Newly published Pages
sites appear automatically on the next daily build — no manual edits.

## How it works

- `build.py` — discovers Pages-enabled public repos and renders the page into
  `_site/`.
- `style.css` — the dark, glassy card-grid theme.
- `.github/workflows/deploy.yml` — runs the build daily (and on push) and
  deploys `_site/` to GitHub Pages.

## Run locally

```bash
python build.py            # writes _site/index.html (uses your `gh` token)
cd _site && python3 -m http.server 8220   # preview at http://localhost:8220
```

## Adding / removing projects

There's nothing to edit here — publish a GitHub Pages site on any public repo
you own and it shows up automatically. Unpublish it and it drops off. (An
opt-out mechanism can be added later if needed.)
