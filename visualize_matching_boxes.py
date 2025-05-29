import argparse
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
import ctypes
from PIL import Image, ImageDraw

def get_text_from_raw_text_obj(raw_text_obj, page):
    textpage = pdfium_c.FPDFText_LoadPage(page.raw)
    if not textpage:
        return ""
    try:
        buflen = pdfium_c.FPDFTextObj_GetText(raw_text_obj, textpage, None, 0)
        if buflen <= 0:
            return ""
        buf = (ctypes.c_ushort * buflen)()
        pdfium_c.FPDFTextObj_GetText(raw_text_obj, textpage, buf, buflen)
        return bytearray(buf).decode('utf-16-le').rstrip('\x00')
    finally:
        pdfium_c.FPDFText_ClosePage(textpage)

def boxes_are_equal(box1, box2, tol=1e-2):
    return all(abs(a - b) < tol for a, b in zip(box1, box2))

def draw_matching_boxes(page, output_path):
    objects = list(page.get_objects())
    scale = 2.0
    bitmap = page.render(scale=scale)
    pil_image = bitmap.to_pil()
    page_width, page_height = pil_image.size
    boxes_draw = ImageDraw.Draw(pil_image)

    for i, obj in enumerate(objects):
        # Get object bounding box
        left = ctypes.c_float()
        bottom = ctypes.c_float()
        right = ctypes.c_float()
        top = ctypes.c_float()
        success = pdfium_c.FPDFPageObj_GetBounds(obj.raw, ctypes.byref(left), ctypes.byref(bottom), ctypes.byref(right), ctypes.byref(top))
        if not success:
            print(f"Object {i+1}: Could not get object bounding box.")
            continue
        obj_box = (left.value, bottom.value, right.value, top.value)
        print(f"Object {i+1}: Bounding box: {obj_box}")
        # Try to get clipping path
        show_box = True
        try:
            clip_path = pdfium_c.FPDFPageObj_GetClipPath(obj.raw)
            if clip_path and all(hasattr(pdfium_c, fn) for fn in [
                "FPDFClipPath_CountPaths", "FPDFClipPath_CountPathSegments", "FPDFClipPath_GetPathSegment", "FPDFPathSegment_GetPoint", "FPDFPathSegment_GetType", "FPDFPathSegment_GetClose"]):
                num_paths = pdfium_c.FPDFClipPath_CountPaths(clip_path)
                for path_idx in range(num_paths):
                    num_segs = pdfium_c.FPDFClipPath_CountPathSegments(clip_path, path_idx)
                    points = []
                    for seg_idx in range(num_segs):
                        seg = pdfium_c.FPDFClipPath_GetPathSegment(clip_path, path_idx, seg_idx)
                        x = ctypes.c_float()
                        y = ctypes.c_float()
                        pdfium_c.FPDFPathSegment_GetPoint(seg, ctypes.byref(x), ctypes.byref(y))
                        points.append((x.value, y.value))
                    if len(points) >= 2:
                        # Get the bounding box of the clip path
                        xs = [pt[0] for pt in points]
                        ys = [pt[1] for pt in points]
                        clip_box = (min(xs), min(ys), max(xs), max(ys))
                        print(f"Object {i+1}: Clip path box: {clip_box}")
                        # Draw the clip path in blue
                        pil_points = [(x * scale, page_height - (y * scale)) for x, y in points]
                        closed = False
                        if num_segs > 0:
                            last_seg = pdfium_c.FPDFClipPath_GetPathSegment(clip_path, path_idx, num_segs-1)
                            closed = bool(pdfium_c.FPDFPathSegment_GetClose(last_seg))
                        if closed:
                            boxes_draw.polygon(pil_points, outline='blue')
                        else:
                            boxes_draw.line(pil_points, fill='blue', width=3)
                        # Only show the bounding box if it matches the clip box
                        if not boxes_are_equal(obj_box, clip_box):
                            show_box = False
            else:
                print(f"Object {i+1}: No usable clipping path.")
        except Exception as e:
            print(f"Object {i+1}: Error getting clip path: {e}")
        if show_box:
            pil_top = page_height - (obj_box[3] * scale)
            pil_bottom = page_height - (obj_box[1] * scale)
            pil_left = obj_box[0] * scale
            pil_right = obj_box[2] * scale
            boxes_draw.rectangle([pil_left, pil_top, pil_right, pil_bottom], outline='red', width=3)

    pil_image.save(output_path)
    print(f"Matching boxes visualization saved to {output_path}")

def main():
    parser = argparse.ArgumentParser(description='Visualize matching bounding boxes and clip paths for all objects')
    parser.add_argument('pdf_path', help='Path to the PDF file')
    parser.add_argument('--page', type=int, default=0, help='Page number (0-based)')
    parser.add_argument('--output', type=str, default='matching_boxes.png', help='Output image path')
    args = parser.parse_args()
    doc = pdfium.PdfDocument(args.pdf_path)
    page = doc[args.page]
    draw_matching_boxes(page, args.output)

if __name__ == '__main__':
    main() 