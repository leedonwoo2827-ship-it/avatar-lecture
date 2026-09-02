# -*- coding: utf-8 -*-
"""언어 표 — 화면과 번역이 같은 것을 본다.

260831 hyper-close-frame 의 `pipeline/s8_translate.py` 에서 그대로 가져왔다.
두 도구를 오가며 쓰는데 언어 목록이 다르면 「저기선 됐는데 여기선 안 된다」가 된다.

    iso     세 글자 코드 — 이 표의 열쇠
    name    화면에 뜨는 한국어 이름
    native  원어 이름 (사람이 자기 언어를 찾을 때 쓴다)
    tag     파일 꼬리표 두 글자 — `sceneNN.<tag>.srt`
    script  문자 체계 — 화면에서 이걸로 묶어 보여 준다
    cps     **자/초.** 그 언어를 눈으로 읽는 속도다.

## cps 가 왜 중요한가

자막은 **씬 길이 안에 읽히는 만큼만** 들어갈 수 있다. 같은 뜻이라도 한중일은
6~7자/초, 라틴·키릴은 14~15자/초라 들어가는 글자 수가 두 배 넘게 차이 난다.
그래서 옮길 때 `길이(초) x cps` 를 글자 수 상한으로 준다 — 안 그러면 뜻은 맞는데
화면에 다 못 뜨는 자막이 나온다.

한 줄 최대 글자수(common.CUE_MAX_CHARS)와는 다른 값이다. 저건 **줄 폭**,
이건 **총량**이다. 둘 다 지켜야 한다.
"""
from __future__ import annotations

# iso3 → (한국어 이름, 원어 이름, 파일 꼬리표, 문자 체계, 자/초)
LANGS: dict[str, dict] = {
    "eng": {"name": "영어", "native": "English", "tag": "en",
             "script": "latin", "cps": 15.0},
    "jpn": {"name": "일본어", "native": "日本語", "tag": "ja",
             "script": "kana", "cps": 7.0},
    "zho": {"name": "중국어", "native": "中文", "tag": "zh",
             "script": "han", "cps": 6.0},
    "rus": {"name": "러시아어", "native": "Русский", "tag": "ru",
             "script": "cyrillic", "cps": 14.0},
    "spa": {"name": "스페인어", "native": "Español", "tag": "es",
             "script": "latin", "cps": 15.0},
    "fra": {"name": "프랑스어", "native": "Français", "tag": "fr",
             "script": "latin", "cps": 15.0},
    "deu": {"name": "독일어", "native": "Deutsch", "tag": "de",
             "script": "latin", "cps": 14.0},
    "por": {"name": "포르투갈어", "native": "Português", "tag": "pt",
             "script": "latin", "cps": 15.0},
    "ita": {"name": "이탈리아어", "native": "Italiano", "tag": "it",
             "script": "latin", "cps": 15.0},
    "nld": {"name": "네덜란드어", "native": "Nederlands", "tag": "nl",
             "script": "latin", "cps": 14.0},
    "pol": {"name": "폴란드어", "native": "Polski", "tag": "pl",
             "script": "latin", "cps": 14.0},
    "tur": {"name": "터키어", "native": "Türkçe", "tag": "tr",
             "script": "latin", "cps": 14.0},
    "ukr": {"name": "우크라이나어", "native": "Українська", "tag": "uk",
             "script": "cyrillic", "cps": 14.0},
    "vie": {"name": "베트남어", "native": "Tiếng Việt", "tag": "vi",
             "script": "latin", "cps": 15.0},
    "ind": {"name": "인도네시아어", "native": "Bahasa Indonesia", "tag": "id",
             "script": "latin", "cps": 15.0},
    "msa": {"name": "말레이어", "native": "Bahasa Melayu", "tag": "ms",
             "script": "latin", "cps": 15.0},
    "tgl": {"name": "필리핀어", "native": "Filipino", "tag": "tl",
             "script": "latin", "cps": 15.0},
    "tha": {"name": "태국어", "native": "ไทย", "tag": "th",
             "script": "thai", "cps": 9.0},
    "khm": {"name": "크메르어", "native": "ខ្មែរ", "tag": "km",
             "script": "khmer", "cps": 9.0},
    "mya": {"name": "미얀마어", "native": "မြန်မာ", "tag": "my",
             "script": "myanmar", "cps": 9.0},
    "lao": {"name": "라오어", "native": "ລາວ", "tag": "lo",
             "script": "lao", "cps": 9.0},
    "hin": {"name": "힌디어", "native": "हिन्दी", "tag": "hi",
             "script": "devanagari", "cps": 12.0},
    "nep": {"name": "네팔어", "native": "नेपाली", "tag": "ne",
             "script": "devanagari", "cps": 12.0},
    "ben": {"name": "벵골어", "native": "বাংলা", "tag": "bn",
             "script": "bengali", "cps": 12.0},
    "sin": {"name": "싱할라어", "native": "සිංහල", "tag": "si",
             "script": "sinhala", "cps": 12.0},
    "tam": {"name": "타밀어", "native": "தமிழ்", "tag": "ta",
             "script": "tamil", "cps": 12.0},
    "urd": {"name": "우르두어", "native": "اردو", "tag": "ur",
             "script": "arabic", "cps": 12.0},
    "ara": {"name": "아랍어", "native": "العربية", "tag": "ar",
             "script": "arabic", "cps": 12.0},
    "fas": {"name": "페르시아어", "native": "فارسی", "tag": "fa",
             "script": "arabic", "cps": 12.0},
    "uzb": {"name": "우즈베크어", "native": "Oʻzbekcha", "tag": "uz",
             "script": "latin", "cps": 14.0},
    "kaz": {"name": "카자흐어", "native": "Қазақша", "tag": "kk",
             "script": "cyrillic", "cps": 13.0},
    "mon": {"name": "몽골어", "native": "Монгол", "tag": "mn",
             "script": "cyrillic", "cps": 13.0},
    "swa": {"name": "스와힐리어", "native": "Kiswahili", "tag": "sw",
             "script": "latin", "cps": 15.0},
}

# 화면이 묶어 보여 줄 순서. 여기 없는 문자 체계는 «그 밖» 으로 몰린다.
SCRIPTS = [
    ("latin", "라틴 문자"), ("cyrillic", "키릴 문자"), ("han", "한자"),
    ("kana", "가나"), ("arabic", "아랍 문자"), ("devanagari", "데바나가리"),
    ("thai", "타이 문자"), ("bengali", "벵골 문자"), ("sinhala", "싱할라 문자"),
    ("tamil", "타밀 문자"), ("khmer", "크메르 문자"), ("myanmar", "미얀마 문자"),
    ("lao", "라오 문자"),
]

TAG = {k: v["tag"] for k, v in LANGS.items()}
BY_TAG = {v["tag"]: k for k, v in LANGS.items()}


def find(word: str) -> str:
    """«러시아» · «Русский» · «ru» · «rus» 중 무엇으로 찾아도 iso3 를 돌려준다.

    사람은 자기가 아는 이름으로 찾는다. 코드를 외우게 하지 않는다.
    """
    w = (word or "").strip().lower()
    if not w:
        return ""
    if w in LANGS:
        return w
    if w in BY_TAG:
        return BY_TAG[w]
    for iso, v in LANGS.items():
        if w == v["name"].lower() or w == v["native"].lower():
            return iso
    for iso, v in LANGS.items():
        if w in v["name"].lower() or w in v["native"].lower():
            return iso
    return ""


def rows_for_ui() -> list[dict]:
    """화면이 받아 갈 목록 — 문자 체계 순서대로."""
    order = {s: i for i, (s, _) in enumerate(SCRIPTS)}
    out = [{"iso": k, **v} for k, v in LANGS.items()]
    out.sort(key=lambda r: (order.get(r["script"], 99), r["name"]))
    return out


def budget_chars(iso: str, seconds: float) -> int:
    """이 언어로 `seconds` 안에 읽힐 수 있는 글자 수. 번역 길이 상한이다."""
    v = LANGS.get(iso)
    return int(max(1.0, seconds) * (v["cps"] if v else 14.0))
