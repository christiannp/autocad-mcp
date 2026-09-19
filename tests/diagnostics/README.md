# Diagnostics

One-off scripts written while working out how AutoCAD 2025 actually behaves.
They are kept because each one answers a question that is expensive to
re-discover; the answers are summarised in the "Design notes" section of
README.md.

| script | question it answered |
|---|---|
| `diag_lisp.py` | does inline LISP run through SendCommand, and can it write files? |
| `diag2.py` / `diag3.py` | is AutoLISP evaluating at all, and how long may a SendCommand be? |
| `diag4.py` | where is LISP allowed to write, and can results come back via an XRecord? |
| `diag5.py` | can we `(load)` from AutoCAD's temp folder, and does streaming source work? |
| `diag6.py` / `diag7.py` | which part of the support library parks AutoCAD? |
| `diag8.py` | which SendCommand terminator avoids a stray Enter? |
| `diag_hatch_trim.py` | how must a hatch boundary be marshalled, and what are TRIM's real prompts? |
| `diag_formats.py` | which AcSaveAsType numbers work, and what version does each produce? |
| `diag_save_plot.py` | which plotting call actually writes a PDF? |
| `diag_break.py` | does the BREAK command accept scripted points? (it does not, reliably) |
| `quick_overkill.py` | OVERKILL option keywords |
| `mark_readonly.py` | a one-time patch that tagged the inspection-only tools |
