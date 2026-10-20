Video: the video /home/user/realtest/export.mp4  
Words: the word-timestamp file groq_words.json, given with --transcript  
Preset: premium_editorial_viral  
Graphics: 5, effect clips: 11  
**5 passed, 5 FAILED**

| cue | said | expected | result | what appeared |
|---|---|---|---|---|
| hook | tatlong sikreto ng viral na video @ 0.7s | title ['sikreto', 'viral'] | PASS | kinetic-words @ 0.1s: teka lang tatlong sikreto ng viral na |
| count | Tatyo dalawa isa @ 2.82s | countdown ['3'] | **FAILURE** (nothing appeared for this cue) | — |
| keyword | Una disiplina @ 4.82s | title ['disiplina'] | **FAILURE** (nothing appeared for this cue) | — |
| before_after | Dati wala akong follower @ 6.22s | bw  | PASS | bw @ 5.87s:  |
| search | Sa search bar hinanap ko paano kumita online @ 9.82s | search bar ['paano kumita online'] | PASS | search-bar @ 10.53s: bar hinanap ko paano kumita online |
| screenshot | Ito ang screenshot ng resulta ko @ 13.12s | floating screenshot ['search_results.png'] | PASS | phone-mockup @ 13.67s: search_results.png |
| checklist | Ito ang checklist ko sa phone @ 15.3s | checklist ['mag-post', 'sagutin ang comments', 'i-check ang analytics'] | **FAILURE** (nothing appeared for this cue) | — |
| stats | Mula zero hanggang isang libong followers @ 20.22s | numbers ['0', '1000', '30'] | **FAILURE** (nothing appeared for this cue) | — |
| follow | I-follow mo ako @ 24.8s | follow card ['follow', 'profile_photo.png'] | **FAILURE** (nothing appeared for this cue) | — |
| captions | (every caption on screen) | no end punctuation  | PASS | — |

What the AI did (as the app shows it):

- Preset: PREMIUM EDITORIAL VIRAL.
- Preset: No music added: put music you may use in assets/music (a name with 'upbeat' is picked first).
- Format: Ranking / countdown (your instructions ask for it).
- Cut the pauses and filler words (longer than 0.25s): 0:26 -> 0:26, 0 jump cuts.
- Added 5 zoom-ins.
- Captions in the editorial_card style: 9 lines.
- Added 1 effect: bw at 0:06.
- Colour: natural clean.
- Photos not used: facebook_logo.png, profile_photo.png, search_results.png, tiktok_logo.png, youtube_logo.png.
- Motion graphics (Premium editorial): 5 placed.
-   0:00  search-bar - paano kumita online Ito ang screenshot ng resulta
-   0:00  kinetic-words - Teka lang tatlong sikreto ng viral na video Tatyo dalawa isa Una disiplina Dati wala akong fo
-   0:11  search-bar - bar hinanap ko paano kumita online
-   0:14  phone-mockup - Teka lang tatlong sikreto ng viral na video Tatyo dalawa isa Una disiplina Dati wala akong fol
-   0:23  marker-highlight - tatlumpong araw I-follow
- Graphics: Left out a graphic at 0:01: no free space that keeps the face and captions clear.
- Graphics: The stats graphic at 0:01 was left out: no free space that keeps the face and captions clear.
- Graphics: The face was not tracked, so cards keep off the upper-middle of the frame, where a speaker usually is. (Set up tracking, docs/tracking.md, to place them around the real face.)
