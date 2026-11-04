import tkinter as tk
import unittest
import pymupdf
from zynq_bjt.pdf_view import PdfPane


class PdfViewTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.geometry('900x650')
        self.seen=[];self.pane=PdfPane(self.root,self.seen.append);self.pane.pack(fill='both',expand=True)
        self.root.update()
        self.doc=pymupdf.open()
        for i in range(12):
            p=self.doc.new_page(width=400 if i%2 else 600,height=800)
            p.insert_text((30,40),'PAGE '+str(i+1))
        self.pane.set_document(self.doc);self.root.update()

    def tearDown(self):
        self.pane.clear();self.doc.close();self.root.destroy()

    def test_all_pages_share_scroll_region_and_visible_cache_is_bounded(self):
        p=self.pane;self.assertEqual(len(p.pages),12)
        self.assertGreater(p.total_height,10*p.canvas.winfo_height())
        self.assertLess(len(p.photos),4)
        p.canvas.yview_moveto((p.pages[4]['y']+50)/p.total_height);self.root.update()
        self.assertEqual(self.seen[-1],4);self.assertIn(4,p.photos);self.assertNotIn(0,p.photos)
        p.goto_page(8);self.root.update();self.assertEqual(self.seen[-1],8)

    def test_fit_width_centers_mixed_pages_and_resize_preserves_reading_position(self):
        p=self.pane
        self.assertAlmostEqual(p.pages[0]['width'],p.canvas.winfo_width()-24,delta=1)
        for page in p.pages:self.assertAlmostEqual(page['x']+page['width']/2,p.content_width/2)
        p.goto_page(3);self.root.update();old=p.pages[0]['width']
        self.root.geometry('1100x650');self.root.update();p.layout();self.root.update()
        self.assertGreater(p.pages[0]['width'],old);self.assertEqual(self.seen[-1],3)
        p.zoom=1.5;p.layout();self.root.update();self.assertGreater(p.content_width,p.canvas.winfo_width())
        p.fit_width();self.root.update();self.assertEqual(p.zoom,1)
        self.assertAlmostEqual(p.pages[0]['width'],p.canvas.winfo_width()-24,delta=1)
