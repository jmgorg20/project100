Video: a 30.67 s stand-in clip made with FFmpeg (the base video was not available here)  
Words: the word-timestamp fixture second_words.json (no transcription here)  
Preset: premium_editorial_viral  
Graphics: 13, effect clips: 23  
**13 passed, 0 FAILED**

| cue | said | expected | result | what appeared |
|---|---|---|---|---|
| hook | Limang minuto lang ito @ 1.02s | title ['minuto', 'limang', '5'] | PASS | magazine-cover @ 1.0s: minuto | limang minuto lang ito | pasensya | araw-araw na | murang ulam recipe | 1; countdown-timer @ 2.43s: 5 |
| count | Lima apat tatlo dalawa isa @ 2.44s | countdown ['5'] | PASS | countdown-timer @ 2.43s: 5 |
| keyword | Pangalawa PASENSYA @ 4.67s | title ['pasensya'] | PASS | kinetic-words @ 4.67s: pasensya |
| before_after | Noon takot akong mag-live @ 5.86s | bw  | PASS | bw @ 5.77s:  |
| search | Sa search bar i-type ninyo murang ulam recipe @ 8.89s | search bar ['murang ulam recipe'] | PASS | search-bar @ 8.9s: murang ulam recipe |
| screenshot | Tingnan ninyo ang graph ng sales ko @ 11.92s | floating screenshot ['search_results.png'] | PASS | screenshot-collage @ 12.9s: search_results.png |
| list | Mga gamit ko sa kusina @ 14.16s | checklist ['kawali', 'sandok', 'rice cooker'] | PASS | editorial-checklist @ 14.17s: gamit ko sa kusina | kawali | sandok | rice cooker |
| platforms | Nasa Instagram at YouTube ako @ 17.59s | logo cards ['instagram', 'youtube'] | PASS | app-tile @ 17.9s: instagram; app-tile @ 18.57s: youtube | youtube_logo.png |
| handle | @lutongbahay.ph @ 19.39s | profile card ['@lutongbahay.ph'] | PASS | profile-card @ 19.4s: @lutongbahay.ph | profile_photo.png |
| storyboard | Plano ko intro luto tikim @ 19.98s | storyboard ['intro', 'luto', 'tikim'] | PASS | profile-card @ 19.4s: @lutongbahay.ph | profile_photo.png; storyboard-doc @ 19.97s: plano ko | intro | luto | tikim |
| stats | Mula isang daan hanggang limang libong views sa dalawang linggo @ 22.13s | numbers ['100', '5000', '2'] | PASS | stat-cards @ 22.43s: 100 | 5,000 views | 2 linggo |
| follow | Mag-subscribe ka na @ 25.68s | follow card ['@lutongbahay.ph', 'subscribe', 'follow'] | PASS | profile-card @ 25.67s: @lutongbahay.ph | profile_photo.png |
| captions | (every caption on screen) | no end punctuation  | PASS | — |
