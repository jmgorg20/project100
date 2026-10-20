# Face finder hang fix: evidence

The real Windows run hung for good at "Finding your face so graphics keep off it". Here, on Linux,
with the user's export:

| file | what it shows |
|---|---|
| `face-finder-ok.log` | the face finder in its own process: self-test 0.5 s, face found in 75 of 104 samples in 7.9 s |
| `face-finder-hang.log` | made to hang: stopped at the real 60 s limit ("no answer within 60 s - stopped"), the edit goes on |
| `face-finder-crash.log` | made to crash: exit code 3 reported in 0.3 s |
| `face-finder-error-selftest.log` | a failed self-test after installing: removed again and switched off |
| `report_face_finder_hang.md`, `sheet_face_finder_hang.jpg` | the whole edit through `editor.py ai-edit` (as the app runs it) with a hanging face finder: 11/11 cues, rendered, cards in the safe zones, the warning with the log's path |

NOT VERIFIED: Windows. The fix has not been run on the user's PC yet.
