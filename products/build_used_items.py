"""
posts/配下の全draftファイルのfrontmatter(candidates:/products:セクション)から、
これまでに候補として採用した商品(itemCode単位)の履歴を機械的に再構築し、
products/used_items.json に保存するスクリプト。

- 新しい発見・驚き型(6-2)の候補を選ぶ前に、必ずこのファイル(または直近の
  再生成結果)を確認し、既に採用済みの商品(同一itemCode)を候補から除外する
  こと(CLAUDE.md「既出商品の重複除外ルール」参照)。
- posts/配下に新しいdraftファイルを追加した後は、このスクリプトを再実行して
  used_items.jsonを最新化すること。手動でJSONを編集するのではなく、常に
  posts/配下のfrontmatterを唯一の情報源として再構築する運用とする(手動編集は
  posts/側との不整合を生みやすいため)。
- 6-1(スレッド型、廃止済み)当時のファイルは`products:`キー、6-2(単発型)の
  ファイルは`candidates:`キーで商品リストを持つため、両方に対応する。

使い方:
  python products/build_used_items.py
"""

from __future__ import annotations

import glob
import json
import os
import re
from datetime import date

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def extract_candidates() -> list[dict]:
    results = []
    for path in sorted(glob.glob(os.path.join(PROJECT_ROOT, "posts", "*.md"))):
        with open(path, encoding="utf-8") as f:
            content = f.read()
        m = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
        if not m:
            continue
        fm = m.group(1)

        def field(name: str) -> str | None:
            mm = re.search(rf"^{name}:\s*(.+)$", fm, re.MULTILINE)
            return mm.group(1).strip() if mm else None

        genre = field("genre")
        createdAt = field("createdAt")
        status = field("status")

        rel_path = os.path.relpath(path, PROJECT_ROOT).replace("\\", "/")

        for section_key in ("candidates", "products"):
            sec_m = re.search(
                rf"^{section_key}:\n((?:  - .*\n(?:(?!  - )(?!^\w).*\n)*)+)", fm, re.MULTILINE
            )
            if not sec_m:
                continue
            sec = sec_m.group(1)
            items = re.split(r"\n(?=  - )", sec)
            for it in items:
                if not it.strip():
                    continue
                itemCode_m = re.search(r"itemCode:\s*(.+)", it)
                if not itemCode_m:
                    continue
                label_m = re.search(r"label:\s*(.+)", it)
                shop_m = re.search(r"shopName:\s*(.+)", it)
                url_m = re.search(r"productPageUrl:\s*(.+)", it)
                results.append(
                    {
                        "file": rel_path,
                        "genre": genre,
                        "createdAt": createdAt,
                        "status": status,
                        "label": label_m.group(1).strip() if label_m else None,
                        "itemCode": itemCode_m.group(1).strip(),
                        "shopName": shop_m.group(1).strip() if shop_m else None,
                        "productPageUrl": url_m.group(1).strip() if url_m else None,
                    }
                )
    return results


def build_used_items(candidates: list[dict]) -> dict:
    items: dict[str, dict] = {}
    for c in candidates:
        code = c["itemCode"]
        entry = items.setdefault(
            code,
            {
                "productPageUrl": c["productPageUrl"],
                "shopName": c["shopName"],
                "genres": [],
                "firstSeenAt": c["createdAt"],
                "occurrences": [],
            },
        )
        if c["productPageUrl"] and not entry["productPageUrl"]:
            entry["productPageUrl"] = c["productPageUrl"]
        if c["genre"] and c["genre"] not in entry["genres"]:
            entry["genres"].append(c["genre"])
        if c["createdAt"] and (not entry["firstSeenAt"] or c["createdAt"] < entry["firstSeenAt"]):
            entry["firstSeenAt"] = c["createdAt"]
        entry["occurrences"].append(
            {
                "file": c["file"],
                "genre": c["genre"],
                "createdAt": c["createdAt"],
                "status": c["status"],
                "label": c["label"],
            }
        )
    return items


def main() -> None:
    candidates = extract_candidates()
    items = build_used_items(candidates)
    dup_items = {k: v for k, v in items.items() if len(v["occurrences"]) > 1}

    payload = {
        "generatedAt": date.today().isoformat(),
        "generatedBy": "products/build_used_items.py (posts/配下の全frontmatterから機械的に再構築)",
        "note": "このファイルはposts/配下の全ファイルのcandidates:/products:セクションから機械的に"
        "再構築される。手動編集するより、新しいdraftを追加した後にこのスクリプトを再実行して"
        "再構築することを推奨する。",
        "itemCount": len(items),
        "items": items,
    }

    out_path = os.path.join(PROJECT_ROOT, "products", "used_items.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"wrote {out_path}: {len(items)} unique items, {len(dup_items)} duplicated across files")
    for code, v in dup_items.items():
        print(f"  DUP {code}: {[o['file'] for o in v['occurrences']]}")


if __name__ == "__main__":
    main()
