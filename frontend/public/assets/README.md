# Static image assets

Drop people photos and research project images here, then point the `photo:` /
`image:` fields in `backend/data/inputs/people.yaml` and `research.yaml` at
`/assets/<filename>` (e.g. `/assets/sid.png`). Files in `public/` are served at
the site root, so `/assets/sid.png` resolves to `frontend/public/assets/sid.png`
in dev and in the built `dist/`.

Until real images are supplied the site degrades gracefully: people without a
resolvable photo show a monogram tile, and research tiles drop the image block.
