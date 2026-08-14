"""
楽天ジャンル検索API(IchibaGenre/Search)を使って、指定したジャンルIDの
子ジャンル一覧を調べるスクリプト。

- 認証情報は環境変数から読み込む。コード中に直接書き込まない。
  - RAKUTEN_APP_ID(アプリID): 必須。APIリクエストの applicationId パラメータに使用。
- 指定したジャンルIDを起点に、子ジャンルを再帰的に辿る。
  --find で指定した文字列がジャンル名に含まれるジャンルが見つかった時点で
  そのジャンルID・ジャンル名・階層(親ジャンル名の連なり)を表示して探索を打ち切る。
  --find を指定しない場合は、起点ジャンルの直接の子ジャンル一覧のみを表示する。

使い方:
  python products/rakuten_genre_search.py --genre-id 100227 --find 惣菜
  python products/rakuten_genre_search.py --genre-id 100227
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

GENRE_API_URL = "https://app.rakuten.co.jp/services/api/IchibaGenre/Search/20140222"


def get_app_id() -> str:
    app_id = os.environ.get("RAKUTEN_APP_ID")
    if not app_id:
        print(
            "エラー: 環境変数 RAKUTEN_APP_ID が設定されていません。実行前に設定してください。",
            file=sys.stderr,
        )
        sys.exit(1)
    return app_id


def fetch_genre(genre_id: str, app_id: str) -> dict:
    params = {
        "applicationId": app_id,
        "genreId": genre_id,
        "format": "json",
    }
    url = f"{GENRE_API_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"エラー: HTTP {e.code} ({genre_id}) {e.read().decode('utf-8', 'ignore')}", file=sys.stderr)
        sys.exit(1)


def search(genre_id: str, app_id: str, find: str | None, path: list[str], depth: int, max_depth: int) -> bool:
    data = fetch_genre(genre_id, app_id)
    children = data.get("children", [])

    if not children:
        return False

    for child in children:
        info = child.get("child", {})
        cid = str(info.get("genreId"))
        cname = info.get("genreName")
        current_path = path + [f"{cname}({cid})"]

        if find and find in (cname or ""):
            print("見つかりました:")
            print(" > ".join(current_path))
            print(f"ジャンルID: {cid}")
            print(f"ジャンル名: {cname}")
            return True

        if not find:
            print(" > ".join(current_path))

    if find and depth < max_depth:
        for child in children:
            info = child.get("child", {})
            cid = str(info.get("genreId"))
            cname = info.get("genreName")
            current_path = path + [f"{cname}({cid})"]
            time.sleep(0.2)
            if search(cid, app_id, find, current_path, depth + 1, max_depth):
                return True

    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="楽天ジャンル検索API(IchibaGenre/Search)でジャンルIDを調べる")
    parser.add_argument("--genre-id", required=True, help="探索の起点にするジャンルID")
    parser.add_argument("--find", help="ジャンル名にこの文字列を含むジャンルを再帰的に探す")
    parser.add_argument("--max-depth", type=int, default=4, help="再帰探索の最大階層数(デフォルト4)")
    args = parser.parse_args()

    app_id = get_app_id()
    found = search(args.genre_id, app_id, args.find, [], 0, args.max_depth)

    if args.find and not found:
        print(f"「{args.find}」を含むジャンルは、ジャンルID {args.genre_id} 配下 深さ{args.max_depth}以内では見つかりませんでした。")


if __name__ == "__main__":
    main()
