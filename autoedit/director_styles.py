"""The Director's style presets and the word lists it uses to read the mood of what is said.

A style is data: how many graphics at most, how far apart, which kinds of templates it likes,
which colours and emphasis transitions it uses. Add your own by adding an entry to STYLES.
"""

# category weights: how much the style likes each kind of template (0 = never)
STYLES = {
    "promoter": {
        "label": "Professional promoter", "tl": "Propesyonal na promoter",
        "about": "Fast and loud: pop-up words, counters, cards and emoji on every key phrase, "
                 "with flash and punch-in on the big moments.",
        "max_per_10s": 4, "min_gap": 1.1, "duration": 1.0, "size": 1.0, "intensity": 0.85,
        "categories": {"text": 1.0, "card": 0.9, "pill": 0.9, "data": 1.0, "pointer": 0.8,
                       "emoji": 0.9, "banner": 0.8},
        "prefer": ["pop-heavy", "highlight-box", "counter-number", "stamp", "bounce-words",
                   "prompt-card", "notification-stack", "lower-third-pill", "emoji-pop"],
        "deny": ["serif-elegant", "thin-spaced"],
        "palette": ["#ffd23f", "#ff3b6b", "#35e08a", "#58c8ff", "#ff7a1a", "#b388ff"],
        "attach": ["flash", "punch", "whip"], "attach_importance": 0.7, "attach_gap": 3.0,
        "wipe": True, "emoji": True, "hold": 0.35,
    },
    "calm_documentary": {
        "label": "Calm documentary", "tl": "Kalmadong documentary",
        "about": "Quiet and clean: a few thin or elegant titles and lower-thirds, slow motion, "
                 "no flashes.",
        "max_per_10s": 1, "min_gap": 3.5, "duration": 1.35, "size": 0.9, "intensity": 0.4,
        "categories": {"text": 1.0, "card": 0.5, "pill": 0.9, "data": 0.7, "pointer": 0.3,
                       "emoji": 0.0, "banner": 0.4},
        "prefer": ["thin-spaced", "slide-up", "lower-third-pill", "serif-elegant", "typewriter",
                   "quote-card", "glow-blur-in"],
        "deny": ["pop-heavy", "bounce-words", "glitch-text", "meme-caption", "stamp",
                 "sticker-label", "warning-banner", "emoji-pop", "emoji-burst"],
        "palette": ["#e8dcc0", "#9fc5c8", "#ffffff", "#c9d6a3"],
        "attach": [], "attach_importance": 2.0, "attach_gap": 99.0,
        "wipe": False, "emoji": False, "hold": 0.6,
    },
    "meme": {
        "label": "Meme / funny", "tl": "Meme / nakakatawa",
        "about": "Loud and silly: meme captions, stickers, emoji, bouncing words.",
        "max_per_10s": 3, "min_gap": 1.3, "duration": 0.95, "size": 1.05, "intensity": 1.0,
        "categories": {"text": 1.0, "card": 0.4, "pill": 0.5, "data": 0.4, "pointer": 0.8,
                       "emoji": 1.0, "banner": 1.0},
        "prefer": ["meme-caption", "sticker-label", "emoji-pop", "bounce-words", "emoji-burst",
                   "handwritten", "scribble-underline", "arrow-point"],
        "deny": ["serif-elegant", "thin-spaced", "news-banner", "quote-card"],
        "palette": ["#ffe14d", "#ff5c8a", "#00e5ff", "#7cff6b"],
        "attach": ["punch", "flash"], "attach_importance": 0.65, "attach_gap": 4.0,
        "wipe": False, "emoji": True, "hold": 0.3,
    },
    "news": {
        "label": "News / explainer", "tl": "Balita / paliwanag",
        "about": "Serious and tidy: headline banners, lower-thirds, numbers, checklists.",
        "max_per_10s": 2, "min_gap": 2.2, "duration": 1.15, "size": 0.95, "intensity": 0.5,
        "categories": {"text": 0.8, "card": 0.8, "pill": 1.0, "data": 1.0, "pointer": 0.6,
                       "emoji": 0.0, "banner": 1.0},
        "prefer": ["news-banner", "lower-third-pill", "counter-number", "stat-bar", "checklist",
                   "typewriter", "slide-up", "underline-draw"],
        "deny": ["meme-caption", "sticker-label", "bounce-words", "emoji-pop", "emoji-burst",
                 "glitch-text", "handwritten", "heart-like"],
        "palette": ["#d90429", "#2f6bff", "#ffffff", "#ffd23f"],
        "attach": ["whip"], "attach_importance": 0.9, "attach_gap": 6.0,
        "wipe": True, "emoji": False, "hold": 0.45,
    },
    "luxury": {
        "label": "Luxury / premium", "tl": "Luxury / premium",
        "about": "Slow and elegant: serif and gradient-gold titles, fine lines, no noise.",
        "max_per_10s": 1, "min_gap": 3.5, "duration": 1.3, "size": 0.95, "intensity": 0.45,
        "categories": {"text": 1.0, "card": 0.5, "pill": 0.5, "data": 0.6, "pointer": 0.0,
                       "emoji": 0.0, "banner": 0.0},
        "prefer": ["serif-elegant", "gradient-shine", "thin-spaced", "split-reveal",
                   "quote-card", "rating-stars"],
        "deny": ["pop-heavy", "bounce-words", "glitch-text", "meme-caption", "stamp",
                 "sticker-label", "warning-banner", "emoji-pop", "emoji-burst", "news-banner",
                 "typewriter", "karaoke-line"],
        "palette": ["#d8b56a", "#f4e4bc", "#ffffff"],
        "attach": [], "attach_importance": 2.0, "attach_gap": 99.0,
        "wipe": True, "emoji": False, "hold": 0.6,
    },
    "minimal": {
        "label": "Minimal", "tl": "Minimal",
        "about": "Almost nothing: now and then one clean word or underline.",
        "max_per_10s": 1, "min_gap": 4.0, "duration": 1.0, "size": 0.9, "intensity": 0.35,
        "categories": {"text": 1.0, "card": 0.0, "pill": 0.6, "data": 0.5, "pointer": 0.3,
                       "emoji": 0.0, "banner": 0.0},
        "prefer": ["slide-up", "underline-draw", "thin-spaced", "lower-third-pill",
                   "scribble-underline"],
        "deny": ["pop-heavy", "bounce-words", "glitch-text", "meme-caption", "stamp",
                 "sticker-label", "warning-banner", "emoji-pop", "emoji-burst", "news-banner",
                 "karaoke-line", "gradient-shine", "serif-elegant"],
        "palette": ["#ffffff", "#cfd6e4", "#ffd23f"],
        "attach": [], "attach_importance": 2.0, "attach_gap": 99.0,
        "wipe": False, "emoji": False, "hold": 0.5,
    },
}
DEFAULT_STYLE = "promoter"

# Words in the instruction that ask for a look, or for motion graphics at all.
STYLE_KEYWORDS = {
    "promoter": ["promoter", "promo", "hype", "ad ", "advert", "commercial", "kinetic",
                 "pop-up", "popup", "pop up", "motion graphic", "graphics", "graphic",
                 "animated text", "animation", "paligsahan", "pang-benta"],
    "calm_documentary": ["documentary", "calm", "kalmado", "cinematic", "mahinahon"],
    "meme": ["meme", "funny", "nakakatawa", "joke", "comedy"],
    "news": ["news", "balita", "explainer", "headline"],
    "luxury": ["luxury", "premium", "elegant", "classy", "mamahalin"],
    "minimal": ["minimal", "simple lang", "simple graphics", "konting graphics"],
}
GRAPHICS_WORDS = ["graphic", "pop-up", "popup", "pop up", "kinetic", "promoter", "motion",
                  "animated", "lower third", "lower-third", "counter", "arrow", "emoji",
                  "sticker", "before/after", "before and after", "wipe", "title card"]

# ---------------------------------------------------------------- words and moods

STOPWORDS = set("""
ang ng sa na at ay mga ko mo niya namin natin ninyo nila ito iyon iyan yung yun ung po ba din rin
lang naman pa nga si kay kung pag kapag para dahil kasi pero o ni nang may mayroon ako ikaw siya
kami tayo kayo sila ay am is are was were be been to of and a an the in on at for with from by as
it this that these those i you he she we they my your his her our their me him them so but or if
then than do does did have has had will would can could just very really um uh uhm ah eh
""".split())

CTA_WORDS = {"follow": "follow-pill", "subscribe": "follow-pill", "sundan": "follow-pill",
             "comment": "comment-pill", "i-comment": "comment-pill", "icomment": "comment-pill"}

MOOD_WORDS = {
    "money": """piso pesos peso pera kita sweldo sahod presyo libre discount sale benta benta
                bayad milyon libo daan gcash maya bank negosyo investment invest income profit
                money cash price free dollars revenue sales""".split(),
    "urgent": """ngayon agad bilis dali madali limited last huwag palampasin ubos ngayong
                 deadline now today hurry fast quick instantly""".split(),
    "warning": """mag-ingat ingat babala delikado panganib scam mali huwag bawal peligro stop
                  warning careful danger never mistake wrong avoid""".split(),
    "funny": """haha hahaha grabe naku loko joke biro tawa chaka lol funny nakakatawa pinoy
                kalokohan weird silly""".split(),
    "emotion": """mahal love salamat puso miss iyak masaya malungkot pamilya nanay tatay
                  thank thanks heart cry happy sad family dream pangarap""".split(),
    "tech": """ai app software code phone video edit online website internet laptop computer
               tool tools automation data system digital cloud tech apps""".split(),
    "hype": """wow bago new best amazing galing sobrang pinakamahusay idol sikreto secret
               unbelievable crazy insane powerful result results epic""".split(),
    "serious": """importante mahalaga totoo katotohanan fact facts research study ayon
                  important truth reason because dahilan""".split(),
    "calm": """relax kalma breathe slow dahan-dahan peace payapa simple gentle""".split(),
    "luxury": """luxury premium elegant exclusive gold branded mamahalin classic""".split(),
    "news": """balita ulat report headline update announcement breaking""".split(),
    "playful": """laro game fun masaya trick tips hack challenge""".split(),
}
EMOJI_FOR_MOOD = {"money": ["💸", "💰", "🤑"], "hype": ["🔥", "🚀", "⚡"], "funny": ["😂", "🤣", "😆"],
                  "emotion": ["❤️", "🥹", "🙏"], "warning": ["⚠️", "🚫", "😱"], "urgent": ["⏰", "🔥", "⚡"],
                  "tech": ["🤖", "💻", "⚡"], "playful": ["😎", "✨", "🎉"], "calm": ["🌿", "✨", "☁️"],
                  "serious": ["📌", "💡", "✅"], "luxury": ["✨", "💎", "👑"], "news": ["📢", "📰", "📌"]}
ICON_FOR_MOOD = {"money": "money", "hype": "rocket", "tech": "bolt", "emotion": "heart",
                 "warning": "warning", "urgent": "clock", "playful": "star", "serious": "check",
                 "funny": "star", "calm": "eye", "luxury": "star", "news": "bell"}
