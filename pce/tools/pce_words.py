"""Build pce/translation/words.json: the menu and verb labels.

Every label in every module's word list is looked up in the PS1
translation by its bare Japanese (pce_reuse's loose key); the fullest
wording wins - a `long` over the short label it stands for, the longest
of several candidates, never a dossier heading (colour code, quotes) or a
spoken variant (a trailing ? or ...). HAND below is what the PS1 has no
label for, and what reads better on the PCE.

Labels no longer fit a byte slot: the bytecode names an item by offset and
pcescript remaps every reference, so a label is as long as the words are.
What the engine matches against player input gets no English (is_data):
the ★ wildcards and 以外 catch-alls, the dial numbers, and in the data
lists (pcescript.DATA_LISTS) every katakana-only record - the kana
keyboard's rows, the search keys, ベンソン and its misspellings, the
OLEEN/QUEEN set, the chess pieces - until the PCE's keyboard is Latin.

  python pce/tools/pce_words.py          # rebuild words.json, list what is missing
  python pce/tools/pce_words.py --refresh <commit> [--write]
        # the PS1's labels moved on (the 0.9.1 sweep spelled some 400 out):
        # every words.json label still equal to what this generator made from
        # the PS1 data at <commit> takes what it makes from the PS1 data now,
        # if it fits the list box's 8 cells; a label hand-edited past the
        # generator, or too wide, is listed for a hand decision. words.json is
        # hand-maintained past its generator (Parrot, Look around, Traffic
        # light...), so a plain rebuild regresses it - refresh instead.
"""
import collections, glob, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
WORK = os.path.join(ROOT, 'work')
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import pce_reuse as R
import pcescript as S
import patch_pce as P

HAND = {
    # the save handler (158 and its Act copies 270/286/302): the prompt after
    # a save, and Konami's debug scene picker in the same list - an
    # all-English module draws any kanji left in a label as pair glyphs
    # ("ゲームを'rける" after the first save), so nothing stays Japanese
    "ゲームを続ける": "Continue", "終了する": "End the game",
    "ａｃｔ１前半": "Act 1 part 1", "ａｃｔ１後半": "Act 1 part 2", "ａｃｔ２開始": "Act 2 start",
    "ａｃｔ２前半": "Act 2 part 1", "ａｃｔ２後半": "Act 2 part 2", "ａｃｔ３開始": "Act 3 start",
    "ＪＤへ直行": "To Joy Division", "ＯＨへ直行": "To Outer Heaven", "ＯＨナポレオン": "OH: Napoleon",
    "ＱＵＥＥＮ病院": "Queen Hospital", "ランダム復活": "Randam returns", "リサと": "With Lisa",
    "カトリーヌを探せ": "Find Catherine", "ギリアン宅へ直行": "Gillian's home", "ギブスン家へ直行": "To Gibson's home",
    "シューティング": "Shooting", "ナポレオンに会う": "Meet Napoleon", "ハリーのいるメカ室へ行く": "Harry, Mech room",
    "教会へ向かう": "To the church", "局長その１": "Chief, part 1", "局長その２": "Chief, part 2",
    "工場跡からの帰還": "From the factory", "工場跡へ行く": "To the factory", "自宅カトリーヌ": "Catherine, home",
    "病院ランダム同行": "Randam, hospital", "暴走シーン": "Rampage scene", "クィーン病院１": "Queen Hosp. 1",
    # the videophone's services (190) and the Telephone Game Quiz's answers
    # (206) are picked from lists, not typed
    "クイズ": "Quiz", "エッチ": "Adult", "ジェミー": "Jamie",
    "ヨンセンマン": "Yonsenman", "アグネス・ラムネ": "Agnes Ramune", "コシアンコさん": "Miss Koshianko",
    "トシちゃん": "Toshi-chan", "ペティ・ママ": "Betty Mama", "ミロちゃん": "Milo-chan", "麦麦クラブ": "Mugimugi Club",
    "美河憲ー": "Kenichi Mikawa", "ＭＳＸ２十": "MSX2+",
    "１枚": "1 disk", "２枚": "2 disks", "３枚": "3 disks", "４枚": "4 disks", "５枚": "5 disks", "６枚": "6 disks",
    "７枚": "7 disks", "８枚": "8 disks", "２回": "2 times", "４回": "4 times", "６回": "6 times", "８回": "8 times",
    "１０回": "10 times", "１２回": "12 times", "ａｃｔ３": "Act 3",
    "１２８ＸＸ": "128XX", "１２８ＸＹ": "128XY", "１８ＸＸ": "18XX", "１８ＸＹ": "18XY", "４６ＸＸ": "46XX", "４６ＸＹ": "46XY",
    "６４ＸＸ": "64XX", "６４ＸＹ": "64XY", "ＭＳＸ": "MSX", "ＭＳＸ２": "MSX2", "ＰＣ８８": "PC-88", "ＰＣ９８": "PC-98",
    "ＴＯＷＮＳ": "TOWNS", "Ｘ６８０００": "X68000",
    # the list box is 8 cells wide (16 letters, a digit or a symbol a cell of
    # its own) and cuts a longer label: "Continue the gam" after a save
    "セーブ１に上書き": "Replace save 1", "セーブ２に上書き": "Replace save 2", "セーブ３に上書き": "Replace save 3",
    "セーブ４に上書き": "Replace save 4", "メタルに番号聞く": "Ask Metal number", "リトルのメモリー": "Little's memory",
    "南北問題": "North vs South", "シベリア中立領土": "Neutral Siberia", "核の消滅": "Nuclear ban", "移民問題": "Immigration",
    "自動交通システム": "Traffic system", "文化・スポーツ": "Culture & sport", "書斎へ戻る": "Back to study",
    "紫外線療法の病院": "Ultraviolet ward", "老人の家": "Old man's house", "質問に答える": "Answer", "遊園地": "Amusement park",
    # the PS1 has no label for these
    "おかねさん": "Miss Money",
    "お面ライダー": "Mask Rider",
    "エイリヤン": "Alyen",
    "ガリバー": "Gulliver",
    "コウネリヤッサン": "Cornelius",
    "ダダダ": "Dadada",
    "Ｈ２Ｏ": "H2O",
    "ナノマシンとは": "Nanomachines",
    "ナポレオンの人種": "Napoleon's race",
    "メタルギア使う": "Use Metal Gear",
    "場所移動": "Move on",
    "崖にあたる": "Hit the cliff",
    "映像": "Footage",
    "映像メモリー": "Video memory",
    "机の引出し": "Desk drawer",
    "死亡推定時間": "Time of death",
    "焚火": "Bonfire",
    "神に祈る": "Pray to God",
    "耳を済ます": "Listen",
    "臭う": "Smell",
    "買った": "Bought it",
    "買ってない": "Didn't buy",
    "賞金稼ぎ屋": "Bounty hunter",
    "電話番号": "Phone number",
    "ＪＯＹについて": "About JOY",
    "ＪＵＮＫＥＲの事": "About JUNKER",
    "ＪＵＮＫＥＲ関係": "JUNKER files",
    "ＰＣ６８": "PC68",
    "ＶＴＲ": "VTR",
    "紫外線": "UV rays",
    "本部設備": "HQ facilities",
    "ボタン１": "Button 1",
    "ボタン２": "Button 2",
    "ボタン３": "Button 3",
    "扉１": "Door 1",
    "扉２": "Door 2",
    "扉３": "Door 3",
    "輪郭": "Face",
    "２０２号室": "Room 202",
    "３０１号室": "Room 301",
    # the videophone (174, 190)
    "かけない": "Don't call",
    "かける": "Call",
    "ビデオフォン切る": "Hang up",
    "持物見せる": "Show an item",
    "記憶": "Memory",
    "答える": "Answer",
    "答えない": "Don't answer",
    "自分の仕事": "My work",
    "夢": "Dream",
    "写真の事": "About the photo",
    "留守電の事": "The answerphone",
    "愛のキューピット": "Love's Cupid",
    "陳周鳳": "Chin Shu Ho",
    "ギブスン家": "Gibson's home",
    "レース": "The races",
    "イワン家": "Ivan's home",
    "ゲーセン": "The arcade",
    "ネグリジェ": "Negligee",
    "フレディ家": "Freddy's home",
    "ホテル": "A hotel",
    "ミュージカル": "A musical",
    "海": "The sea",
    "外出先": "Where you went",
    "近況報告": "How things are",
    "仕事": "Work",
    "水族館": "The aquarium",
    "食事": "Dinner",
    "動物園": "The zoo",
    "電話の相手": "Who called",
    # the quiz (206)
    "ゲームしない": "Don't play",
    "ゲームする": "Play",
    "ゲームやめる": "Quit the game",
    "安全地域": "Safe zone",
    # Gaudi's name search (254)
    "人名検索する": "Search a name",
    "人名検索やめる": "Stop searching",
    # Act 2 (382)
    "もみしだく": "Grope",
    "押し倒す": "Push her down",
    "チェス盤": "Chessboard",
    "パソコン": "Computer",
    "家具": "Furniture",
    "草むら": "Bushes",
    "涙拭う": "Wipe her tears",
    "触る": "Touch",
    "男の証明": "Prove I'm a man",
    "慰めモノにする": "Take advantage",
    "アリスなだめる": "Comfort Alice",
    "ギブスンの年齢": "Gibson's age",
    "３サイズ": "Her measurements",
    "ＰＣ６８について": "About the PC68",
}
# What the player types. The kana keyboard's rows (Gaudi's name search, 254)
# become Latin rows, so every key the engine matches against typed input
# becomes FULLWIDTH Latin (one cell per letter, the way the keyboard emits
# it): the search keys (PS1 keytable spellings), the videophone quiz answers
# and the BENSON / OLEEN / chess sets (PS1 PUZZLE_TARGETS spellings, 以外
# kept on the catch-alls). Fullwidth values are written as plain Shift-JIS.
TYPED = {254, 174, 190, 558, 574}         # the modules that compare typed input
# a record of a typed module that is a plain LABEL there, not a key: the name
# search's spellings must not reach it (574's Catherine is the Ask target in
# a framed box, 8 cells wide, and drew CATHERIN in fullwidth capitals until
# 2026-09-15 - her reference is followed by the label op 3a, the typed keys'
# by 20)
NOT_KEYS = {574: {"カトリーヌ"}}
KEYS = {
    # (the kana row records - ア, イウエオ, カキクケコ... - stay: the keyboard is
    # built on them (a change blanks it) and the search files its names
    # under them - pcescript.search_table / pcesearch make that work for
    # Latin names; what a key types comes from the system file's key
    # table, pcekeyboard)
    # the name search
    "メタルギア": "ＭＥＴＡＬＧＥＡＲ", "ヤラユウサク": "ＹＡＲＡＹＵＳＡＫＵ", "ヤマネキヨヒコ": "ＹＡＭＡＮＥＫＩＹＯＨＩＫＯ",
    "ヨシオカサトシ": "ＹＯＳＨＩＯＫＡＳＡＴＯＳＨＩ", "ランダムハジル": "ＲＡＮＤＡＭＨＡＪＩＬＥ", "ランダム": "ＲＡＮＤＡＭ",
    "リサニールセン": "ＬＩＳＡＮＩＥＬＳＥＮ", "リサ": "ＬＩＳＡ", "リトルジヨン": "ＬＩＴＴＬＥＪＯＨＮ", "リトル": "ＬＩＴＴＬＥ",
    "アリスギブスン": "ＡＬＩＣＥＧＩＢＳＯＮ", "アリス": "ＡＬＩＣＥ", "アダチトシヤ": "ＡＤＡＣＨＩＴＯＳＨＩＹＡ",
    "イワンロドリゲス": "ＩＶＡＮＲＯＤＲＩＧＵＥＺ", "イワン": "ＩＶＡＮ", "イケダタカハル": "ＩＫＥＤＡＴＡＫＡＨＡＲＵ",
    "イザベラベルベツト": "ＩＳＡＢＥＬＬＡＶＥＬＶＥＴ", "イザベラ": "ＩＳＡＢＥＬＬＡ", "イシイマサル": "ＩＳＨＩＩＭＡＳＡＲＵ",
    "イノウエキクコ": "ＩＮＯＵＥＫＩＫＵＫＯ", "イノウエシンヤ": "ＩＮＯＵＥＳＨＩＮＹＡ", "イノグチイサオ": "ＩＮＯＧＵＣＨＩＩＳＡＯ",
    "オメコ": "ＯＭＥＫＯ", "オヤジサン": "ＯＬＤＭＡＮ", "オオヤマハルカ": "ＯＹＡＭＡＨＡＲＵＫＡ", "オオタヨシヒコ": "ＯＴＡＹＯＳＨＩＨＩＫＯ",
    "オマンコ": "ＯＭＡＮＫＯ", "カトリーヌギブスン": "ＣＡＴＨＥＲＩＮＥＧＩＢＳＯＮ", "カトリーヌギブソン": "ＣＡＴＨＥＲＩＮＥＧＩＢＳＥＮ",
    "カトリーヌ": "ＣＡＴＨＥＲＩＮＥ", "キヤンタマ": "ＫＹＡＮＴＡＭＡ", "キヨクチヨウ": "ＣＨＩＥＦ", "キンタマ": "ＫＩＮＴＡＭＡ",
    "キノシタトミハル": "ＫＩＮＯＳＨＩＴＡＴＯＭＩＨＡＲＵ", "ギリアンシード": "ＧＩＬＬＩＡＮＳＥＥＤ", "ギリアン": "ＧＩＬＬＩＡＮ",
    "ギブスン": "ＧＩＢＳＯＮ", "コヤママミ": "ＫＯＹＡＭＡＭＡＭＩ", "コジマヒデオ": "ＫＯＪＩＭＡＨＩＤＥＯ", "コナミ": "ＫＯＮＡＭＩ",
    "サイカチリユウジ": "ＳＡＩＫＡＣＨＩＲＹＵＪＩ", "サカモトシンヤ": "ＳＡＫＡＭＯＴＯＳＨＩＮＹＡ", "サゴイサチヨ": "ＳＡＧＯＩＳＡＣＨＩＹＯ",
    "シオザワカネト": "ＳＨＩＯＺＡＷＡＫＡＮＥＴＯ", "シノハラケンジ": "ＳＨＩＮＯＨＡＲＡＫＥＮＪＩ", "シマケンジ": "ＳＨＩＭＡＫＥＮＪＩ",
    "ジヤンジヤツクギブスン": "ＪＥＡＮＪＡＣＫＧＩＢＳＯＮ", "ジヤンジヤツクギブソン": "ＪＥＡＮＪＡＣＫＧＩＢＳＥＮ",
    "ジヤンジヤツク": "ＪＥＡＮＪＡＣＫ", "ジヤン": "ＪＥＡＮ", "ジヤツク": "ＪＡＣＫ", "ジエミーシード": "ＪＡＭＩＥＳＥＥＤ", "ジエミー": "ＪＡＭＩＥ",
    "タムラシゲユキ": "ＴＡＭＵＲＡＳＨＩＧＥＹＵＫＩ", "タテイシカズヒロ": "ＴＡＴＥＩＳＨＩＫＡＺＵＨＩＲＯ",
    "タナハシマサアキ": "ＴＡＮＡＨＡＳＨＩＭＡＳＡＡＫＩ", "タマキン": "ＴＡＭＡＫＩＮ", "タマタマ": "ＴＡＭＡＴＡＭＡ",
    "チンコ": "ＣＨＩＮＫＯ", "チンシユウホウ": "ＣＨＩＮＳＨＵＨＯ", "チンチン": "ＣＨＩＮＣＨＩＮ", "チンポコ": "ＣＨＩＮＰＯＫＯ",
    "チンポ": "ＣＨＩＮＰＯ", "チン": "ＣＨＩＮ", "トミナガミーナ": "ＴＯＭＩＮＡＧＡＭＩＮＡ", "ナヤゴロウ": "ＮＡＹＡＧＯＲＯ",
    "ナガタアキヒコ": "ＮＡＧＡＴＡＡＫＩＨＩＫＯ", "ナポレオンボナパルト": "ＮＡＰＯＬＥＯＮＢＯＮＡＰＡＲＴＥ", "ナポレオン": "ＮＡＰＯＬＥＯＮ",
    "ハヤサカタエコ": "ＨＡＹＡＳＡＫＡＴＡＥＫＯ", "ハリーベンソン": "ＨＡＲＲＹＢＥＮＳＯＮ", "ハリー": "ＨＡＲＲＹ",
    "ハシモトカズヒサ": "ＨＡＳＨＩＭＯＴＯＫＡＺＵＨＩＳＡ", "フルカワモトアキ": "ＦＵＲＵＫＡＷＡＭＯＴＯＡＫＩ",
    "フルカワトシハル": "ＦＵＲＵＫＡＷＡＴＯＳＨＩＨＡＲＵ", "フレデイーニールセン": "ＦＲＥＤＤＹＮＩＥＬＳＥＮ", "フレデイー": "ＦＲＥＤＤＹ",
    "フレデイニールセン": "ＦＲＥＤＤＩＮＩＥＬＳＥＮ", "フレデイ": "ＦＲＥＤＤＩ", "ベンソンカニンガム": "ＢＥＮＳＯＮＣＵＮＮＩＮＧＨＡＭ",
    "ボボ": "ＢＯＢＯ", "マツイナオキ": "ＭＡＴＳＵＩＮＡＯＫＩ", "マツダヒロシ": "ＭＡＴＳＵＤＡＨＩＲＯＳＨＩ",
    "マツハナヨシカズ": "ＭＡＴＳＵＨＡＮＡＹＯＳＨＩＫＡＺＵ", "マツハナケンワ": "ＭＡＴＳＵＨＡＮＡＫＥＮＷＡ", "マツバナ": "ＭＡＴＳＵＢＡＮＡ",
    "ミカスレイトン": "ＭＩＫＡＳＬＡＹＴＯＮ", "ミカ": "ＭＩＫＡ", "ムラオカカズキ": "ＭＵＲＡＯＫＡＫＡＺＵＫＩ",
    # the videophone quiz (174, 190)
    "カクメイ": "ＲＥＶＯＬＴ", "シラナイ": "ＮＯＩＤＥＡ", "シラン": "ＤＵＮＮＯ", "ワカラン": "ＮＯＣＬＵＥ", "キネンビ": "ＭＥＭＯＲＩＡＬ",
    "ミンナデ": "ＴＯＧＥＴＨＥＲ", "メイヨ": "ＨＯＮＯＵＲ", "アメリカ": "ＡＭＥＲＩＣＡ", "フランス": "ＦＲＡＮＣＥ", "オワル": "ＥＮＤＳ",
    "オワツタ": "ＯＶＥＲ", "センソウ": "ＷＡＲ", "ゼキ": "ＨＡＣＫ", "ソウ": "ＷＥＥＤ", "ネタロウ": "ＳＬＥＥＰＥＲ", "デンカ": "ＲＥＩＮ",
    "テンカ": "ＲＥＩＧＮ",
    # BENSON (558): the answer, its misspellings, the catch-all
    "ベンソン以外": "ＢＥＮＳＯＮ以外", "ベンソン": "ＢＥＮＳＯＮ", "ベンソ": "ＢＥＮＳＯ", "ベソン": "ＢＮＳＯＮ", "バンソン": "ＢＡＮＳＯＮ",
    "ビンソン": "ＢＩＮＳＯＮ", "ブンソン": "ＢＵＮＳＯＮ", "ボンソン": "ＢＯＮＳＯＮ", "ブンセン": "ＢＵＮＳＥＮ", "ベンゼン": "ＢＥＮＺＥＮＥ",
    "ベンンン": "ＢＥＮＮＮＮ", "ベンソソ": "ＢＥＮＳＯＳＯ", "ベンンソ": "ＢＥＮＮＳＯ", "ベツソン": "ＢＥＴＳＯＮ",
    # OLEEN / QUEEN and the chess pieces (574)
    "クイーン以外": "ＱＵＥＥＮ以外", "クイーン": "ＱＵＥＥＮ", "クレーン": "ＣＲＡＮＥ", "オーエン": "ＯＷＥＮ", "オーリン": "ＯＲＬＩＮ",
    "オウリン": "ＯＬＥＥＮ", "オリーン": "ＯＬＥＡＮ", "オリイン": "ＯＬＩＥＮ", "オリーナ": "ＯＬＩＮＡ", "オリーノ": "ＯＬＩＮＯ",
    "オリーヌ": "ＯＬＩＮＥ", "オリン": "ＯＲＩＮ", "キング": "ＫＩＮＧ", "ビシヨツプ": "ＢＩＳＨＯＰ", "ナイト": "ＫＮＩＧＨＴ",
}
# a candidate that is a heading or speech, not a label
NOT_LABEL = re.compile(r"[＠'\"]|^\s|^\.|[?!…]$|\.\.\.$")


def ps1_labels(commit=None):
    """loose key of the bare Japanese -> the fullest PS1 wording (the working
    tree's ps1/translation, or a commit's)."""
    import subprocess
    cands = collections.defaultdict(collections.Counter)
    for ref in sorted(glob.glob(os.path.join(WORK, 'ref', 'ISZ_*.json'))):
        name = os.path.basename(ref)
        if commit:
            out = subprocess.run(['git', 'show', f'{commit}:ps1/translation/{name}'], capture_output=True, cwd=ROOT).stdout
            if not out:
                continue
            data = json.loads(out.decode('utf-8'))
        else:
            tr = os.path.join(ROOT, 'ps1', 'translation', name)
            if not os.path.exists(tr):
                continue
            data = json.load(open(tr, encoding='utf-8'))
        jp = {s['off']: s['jp'] for s in json.load(open(ref, encoding='utf-8'))['strings']}
        for s in data['strings']:
            if s.get('en') and s['off'] in jp and not s.get('lock'):
                k = R.loose_key(R.norm(jp[s['off']]))
                cands[k][s.get('long') or s['en']] += 1
    out = {}
    for k, c in cands.items():
        clean = [e for e in c if not NOT_LABEL.search(e)]
        if not clean:
            # only headings: strip the colour code, the quotes and the padding
            clean = [re.sub(r"＠.", "", e).strip().strip("'") for e in c]
        # the longest wording; between equals the one more banks use (店内 is
        # Joy Division's Shop in four banks and Outer Heaven's Club in one)
        best = max(clean, key=lambda e: (len(e), c.get(e, 0), e))
        if re.search(r"[^ -~]", best):
            continue                                  # a fullwidth typed target
        out[k] = best
    return out


def pce_labels():
    """Every word-list label, in module order, with the modules it is in."""
    src = P.Image(P.SRC, 12000)
    labels = collections.OrderedDict()
    for rec, n in S.records():
        if n > S.MAX_SECTORS:
            continue
        mod = S.read_file(src, rec, n)
        strings, flag = S.strings_of(mod)
        if len(strings) < 8 or flag:
            continue
        wstart, wend, wrecs = S.word_list(mod, strings[0][0])
        for jp in wrecs:
            labels.setdefault(jp, []).append(rec)
    return labels


def is_data(jp, recs):
    """A record the engine compares, not a label to read."""
    if '★' in jp or '☆' in jp or '以外' in jp:
        return True
    if re.fullmatch(r'[０-９]+', jp):
        return True
    return all(r in S.DATA_LISTS for r in recs) and re.fullmatch(r'[ァ-ヶー]+', jp) is not None


def generate(ps1, labels):
    """{label: English} as the generator makes it, and the labels with none."""
    words, missing = {}, []
    for jp, recs in labels.items():
        data = is_data(jp, recs)
        en = HAND.get(jp) or (None if data else ps1.get(R.loose_key(R.norm(jp))))
        if jp in KEYS:
            # typed in the modules with a keyboard or a typed puzzle; a menu
            # label elsewhere ("Mika" as an Ask topic), so the fullwidth
            # spelling is qualified by module: "254:ミカ"
            for rec in recs:
                if rec in TYPED and jp not in NOT_KEYS.get(rec, ()):
                    words[f"{rec}:{jp}"] = KEYS[jp]
            if all(rec in TYPED for rec in recs):
                continue
        if en:
            words[jp] = en
        elif not data:
            missing.append((recs, jp))
    return words, missing


OUT = os.path.join(ROOT, 'pce', 'translation', 'words.json')
LIST_COLS = 8                     # the list menu's highlight box (pceverify.LIST_COLS)


def refresh(commit, write):
    """words.json brought up to the PS1's labels since <commit> (see the docstring)."""
    import pcepair
    labels = pce_labels()
    old, _ = generate(ps1_labels(commit), labels)
    new, _ = generate(ps1_labels(), labels)
    cur = json.load(open(OUT, encoding='utf-8'))
    taken, hand, wide = [], [], []
    for jp, en in new.items():
        was = old.get(jp)
        if en == was or jp not in cur or cur[jp] == en:
            continue
        if cur[jp] != was:
            hand.append((jp, cur[jp], was, en))
        elif pcepair.cells(en) > LIST_COLS:
            wide.append((jp, cur[jp], en))
        else:
            taken.append((jp, cur[jp], en))
            cur[jp] = en
    print(f"{len(taken)} labels take the PS1's new wording{' (written)' if write else ''}, "
          f"{len(hand)} hand-maintained and {len(wide)} too wide listed")
    for jp, v, en in taken:
        print(f"  {jp}: {v!r} -> {en!r}")
    for jp, v, was, en in hand:
        print(f"  HAND {jp}: words.json {v!r}, generated {was!r}, PS1 now {en!r}")
    for jp, v, en in wide:
        print(f"  WIDE {jp}: words.json {v!r}, PS1 now {en!r} ({pcepair.cells(en)} cells)")
    if write:
        json.dump(dict(sorted(cur.items())), open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def main():
    if '--refresh' in sys.argv:
        refresh(sys.argv[sys.argv.index('--refresh') + 1], '--write' in sys.argv)
        return
    words, missing = generate(ps1_labels(), pce_labels())
    json.dump(dict(sorted(words.items())), open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"{len(words)} menu labels -> {OUT}")
    for recs, jp in missing:
        print(f"  no English: {jp} {recs}")


if __name__ == '__main__':
    main()
