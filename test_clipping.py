import os
import argparse
import pypdfium2 as pdfium
from PIL import Image, ImageDraw
import pypdfium2.raw as pdfium_c
import ctypes

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
        # Convert UTF-16LE buffer to Python string, strip trailing nulls
        return bytearray(buf).decode('utf-16-le').rstrip('\x00')
    finally:
        pdfium_c.FPDFText_ClosePage(textpage)

def draw_text_objects(page, clip_region, output_path):
    objects = list(page.get_objects())
    scale = 2.0
    bitmap = page.render(scale=scale)
    pil_image = bitmap.to_pil()
    page_width, page_height = pil_image.size
    boxes_image = Image.new('RGB', (page_width, page_height), 'white')
    boxes_draw = ImageDraw.Draw(boxes_image)

    found = False
    for i, obj in enumerate(objects):
        if obj.type == 1:  # 1 = text object
            text = get_text_from_raw_text_obj(obj.raw, page)
            if text and text.strip() == "30075":
                found = True
                print(f"Found text '30075' in object {i+1}")
                # Get and draw object bounding box (red)
                left = ctypes.c_float()
                bottom = ctypes.c_float()
                right = ctypes.c_float()
                top = ctypes.c_float()
                success = pdfium_c.FPDFPageObj_GetBounds(obj.raw, ctypes.byref(left), ctypes.byref(bottom), ctypes.byref(right), ctypes.byref(top))
                if success:
                    print(f"Object bounding box: left={left.value}, bottom={bottom.value}, right={right.value}, top={top.value}")
                    pil_top = page_height - (top.value * scale)
                    pil_bottom = page_height - (bottom.value * scale)
                    pil_left = left.value * scale
                    pil_right = right.value * scale
                    boxes_draw.rectangle([pil_left, pil_top, pil_right, pil_bottom], outline='red', width=3)
                else:
                    print("Could not get object bounding box.")
                # Try to get and draw actual clipping path (blue)
                try:
                    clip_path = pdfium_c.FPDFPageObj_GetClipPath(obj.raw)
                    if clip_path:
                        if all(hasattr(pdfium_c, fn) for fn in [
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
                                    pil_x = x.value * scale
                                    pil_y = page_height - (y.value * scale)
                                    points.append((pil_x, pil_y))
                                    # Log the raw PDF coordinates and the PIL coordinates
                                    print(f"Object {i+1}, path {path_idx}, seg {seg_idx}: PDF ({x.value}, {y.value}) -> PIL ({pil_x}, {pil_y})")
                                # Check if path is closed
                                closed = False
                                if num_segs > 0:
                                    last_seg = pdfium_c.FPDFClipPath_GetPathSegment(clip_path, path_idx, num_segs-1)
                                    closed = bool(pdfium_c.FPDFPathSegment_GetClose(last_seg))
                                if len(points) > 1:
                                    if closed:
                                        boxes_draw.polygon(points, outline='blue')
                                    else:
                                        boxes_draw.line(points, fill='blue', width=3)
                        else:
                            print("Clipping path exists, but path segment functions are not available in this pypdfium2 version.")
                    else:
                        print("No clipping path for this object.")
                except Exception as e:
                    print(f"No clipping path or error: {e}")
    if not found:
        print("No text object with text '30075' found.")

    boxes_output_path = output_path.replace('.png', '_boxes.png')
    boxes_image.save(boxes_output_path)
    print(f"Boxes-only visualization saved to {boxes_output_path}")

def main():
    parser = argparse.ArgumentParser(description='Visualize PDF text objects with clipping')
    parser.add_argument('pdf_path', help='Path to the PDF file')
    parser.add_argument('--page', type=int, default=0, help='Page number (0-based)')
    args = parser.parse_args()
    output_dir = "test_output"
    os.makedirs(output_dir, exist_ok=True)
    doc = pdfium.PdfDocument(args.pdf_path)
    page = doc[args.page]
    output_path = os.path.join(output_dir, f"page_{args.page}.png")
    draw_text_objects(page, None, output_path)

if __name__ == '__main__':
    main()
