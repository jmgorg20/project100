Video: a 29.8 s stand-in clip made with FFmpeg (the base video was not available here)  
Words: the word-timestamp fixture second_words.json (no transcription here)  
Preset: (none: default settings)  
Graphics: 0, effect clips: 6  
**1 passed, 12 FAILED**

| cue | said | expected | result | what appeared |
|---|---|---|---|---|
| hook | Limang minuto lang ito @ 1.02s | title ['minuto', 'limang', '5'] | **FAILURE** (nothing appeared for this cue) | — |
| count | Lima apat tatlo dalawa isa @ 2.44s | countdown ['5'] | **FAILURE** (nothing appeared for this cue) | — |
| keyword | Pangalawa PASENSYA @ 4.67s | title ['pasensya'] | **FAILURE** (nothing appeared for this cue) | — |
| before_after | Noon takot akong mag-live @ 5.86s | bw  | **FAILURE** (nothing appeared for this cue) | — |
| search | i-type ninyo murang ulam recipe @ 9.91s | search bar ['murang ulam recipe'] | **FAILURE** (nothing appeared for this cue) | — |
| screenshot | Tingnan ninyo ang graph ng sales ko @ 11.92s | floating screenshot ['search_results.png'] | **FAILURE** (nothing appeared for this cue) | — |
| list | Mga gamit ko sa kusina @ 14.16s | checklist ['kawali', 'sandok', 'rice cooker'] | **FAILURE** (nothing appeared for this cue) | — |
| platforms | Nasa Instagram at YouTube ako @ 17.59s | logo cards ['instagram', 'youtube'] | **FAILURE** (nothing appeared for this cue) | — |
| handle | @lutongbahay.ph @ 19.39s | profile card ['@lutongbahay.ph'] | **FAILURE** (nothing appeared for this cue) | — |
| storyboard | Plano ko intro luto tikim @ 19.98s | storyboard ['intro', 'luto', 'tikim'] | **FAILURE** (nothing appeared for this cue) | — |
| stats | Mula isang daan hanggang limang libong views sa dalawang linggo @ 22.13s | numbers ['100', '5000', '2'] | **FAILURE** (nothing appeared for this cue) | — |
| follow | Mag-subscribe ka na | follow card ['@lutongbahay.ph', 'subscribe', 'follow'] | **FAILURE** (the phrase is not in the transcript (cut out?)) | — |
| captions | (every caption on screen) | no end punctuation  | PASS | — |
