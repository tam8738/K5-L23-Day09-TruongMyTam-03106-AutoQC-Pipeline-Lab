"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict  # noqa: F401

import yaml  # noqa: F401

from ..common import ERROR, parse_yolo_line  # noqa: F401


DROP_LINE_CODES = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}
REMOVE_IMG_CODES = {"DUP_IMAGE_EXACT", "DUP_IMAGE_NEAR", "LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE"}


def fix(ds, issues, cfg):
    err_issues = [i for i in issues if i.severity == ERROR]
    fixes = []
    removed_images = set()
    renamed_classes = False
    needs_label_seen = set()
    line_issues_by_stem = defaultdict(lambda: defaultdict(set))

    # 1. Xử lý xoá ảnh, đổi tên lớp, thiếu file nhãn, và gom lỗi theo dòng
    for i in err_issues:
        if i.code in REMOVE_IMG_CODES:
            stem = i.image
            if stem not in removed_images:
                img_p = ds.image_path(stem)
                lbl_p = ds.label_path(stem)
                if (img_p and img_p.exists()) or lbl_p.exists():
                    before_name = img_p.name if (img_p and img_p.exists()) else f"{stem}.txt"
                    if img_p and img_p.exists():
                        img_p.unlink()
                    if lbl_p.exists():
                        lbl_p.unlink()
                    ds._size_cache.pop(stem, None)
                    fixes.append(
                        {
                            "image": stem,
                            "line": "",
                            "action": "remove_image",
                            "before": before_name,
                            "after": "(đã xoá)",
                        }
                    )
                removed_images.add(stem)
        elif i.code == "BAD_CLASS_NAME":
            if not renamed_classes:
                expected = {idx: name for idx, name in enumerate(cfg["classes"])}
                current = ds.yaml_names()
                if current != expected:
                    d = (
                        yaml.safe_load(ds.yaml_path.read_text(encoding="utf-8")) or {}
                        if ds.yaml_path.exists()
                        else {}
                    )
                    d["names"] = expected
                    ds.yaml_path.write_text(
                        yaml.safe_dump(d, allow_unicode=True, sort_keys=False),
                        encoding="utf-8",
                    )
                    fixes.append(
                        {
                            "image": "data.yaml",
                            "line": "",
                            "action": "rename_classes",
                            "before": str(current),
                            "after": str(expected),
                        }
                    )
                renamed_classes = True
        elif i.code == "MISSING_LABEL_FILE":
            stem = i.image
            if stem not in removed_images and stem not in needs_label_seen:
                if not ds.label_path(stem).exists():
                    fixes.append(
                        {
                            "image": stem,
                            "line": "",
                            "action": "needs_label",
                            "before": "(không có file)",
                            "after": "chuyển người gán",
                        }
                    )
                    needs_label_seen.add(stem)
        elif i.code in DROP_LINE_CODES or i.code == "BOX_OUT_OF_IMAGE":
            if i.line is not None:
                line_issues_by_stem[i.image][i.line].add(i.code)

    # 2. Xử lý lỗi cấp dòng theo từng file nhãn (một lần mỗi file)
    for stem in sorted(line_issues_by_stem):
        if stem in removed_images:
            continue
        lbl_p = ds.label_path(stem)
        if not lbl_p.exists():
            continue
        raw_lines = lbl_p.read_text(encoding="utf-8", errors="replace").splitlines()
        line_map = line_issues_by_stem[stem]
        new_lines = []
        changed = False

        for line_no, orig in enumerate(raw_lines, 1):
            if line_no not in line_map:
                new_lines.append(orig)
                continue

            codes = line_map[line_no]
            if codes & DROP_LINE_CODES:
                fixes.append(
                    {
                        "image": stem,
                        "line": line_no,
                        "action": "drop_line",
                        "before": orig,
                        "after": "",
                    }
                )
                changed = True
            elif "BOX_OUT_OF_IMAGE" in codes:
                try:
                    cls, cx, cy, w, h = parse_yolo_line(orig)
                except ValueError:
                    fixes.append(
                        {
                            "image": stem,
                            "line": line_no,
                            "action": "drop_line",
                            "before": orig,
                            "after": "",
                        }
                    )
                    changed = True
                    continue

                x1 = max(0.0, min(1.0, cx - w / 2))
                y1 = max(0.0, min(1.0, cy - h / 2))
                x2 = max(0.0, min(1.0, cx + w / 2))
                y2 = max(0.0, min(1.0, cy + h / 2))
                nw, nh = x2 - x1, y2 - y1
                if nw <= 0 or nh <= 0:
                    fixes.append(
                        {
                            "image": stem,
                            "line": line_no,
                            "action": "drop_line",
                            "before": orig,
                            "after": "",
                        }
                    )
                    changed = True
                else:
                    ncx, ncy = (x1 + x2) / 2, (y1 + y2) / 2
                    after_ln = f"{cls} {ncx:.6f} {ncy:.6f} {nw:.6f} {nh:.6f}"
                    new_lines.append(after_ln)
                    fixes.append(
                        {
                            "image": stem,
                            "line": line_no,
                            "action": "clip_box",
                            "before": orig,
                            "after": after_ln,
                        }
                    )
                    changed = True

        if changed:
            lbl_p.write_text(
                "\n".join(new_lines) + ("\n" if new_lines else ""),
                encoding="utf-8",
            )

    return fixes
