"""index.html 에 버전 도장을 찍고 data/build.json 에 같은 값을 남긴다.

왜 필요한가
-----------
GitHub Pages 는 `Cache-Control: max-age=600` 으로 내려오고, 브라우저는 그보다 더
오래 index.html 을 들고 있는 경우가 많다. 그래서 데이터를 고쳐 올려도 한참 동안
옛 화면이 보인다(실제로 '151곳'이 하루 넘게 남아 있었다). 데이터 파일은 페이지가
`cache: "no-store"` 로 받으니 문제가 없고, **문제는 페이지 자신**이다.

그래서 페이지 안에 BUILD 값을 심어 두고, 페이지가 뜰 때 `data/build.json` 을
캐시 없이 받아 비교한다. 다르면 자기 자신이 낡았다는 뜻이므로 한 번 새로고침하고,
그래도 같으면(=CDN 이 아직 옛것을 준다) 띠를 띄워 사람에게 알린다.

쓰는 법
-------
index.html 을 고친 뒤, 커밋하기 전에 한 번 돌린다.

    python scripts/stamp_build.py

index.html 의 BUILD 줄과 data/build.json 이 같은 값으로 맞춰진다. 값은 BUILD 줄을
뺀 나머지 index.html 의 SHA-256 앞 12자리라, 내용이 그대로면 도장도 그대로다.
"""
import hashlib
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import krx_alignment as ka  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = ROOT / "index.html"
OUT = ROOT / "data" / "build.json"

STAMP = re.compile(r'^const BUILD = "[^"]*";$', re.M)


def main():
    text = PAGE.read_text(encoding="utf-8")
    if not STAMP.search(text):
        raise SystemExit('index.html 에 `const BUILD = "...";` 줄이 없습니다')

    # 도장 줄을 뺀 나머지로 해시를 낸다. 그래야 같은 내용에 같은 값이 나온다.
    body = STAMP.sub('const BUILD = "";', text)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]

    stamped = STAMP.sub(f'const BUILD = "{digest}";', text)
    changed_page = stamped != text
    if changed_page:
        PAGE.write_text(stamped, encoding="utf-8", newline="")
    changed_json = ka.write_if_changed(OUT, {"build": digest}, indent=1)

    where = [name for name, hit in (("index.html", changed_page),
                                    ("data/build.json", changed_json)) if hit]
    print(f"build {digest} — {', '.join(where) if where else 'already in sync'}")


if __name__ == "__main__":
    main()
