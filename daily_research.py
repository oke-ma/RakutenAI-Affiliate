"""
毎朝のローテーション対象ジャンル(発見・驚き型2件)について、
products/rakuten_item_search.py と同じロジックで商品リサーチを実行し、
結果を products/ 配下にJSON保存するスクリプト。

- posts/rotation_state.json(discovery_index)と
  posts/rotation_genres.json(単発ローテーション対象39ジャンルの唯一の正式な情報源)を
  読み込み、本日の対象ジャンルを判定する。
- 各ジャンルについて、キーワード「ふるさと納税」固定・--max-pages 3相当の条件で
  products/rakuten_item_search.py の関数をそのまま呼び出し、
  products/YYYY-MM-DD_商品リサーチ_<ジャンル名>.json に保存する
  (rakuten_item_search.py 単体実行時と同じファイル名規則)。
- rotation_state.json はここでは更新しない。インデックスの更新は、実際に
  投稿(draft)を生成し終えた後に行う運用(CLAUDE.md「実行のたびの更新ルール」)
  のままであり、このスクリプトの役割ではない。

認証情報は環境変数から読み込む(products/rakuten_item_search.py と同じ)。
  - RAKUTEN_APP_ID(アプリID): 必須
  - RAKUTEN_ACCESS_KEY(アクセスキー): 必須
  - RAKUTEN_AFFILIATE_ID(アフィリエイトID): 任意
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parent
ROTATION_STATE_PATH = PROJECT_ROOT / "posts" / "rotation_state.json"
ROTATION_GENRES_PATH = PROJECT_ROOT / "posts" / "rotation_genres.json"

sys.path.insert(0, str(PROJECT_ROOT / "products"))
import rakuten_item_search as ris  # noqa: E402

FIXED_KEYWORD = "ふるさと納税"
MAX_PAGES = 3
REQUEST_INTERVAL_SECONDS = 1.0


def load_rotation_state() -> dict:
    return json.loads(ROTATION_STATE_PATH.read_text(encoding="utf-8"))


def load_rotation_genres() -> dict:
    return json.loads(ROTATION_GENRES_PATH.read_text(encoding="utf-8"))


def resolve_today_genres(state: dict, genres: dict) -> list[dict]:
    discovery_list = genres["discovery"]
    discovery_index = state["discovery_index"] % len(discovery_list)

    today = []
    for offset in (0, 1):
        idx = (discovery_index + offset) % len(discovery_list)
        today.append(discovery_list[idx])

    return today


def research_genre(genre: dict, app_id: str, access_key: str, affiliate_id: str | None) -> Path:
    round_ = ris.SearchRound(
        keyword=FIXED_KEYWORD,
        genre_id=genre["genreId"],
        genre_name=genre["name"],
        label=f"{genre['name']}({genre['genreId']})",
    )
    args = SimpleNamespace(
        min_price=None,
        max_price=None,
        min_review_count=0,
        min_review_average=0.0,
        max_pages=MAX_PAGES,
        sort=ris.DEFAULT_SORT,
        output_suffix=genre["name"],
    )

    print(f"[{genre['name']}] '{round_.label}' を検索しています...")
    raw_items = ris.fetch_items_for_round(
        app_id=app_id, access_key=access_key, affiliate_id=affiliate_id, round_=round_, args=args
    )
    filtered = ris.filter_and_format_items(raw_items, args.min_review_count, args.min_review_average, round_)
    print(f"  取得 {len(raw_items)}件 → 絞り込み後 {len(filtered)}件")

    merged_items, duplicate_count = ris.merge_and_dedupe({round_.label: filtered})
    per_round_counts = {round_.label: len(filtered)}

    output_path = ris.save_results(merged_items, [round_], per_round_counts, duplicate_count, args)
    print(f"  保存しました: {output_path}")
    return output_path


def main() -> None:
    app_id, access_key, affiliate_id = ris.get_credentials()

    state = load_rotation_state()
    genres = load_rotation_genres()
    today_genres = resolve_today_genres(state, genres)

    print(f"本日の対象ジャンル(discovery_index={state['discovery_index']}): "
          f"{[g['name'] for g in today_genres]}")

    for i, genre in enumerate(today_genres):
        research_genre(genre, app_id, access_key, affiliate_id)
        if i < len(today_genres) - 1:
            time.sleep(REQUEST_INTERVAL_SECONDS)

    print("完了しました。rotation_state.json は更新していません"
          "(インデックス更新は投稿生成後の別ステップの役割です)。")


if __name__ == "__main__":
    main()
