"""
楽天市場商品検索API(IchibaItem/Search)を使った商品リサーチスクリプト。

- 認証情報は環境変数から読み込む。コード中に直接書き込まない。
  - RAKUTEN_APP_ID(アプリID): 必須。APIリクエストの applicationId パラメータに使用。
  - RAKUTEN_ACCESS_KEY(アクセスキー): 必須。APIリクエストの accessKey パラメータに使用。
    applicationId とセットで送る認証用の値で、アフィリエイトIDとは別物。
  - RAKUTEN_AFFILIATE_ID(アフィリエイトID): 任意。APIリクエストの affiliateId パラメータに使用。
    指定するとレスポンスに報酬が発生する affiliateUrl が含まれるようになるが、
    未設定でも商品リサーチ自体(認証・検索)は問題なく実行できる。
- 検索条件は次のいずれか1つを指定する(組み合わせ不可):
  - --keyword: キーワード1件で検索(--genre-id と組み合わせ可)
  - --keywords: キーワードをカンマ区切りで複数指定し、それぞれ順番に検索
  - --genre-id: 楽天ジャンルID1件で検索(--keyword と組み合わせ可)
  - --genre-ids: 楽天ジャンルIDをカンマ区切りで複数指定し、それぞれ
    keyword="ふるさと納税" 固定で順番に検索(公式ジャンル一覧を一括で
    リサーチしたい場合に使用。既知のジャンルIDは GENRE_NAME_BY_ID から
    ジャンル名を自動付与する)
  複数回検索した場合、結果は1つのJSONに統合する(itemCodeが重複する商品は
  最初に見つかったものだけを残す)。
- レビュー件数・平均評価・価格帯で絞り込んだ結果を
  products/YYYY-MM-DD_商品リサーチ.json に保存する。各商品には検索に使った
  キーワード・ジャンルID・ジャンル名(searchKeyword / searchGenreId /
  searchGenreName)を記録する。

使い方は README ではなくこのファイル冒頭コメント、および実行時の --help を参照。
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
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

SEARCH_API_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"
MAX_HITS_PER_PAGE = 30
REQUEST_INTERVAL_SECONDS = 1.0
GENRE_IDS_FIXED_KEYWORD = "ふるさと納税"

PRODUCTS_DIR = Path(__file__).resolve().parent

# 楽天ふるさと納税 公式ジャンル一覧(https://event.rakuten.co.jp/furusato/genre/ で確認)
GENRE_NAME_BY_ID: dict[str, str] = {
    "100228": "精肉・肉加工品",
    "100236": "魚介類・水産加工品",
    "110472": "米・雑穀",
    "100246": "フルーツ・果物",
    "551167": "スイーツ・お菓子",
    "200990": "野菜・きのこ",
    "100256": "麺類",
    "510915": "ビール・洋酒",
    "100316": "水・ソフトドリンク",
    "510901": "日本酒・焼酎",
    "100804": "インテリア・寝具・収納",
    "215783": "日用品雑貨・文房具・手芸",
    "558944": "キッチン用品・食器・調理器具",
    "101381": "施設利用・旅行・交通関連",
    "562637": "家電",
    "211742": "TV・オーディオ・カメラ",
    "101070": "スポーツ・アウトドア",
    "100533": "キッズ・ベビー・マタニティ",
    "566382": "おもちゃ",
    "101438": "災害支援・サービス",
    "100939": "美容・コスメ・香水",
    "100938": "ダイエット・健康",
    "551169": "医薬品・コンタクト・介護",
    "101213": "ペット・ペットグッズ",
    "100005": "花・ガーデン・DIY",
    "100371": "レディースファッション",
    "551177": "メンズファッション",
    "100433": "インナー・下着・ナイトウェア",
    "216131": "バッグ・小物・ブランド雑貨",
    "558885": "靴",
    "558929": "腕時計",
    "216129": "ジュエリー・アクセサリー",
    "200162": "本・雑誌・コミック",
    "101240": "CD・DVD",
    "101205": "テレビゲーム",
    "101164": "ホビー",
    "112493": "楽器・音響機器",
    "503190": "車用品・バイク用品",
    "100026": "パソコン・周辺機器",
    "564500": "スマートフォン・タブレット",
}


@dataclass
class SearchRound:
    keyword: str | None
    genre_id: str | None
    genre_name: str | None
    label: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="楽天市場商品検索APIで商品をリサーチし、条件で絞り込んでJSON保存する。"
    )
    parser.add_argument("--keyword", type=str, default=None, help="検索キーワード(1件のみ。例: ふるさと納税 海鮮)")
    parser.add_argument(
        "--keywords",
        type=str,
        default=None,
        help="検索キーワードをカンマ区切りで複数指定(例: 'ふるさと納税 海鮮,ふるさと納税 肉')。"
        "各キーワードを順番に検索し、結果を1つのJSONに統合する。他の検索系オプションとは同時指定不可。",
    )
    parser.add_argument("--genre-id", type=str, default=None, help="楽天ジャンルID(カテゴリ指定。--keyword と併用可)")
    parser.add_argument(
        "--genre-ids",
        type=str,
        default=None,
        help="楽天ジャンルIDをカンマ区切りで複数指定(例: '100228,100236')。各ジャンルIDに対して"
        f" keyword='{GENRE_IDS_FIXED_KEYWORD}' を固定で付与して順番に検索し、結果を1つのJSONに統合する。"
        "他の検索系オプションとは同時指定不可。",
    )
    parser.add_argument("--min-price", type=int, default=None, help="価格帯の下限(円)")
    parser.add_argument("--max-price", type=int, default=None, help="価格帯の上限(円)")
    parser.add_argument(
        "--min-review-count", type=int, default=0, help="レビュー件数の下限(デフォルト: 0 = 絞り込みなし)"
    )
    parser.add_argument(
        "--min-review-average",
        type=float,
        default=0.0,
        help="平均評価(5段階)の下限(デフォルト: 0.0 = 絞り込みなし)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=5,
        help="検索1回あたりに取得する最大ページ数(1ページ最大30件。デフォルト: 5 = 最大150件取得)",
    )
    parser.add_argument(
        "--sort",
        type=str,
        default="-reviewCount",
        choices=["standard", "+itemPrice", "-itemPrice", "+reviewCount", "-reviewCount", "+reviewAverage", "-reviewAverage"],
        help="APIから取得する際の並び順(デフォルト: レビュー件数の多い順)",
    )
    parser.add_argument(
        "--output-suffix",
        type=str,
        default=None,
        help="出力ファイル名に付与するサフィックス(例: '魚介類・水産加工品')。"
        "同日に複数回実行すると products/YYYY-MM-DD_商品リサーチ.json が上書きされるため、"
        "個別ジャンルの記事作成用に検索する際は指定することを推奨する。",
    )
    args = parser.parse_args()

    bulk_options = [args.keyword, args.keywords, args.genre_ids]
    if sum(1 for v in bulk_options if v) > 1:
        parser.error("--keyword、--keywords、--genre-ids は同時に指定できません。いずれか1つにしてください。")

    if not any(bulk_options) and not args.genre_id:
        parser.error("--keyword、--keywords、--genre-id、--genre-ids のいずれか1つは必ず指定してください。")

    return args


def resolve_search_rounds(args: argparse.Namespace) -> list[SearchRound]:
    if args.genre_ids:
        genre_ids = [g.strip() for g in args.genre_ids.split(",") if g.strip()]
        if not genre_ids:
            print("エラー: --genre-ids に有効なジャンルIDがありません。", file=sys.stderr)
            sys.exit(1)
        rounds = []
        for gid in genre_ids:
            genre_name = GENRE_NAME_BY_ID.get(gid)
            label = f"{genre_name}({gid})" if genre_name else f"genreId={gid}"
            rounds.append(SearchRound(keyword=GENRE_IDS_FIXED_KEYWORD, genre_id=gid, genre_name=genre_name, label=label))
        return rounds

    if args.keywords:
        keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
        if not keywords:
            print("エラー: --keywords に有効なキーワードがありません。", file=sys.stderr)
            sys.exit(1)
        return [SearchRound(keyword=kw, genre_id=args.genre_id, genre_name=None, label=kw) for kw in keywords]

    if args.keyword:
        return [SearchRound(keyword=args.keyword, genre_id=args.genre_id, genre_name=None, label=args.keyword)]

    # args.genre_id のみ指定されたケース
    genre_name = GENRE_NAME_BY_ID.get(args.genre_id)
    label = f"{genre_name}({args.genre_id})" if genre_name else f"genreId={args.genre_id}"
    return [SearchRound(keyword=None, genre_id=args.genre_id, genre_name=genre_name, label=label)]


def get_credentials() -> tuple[str, str, str | None]:
    app_id = os.environ.get("RAKUTEN_APP_ID")
    access_key = os.environ.get("RAKUTEN_ACCESS_KEY")
    affiliate_id = os.environ.get("RAKUTEN_AFFILIATE_ID") or None

    missing = [name for name, value in [("RAKUTEN_APP_ID", app_id), ("RAKUTEN_ACCESS_KEY", access_key)] if not value]
    if missing:
        print(
            f"エラー: 環境変数 {', '.join(missing)} が設定されていません。"
            " 実行前に設定してください(詳細はスクリプト冒頭コメントを参照)。",
            file=sys.stderr,
        )
        sys.exit(1)

    if affiliate_id is None:
        print(
            "注意: RAKUTEN_AFFILIATE_ID が未設定のため、affiliateUrl(報酬対象リンク)なしで実行します。"
        )

    assert app_id is not None and access_key is not None
    return app_id, access_key, affiliate_id


def fetch_page(
    *,
    app_id: str,
    access_key: str,
    affiliate_id: str | None,
    keyword: str | None,
    genre_id: str | None,
    min_price: int | None,
    max_price: int | None,
    sort: str,
    page: int,
) -> dict[str, Any]:
    params: dict[str, str] = {
        "applicationId": app_id,
        "accessKey": access_key,
        "format": "json",
        "hits": str(MAX_HITS_PER_PAGE),
        "page": str(page),
        "sort": sort,
    }
    if affiliate_id:
        params["affiliateId"] = affiliate_id
    if keyword:
        params["keyword"] = keyword
    if genre_id:
        params["genreId"] = genre_id
    if min_price is not None:
        params["minPrice"] = str(min_price)
    if max_price is not None:
        params["maxPrice"] = str(max_price)

    url = f"{SEARCH_API_URL}?{urllib.parse.urlencode(params)}"

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print(f"エラー: 楽天APIへのリクエストが失敗しました(HTTP {e.code})。\n{error_body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"エラー: 楽天APIに接続できませんでした。{e.reason}", file=sys.stderr)
        sys.exit(1)

    data: dict[str, Any] = json.loads(body)

    if "error" in data:
        print(
            f"エラー: 楽天APIがエラーを返しました。{data.get('error')}: {data.get('error_description')}",
            file=sys.stderr,
        )
        sys.exit(1)

    return data


def fetch_items_for_round(
    *,
    app_id: str,
    access_key: str,
    affiliate_id: str | None,
    round_: SearchRound,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    all_items: list[dict[str, Any]] = []

    for page in range(1, args.max_pages + 1):
        data = fetch_page(
            app_id=app_id,
            access_key=access_key,
            affiliate_id=affiliate_id,
            keyword=round_.keyword,
            genre_id=round_.genre_id,
            min_price=args.min_price,
            max_price=args.max_price,
            sort=args.sort,
            page=page,
        )

        items = [entry["Item"] for entry in data.get("Items", [])]
        all_items.extend(items)

        page_count = data.get("pageCount", page)
        print(f"    ページ {page}/{page_count} を取得({len(items)}件)")

        if page >= page_count:
            break

        time.sleep(REQUEST_INTERVAL_SECONDS)

    return all_items


def filter_and_format_items(
    items: list[dict[str, Any]], min_review_count: int, min_review_average: float, round_: SearchRound
) -> list[dict[str, Any]]:
    result = []
    for item in items:
        review_count = int(item.get("reviewCount", 0))
        review_average = float(item.get("reviewAverage", 0.0))

        if review_count < min_review_count:
            continue
        if review_average < min_review_average:
            continue

        result.append(
            {
                "itemName": item.get("itemName"),
                "itemPrice": item.get("itemPrice"),
                "itemUrl": item.get("affiliateUrl") or item.get("itemUrl"),
                "shopName": item.get("shopName"),
                "reviewCount": review_count,
                "reviewAverage": review_average,
                "genreId": item.get("genreId"),
                "itemCode": item.get("itemCode"),
                "imageUrl": (item.get("mediumImageUrls") or [{}])[0].get("imageUrl"),
                "searchLabel": round_.label,
                "searchKeyword": round_.keyword,
                "searchGenreId": round_.genre_id,
                "searchGenreName": round_.genre_name,
            }
        )

    return result


def merge_and_dedupe(items_by_round: dict[str, list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], int]:
    merged: list[dict[str, Any]] = []
    seen_item_codes: set[str] = set()
    duplicate_count = 0

    for items in items_by_round.values():
        for item in items:
            item_code = item.get("itemCode")
            if item_code in seen_item_codes:
                duplicate_count += 1
                continue
            seen_item_codes.add(item_code)
            merged.append(item)

    return merged, duplicate_count


def save_results(
    all_items: list[dict[str, Any]],
    search_rounds: list[SearchRound],
    per_round_counts: dict[str, int],
    duplicate_count: int,
    args: argparse.Namespace,
) -> Path:
    PRODUCTS_DIR.mkdir(exist_ok=True)
    filename = f"{date.today().isoformat()}_商品リサーチ"
    if args.output_suffix:
        filename += f"_{args.output_suffix}"
    output_path = PRODUCTS_DIR / f"{filename}.json"

    payload = {
        "searchedAt": date.today().isoformat(),
        "conditions": {
            "searchRounds": [
                {"label": r.label, "keyword": r.keyword, "genreId": r.genre_id, "genreName": r.genre_name}
                for r in search_rounds
            ],
            "minPrice": args.min_price,
            "maxPrice": args.max_price,
            "minReviewCount": args.min_review_count,
            "minReviewAverage": args.min_review_average,
            "maxPagesPerRound": args.max_pages,
        },
        "perRoundCount": per_round_counts,
        "duplicateItemsRemoved": duplicate_count,
        "resultCount": len(all_items),
        "items": all_items,
    }

    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def main() -> None:
    args = parse_args()
    app_id, access_key, affiliate_id = get_credentials()
    search_rounds = resolve_search_rounds(args)

    items_by_round: dict[str, list[dict[str, Any]]] = {}

    for i, round_ in enumerate(search_rounds, start=1):
        print(f"[{i}/{len(search_rounds)}] '{round_.label}' を検索しています...")

        raw_items = fetch_items_for_round(
            app_id=app_id, access_key=access_key, affiliate_id=affiliate_id, round_=round_, args=args
        )
        filtered = filter_and_format_items(raw_items, args.min_review_count, args.min_review_average, round_)
        print(f"  取得 {len(raw_items)}件 → 絞り込み後 {len(filtered)}件")

        items_by_round[round_.label] = filtered

        if i < len(search_rounds):
            time.sleep(REQUEST_INTERVAL_SECONDS)

    merged_items, duplicate_count = merge_and_dedupe(items_by_round)
    per_round_counts = {label: len(items) for label, items in items_by_round.items()}

    print(f"合計 {len(merged_items)}件(重複除去 {duplicate_count}件)")

    output_path = save_results(merged_items, search_rounds, per_round_counts, duplicate_count, args)
    print(f"保存しました: {output_path}")


if __name__ == "__main__":
    main()
