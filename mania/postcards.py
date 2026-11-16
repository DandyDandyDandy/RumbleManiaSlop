"""Postcards: the tips on Banana Rumble's loading screens, and postcards of one's own for the fork.

A loading screen shows one row of the table `Tips`: a picture (UI_Sprite row, 512 x 512), a title and a text
(`Tips_Text_<lang>`, one row per message id), and its category (`Tips_Category`: a stamp icon and a name). The
game picks the row by `Tips_Terms`: every terms row is a list of tips that may show in some modes and stages of
progress; `TipsManager.pick` takes the lists in turn (a preferential one every other time) and steps through the
tips of each, keeping the place in the save. The Gallery's Documents list the tips too.

The user's postcards (overrides.json "postcards", written by the editor) become rows after the game's own, in a
terms row of their own that is open everywhere (a copy of terms row 1) and preferential: every other loading
screen takes a preferential list (the game has two or three open at a time, the control guides among them), so
one of the user's postcards comes up about every fourth loading screen, in turn. Their text is the same in every
language.

    "postcards": {"<key>": {"title": "...", "text": "...", "category": <Tips_Category id>, "picture": "<file>",
                            "off": true}}
"""
from dbtable import LANGS, SCHEMAS

SCHEMAS.update({
    'Tips': [('TermsID', 'i'), ('CategoryID', 'i'), ('Title', 'u'), ('Explanation', 'u'), ('SpriteID', 'i'),
             ('UnlockCharaID', 'i'), ('IsIgnoreHandsOn', 'b'), ('IsEnabledTrial', 'b')],
    'Tips_Text': [('Title', 's'), ('Explanation', 's')],
    'Tips_Category': [('Name', 'u'), ('IconSpriteID', 'i'), ('DocumentThumbnailSpriteID', 'i')],
    'Tips_Category_Text': [('Name', 's')],
    'Tips_Terms': [('IsPlayStyle', '[b]'), ('IsProgressStory', '[b]'), ('IsProgressBattle', '[b]'), ('IsPreferential', 'b'),
                   ('TermsCategoryID', 'i'), ('TermsText', 'u'), ('IsBattleProgressStory', '[b]'), ('IsEnabledBattleType', '[b]')],
    'Tips_Terms_Text': [('TermsText', 's')],
})

OPEN_TERMS = 1                  # the game's terms row that is open in every mode and at every stage of progress
# (isEnabledTerm: the play style, then for a preferential pick only preferential rows; row 12 asks the progress,
# the others the mode: Adventure leaves out TermsCategoryID 3, Battle more)
DEFAULT_CATEGORY = 10           # "Hints"
TEMPLATE_SPRITE = 2716          # a tip picture of the game (512 x 512, DXT1): the model for the user's


def game_postcards(db):
    """The game's own tips and categories for the editor: {'postcards': [...], 'categories': [...]}."""
    tips, text = db.table('Tips'), db.table('Tips_Text_en')
    cat, cat_text = db.table('Tips_Category'), db.table('Tips_Category_Text_en')
    terms_text = db.table('Tips_Terms_Text_en')
    terms = db.table('Tips_Terms')
    categories = [{'id': r['_id'], 'name': cat_text.row(r['Name'])['Name'], 'icon': r['IconSpriteID']}
                  for r in sorted((r for r in cat.rows if not r['_empty']), key=lambda r: r['_order'])]
    out = []
    for r in sorted((r for r in tips.rows if not r['_empty']), key=lambda r: r['_order']):
        t, tr = text.row(r['Title']), terms.row(r['TermsID'])
        out.append({'id': r['_id'], 'title': t['Title'] if t else '', 'text': (text.row(r['Explanation']) or {}).get('Explanation', ''),
                    'category': r['CategoryID'], 'picture': r['SpriteID'], 'terms': r['TermsID'],
                    'when': (terms_text.row(tr['TermsText']) or {}).get('TermsText', '').strip() if tr else '',
                    'chara': r['UnlockCharaID']})
    return {'postcards': out, 'categories': categories}


def add(db, sprites, ov, out, own_picture):
    """The user's postcards into the tables (db: the import's dbtable.Database; sprites: its sprites.Sprites;
    own_picture: build.own_picture). Returns how many were added."""
    cards = [(k, c) for k, c in sorted(ov.get('postcards', {}).items(), key=lambda kv: _order(kv[0]))
             if not c.get('off') and (c.get('title') or c.get('text'))]
    # opened (and so written) also without postcards: the copies of an earlier import must not stay
    tips, terms, cats = db.table('Tips'), db.table('Tips_Terms'), db.table('Tips_Category')
    text = {lang: db.table(f'Tips_Text_{lang}') for lang in LANGS}
    terms_text = {lang: db.table(f'Tips_Terms_Text_{lang}') for lang in LANGS}
    if not cards:
        return 0
    # a terms row of their own, open everywhere as row 1
    tid = len(terms.rows)
    model = terms.row(OPEN_TERMS)
    msg = max(r['_id'] for r in terms_text['en'].rows) + 1
    fields = {k: (list(v) if isinstance(v, list) else v) for k, v in model.items() if not k.startswith('_')}
    terms.use(tid, **dict(fields, IsPreferential=True, TermsText=msg))
    for lang, t in terms_text.items():
        t.use(msg, TermsText=' ')
    msg = max(max(r['_id'] for r in t.rows) for t in text.values()) + 1
    for key, c in cards:
        rid = len(tips.rows)
        sprite = TEMPLATE_SPRITE        # without a picture of one's own: the game's picture of many hints
        pic = own_picture(c, 'picture')
        if pic:
            sprite = sprites.add('card_' + pic[0], pic[1], out, template=TEMPLATE_SPRITE)
        category = c.get('category', DEFAULT_CATEGORY)
        row = cats.row(category)
        if row is None or row['_empty']:
            category = DEFAULT_CATEGORY
        tips.use(rid, TermsID=tid, CategoryID=category, Title=msg, Explanation=msg, SpriteID=sprite, UnlockCharaID=0,
                 IsIgnoreHandsOn=False, IsEnabledTrial=True)
        for t in text.values():
            t.use(msg, Title=c.get('title', ''), Explanation=c.get('text', ''))
        msg += 1
    return len(cards)


def _order(key):
    return (0, int(key)) if key.isdigit() else (1, key)
