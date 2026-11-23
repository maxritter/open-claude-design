# Finish in the canonical model

Use this workflow when refining an existing product that already has a canonical Design canvas (such as an App Model or Website Model). A separate exploration stays separate only when the user asks for it.

1. Identify the canonical artboard and `project/canvas.json` before creating a focused draft. Record which temporary files this task adds.
2. Once a focused preview is accepted, merge the actual components, states, copy, and interactions back into the canonical artboard. Do not leave two competing versions as equal authorities.
3. Re-read the current file hashes (`open-claude-artifacts files <artifact> --json`) before merging. Preserve unrelated routes, settings, other people's edits, and open comments.
4. Render the merged canonical artboard locally (`open-claude-artifacts render <artifact> --path project/<Artboard>.dc.html`) across light/dark themes and desktop/phone widths, and inspect every screenshot.
5. Remove temporary draft artboards only after the merged canonical artboard is verified and when removal is authorized (`push --remove project/<Draft>.dc.html=<sha256> --allow-write --allow-destructive`, updating `project/canvas.json`). If removal is not authorized, label the draft clearly as superseded and report it.
6. Report the canonical artifact URL, verified version, rendered checks inspected, and any retained drafts.
