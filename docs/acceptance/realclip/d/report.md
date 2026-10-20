Video: the video /home/user/realtest/export.mp4  
Words: the word-timestamp file groq_words.json, given with --transcript  
Preset: premium_editorial_viral  
Graphics: 9, effect clips: 13  
**10 passed, 0 FAILED**

| cue | said | expected | result | what appeared |
|---|---|---|---|---|
| hook | tatlong sikreto ng viral na video @ 0.7s | title ['sikreto', 'viral'] | PASS | magazine-cover @ 0.7s: sikreto | tatlong sikreto ng viral na video | disiplina | ito na ako | paano kumita online | 1 |
| count | Tatlo dalawa isa @ 2.82s | countdown ['3'] | PASS | countdown-timer @ 2.83s: 3 |
| keyword | Una disiplina @ 4.82s | title ['disiplina'] | PASS | kinetic-words @ 4.83s: disiplina |
| before_after | Dati wala akong follower @ 6.22s | bw  | PASS | bw @ 6.13s:  |
| search | Sa search bar hinanap ko paano kumita online @ 9.82s | search bar ['paano kumita online'] | PASS | search-bar @ 9.83s: paano kumita online |
| screenshot | Ito ang screenshot ng resulta ko @ 13.12s | floating screenshot ['search_results.png'] | PASS | screenshot-collage @ 13.67s: search_results.png |
| checklist | Ito ang checklist ko sa phone @ 15.3s | checklist ['mag-post', 'sagutin ang comments', 'i-check ang analytics'] | PASS | editorial-checklist @ 15.3s: checklist ko sa phone | mag-post | sagutin ang comments | i-check ang analytics |
| stats | Mula zero hanggang isang libong followers @ 20.22s | numbers ['0', '1000', '30'] | PASS | stat-cards @ 20.53s: 0 | 1,000 followers | 30 araw |
| follow | I-follow mo ako @ 24.8s | follow card ['follow', 'profile_photo.png'] | PASS | profile-card @ 24.8s: i-follow mo ako | profile_photo.png |
| captions | (every caption on screen) | no end punctuation  | PASS | — |

What the AI did (as the app shows it):

- Preset: PREMIUM EDITORIAL VIRAL.
- Preset: No music added: put music you may use in assets/music (a name with 'upbeat' is picked first).
- Fixed 2 misheard Taglish word(s): 'Tatyo' -> 'Tatlo', 'tatlumpong' -> 'tatlumpung'.
- Cut the pauses and filler words (longer than 0.25s): 0:26 -> 0:26, 0 jump cuts.
- Added 4 zoom-ins.
- Captions in the editorial_card style: 15 lines.
- Added 1 effect: bw at 0:06.
- Colour: natural clean.
- Photos not used: facebook_logo.png, profile_photo.png, search_results.png, tiktok_logo.png, youtube_logo.png.
- Motion graphics (Premium editorial): 9 placed.
-   0:01  magazine-cover - SIKRETO
-   0:03  countdown-timer - Tatlo dalawa isa
-   0:05  kinetic-words - DISIPLINA
-   0:06  strike-text - wala akong follower
-   0:10  search-bar - paano kumita online
-   0:14  screenshot-collage - Ito ang screenshot ng resulta ko
-   0:15  editorial-checklist - checklist ko sa phone
-   0:21  stat-cards - zero hanggang isang libong followers sa tatlumpung araw
-   0:25  profile-card - I-follow mo ako
- Graphics: You asked for countdown: made at 0:03 ("Tatlo dalawa isa").
- Graphics: You asked for big word title: made at 0:01 ("tatlong sikreto ng viral na video"), 0:05 ("Una disiplina").
- Graphics: You asked for search bar: made at 0:10 ("Sa search bar hinanap ko paano kumita on").
- Graphics: You asked for screenshot: made at 0:14 ("Ito ang screenshot ng resulta ko").
- Graphics: You asked for checklist: made at 0:15 ("Ito ang checklist ko sa phone Mag-post s").
- Graphics: You asked for logo cards: nothing in what you said asks for it, so none was made (to get one, name the apps ("Nasa TikTok, Facebook at YouTube ako")).
- Graphics: You asked for profile card: made at 0:25 ("I-follow mo ako").
- Graphics: You asked for storyboard card: nothing in what you said asks for it, so none was made (to get one, say "Storyboard ko: hook, kwento, call to action").
- Graphics: You asked for number cards: made at 0:21 ("zero hanggang isang libong followers sa ").
- Graphics: You asked for black and white: made at 0:06.
- Graphics: Your face was found by the built-in face finder; cards keep off it (the speaker moves lower while a card is up).
