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

def boxes_intersect(box1, box2):
    """Check if two boxes intersect using the algorithm from fz_glyph_entirely_outside_box.
    
    Args:
        box1, box2: Tuples of (x0, y0, x1, y1) where (x0,y0) is bottom-left, (x1,y1) is top-right
    
    Returns:
        True if boxes intersect, False if they are entirely separate
    """
    # If box1 is entirely outside box2, they don't intersect
    if (box1[2] <= box2[0] or  # box1.x1 <= box2.x0 (box1 right edge <= box2 left edge)
        box1[3] <= box2[1] or  # box1.y1 <= box2.y0 (box1 top edge <= box2 bottom edge)  
        box1[0] >= box2[2] or  # box1.x0 >= box2.x1 (box1 left edge >= box2 right edge)
        box1[1] >= box2[3]):   # box1.y0 >= box2.y1 (box1 bottom edge >= box2 top edge)
        return False
    return True

def draw_box(box, boxes_draw, scale, page_height, color='gray', width=1):
    """Draw a bounding box on the image.
    
    Args:
        box: Tuple of (x0, y0, x1, y1) coordinates in PDF space
        boxes_draw: ImageDraw object to draw on
        scale: Scale factor for coordinate conversion
        page_height: Height of the page in pixels
        color: Color of the outline
        width: Width of the outline
    """
    pil_top = page_height - (box[3] * scale)
    pil_bottom = page_height - (box[1] * scale)
    pil_left = box[0] * scale
    pil_right = box[2] * scale
    boxes_draw.rectangle([pil_left, pil_top, pil_right, pil_bottom], outline=color, width=width)

def draw_matching_boxes(page, output_path):
    objects = list(page.get_objects())
    scale = 2.0
    bitmap = page.render(scale=scale)
    pil_image = bitmap.to_pil()
    page_width, page_height = pil_image.size
    boxes_draw = ImageDraw.Draw(pil_image)

    # Check for required clip path functions once
    required_clip_fns = [
        "FPDFClipPath_CountPaths", "FPDFClipPath_CountPathSegments",
        "FPDFClipPath_GetPathSegment", "FPDFPathSegment_GetPoint",
        "FPDFPathSegment_GetType", "FPDFPathSegment_GetClose"
    ]
    has_clip_path_api = all(hasattr(pdfium_c, fn) for fn in required_clip_fns)
    if not has_clip_path_api:
        raise RuntimeError("Required PDFium clip path API functions are missing in pdfium_c. Please check your PDFium installation.")

    # Draw the page crop box in green
    try:
        left = ctypes.c_float()
        bottom = ctypes.c_float()
        right = ctypes.c_float()
        top = ctypes.c_float()
        success = pdfium_c.FPDFPage_GetCropBox(page.raw, ctypes.byref(left), ctypes.byref(bottom), ctypes.byref(right), ctypes.byref(top))
        if success:
            crop_box = (left.value, bottom.value, right.value, top.value)
            print(f"Page crop box: ({crop_box[0]:.2f}, {crop_box[1]:.2f}, {crop_box[2]:.2f}, {crop_box[3]:.2f})")
            draw_box(crop_box, boxes_draw, scale, page_height, color='green', width=2)
        else:
            print("Could not get page crop box")
    except Exception as e:
        print(f"Error getting page crop box: {e}")

    # Initialize counters for statistics
    total_objects = len(objects)
    text_objects = 0
    visible_objects = 0
    clipped_objects = 0

    # Load textpage once for efficiency
    textpage = pdfium_c.FPDFText_LoadPage(page.raw)
    if not textpage:
        print("Warning: Could not load textpage for text checking")

    for i, obj in enumerate(objects):
        # Check if object is a text object and has text content
        obj_type = pdfium_c.FPDFPageObj_GetType(obj.raw)
        if obj_type != 1:  # FPDF_PAGEOBJ_TEXT = 1
            continue
        
        # Check if text object has any text content (without extracting it)
        if textpage:
            buflen = pdfium_c.FPDFTextObj_GetText(obj.raw, textpage, None, 0)
            if buflen <= 0:  # No text content
                continue
        
        text_objects += 1
        
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
        #print(f"Object {i+1}: Bounding box: ({obj_box[0]:.2f}, {obj_box[1]:.2f}, {obj_box[2]:.2f}, {obj_box[3]:.2f})")
        # Try to get clipping path
        show_box = True
        try:
            clip_path = pdfium_c.FPDFPageObj_GetClipPath(obj.raw)
            if clip_path:
                # Collect all points from all paths to calculate a bounding rectangle
                all_points = []
                num_paths = pdfium_c.FPDFClipPath_CountPaths(clip_path)
                for path_idx in range(num_paths):
                    num_segs = pdfium_c.FPDFClipPath_CountPathSegments(clip_path, path_idx)
                    for seg_idx in range(num_segs):
                        seg = pdfium_c.FPDFClipPath_GetPathSegment(clip_path, path_idx, seg_idx)
                        x = ctypes.c_float()
                        y = ctypes.c_float()
                        pdfium_c.FPDFPathSegment_GetPoint(seg, ctypes.byref(x), ctypes.byref(y))
                        all_points.append((x.value, y.value))
                
                if all_points:
                    # Calculate the minimal bounding rectangle that fits the clip path
                    xs = [pt[0] for pt in all_points]
                    ys = [pt[1] for pt in all_points]
                    clip_box = (min(xs), min(ys), max(xs), max(ys))
                    #print(f"Object {i+1}: Clip path bounding box: ({clip_box[0]:.2f}, {clip_box[1]:.2f}, {clip_box[2]:.2f}, {clip_box[3]:.2f}), # of paths: {num_paths}, # of segments: {num_segs}")
                    
                    
                    # Only show the object's bounding box if it doesn't match the clip box
                    if not boxes_intersect(obj_box, clip_box):
                        show_box = False
                        clipped_objects += 1
                    else:
                        # Draw the clip path bounding box in blue
                        draw_box(clip_box, boxes_draw, scale, page_height, color='blue')
                        
                        # If boxes intersect, draw in red and extract text
                        draw_box(obj_box, boxes_draw, scale, page_height, color='red', width=3)
                        show_box = True
                        visible_objects += 1
                        
                        # Extract and print text for red boxes
                        if textpage:
                            buflen = pdfium_c.FPDFTextObj_GetText(obj.raw, textpage, None, 0)
                            if buflen > 0:
                                buf = (ctypes.c_ushort * buflen)()
                                pdfium_c.FPDFTextObj_GetText(obj.raw, textpage, buf, buflen)
                                byte_buf = bytearray(buf)
                                text_content = byte_buf.decode('utf-16-le').rstrip('\x00')
                                utf16_bytes = text_content.encode('utf-16-le')
                                hex_bytes = ' '.join(f'{b:02x}' for b in utf16_bytes)
                                print(f"Object {i+1} text (red box): '{text_content}', utf16 bytes: {hex_bytes}")
            else:
                print(f"Object {i+1}: No clipping path.")
        except Exception as e:
            print(f"Object {i+1}: Error getting clip path: {e}")
        if show_box:
            draw_box(obj_box, boxes_draw, scale, page_height)
            visible_objects += 1

    pil_image.save(output_path)
    print(f"Matching boxes visualization saved to {output_path}")
    
    # Close textpage to avoid memory leaks
    if textpage:
        pdfium_c.FPDFText_ClosePage(textpage)
    
    # Print statistics
    print(f"\nStatistics:")
    print(f"Total objects: {total_objects}")
    print(f"Text objects: {text_objects}")
    print(f"Visible objects: {visible_objects}")
    print(f"Clipped objects: {clipped_objects}")

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