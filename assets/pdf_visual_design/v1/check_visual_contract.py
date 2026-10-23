"""Structural visual QA against the approved Intermediate 18-page PDF.

Usage: python check_visual_contract.py APPROVED_INTERMEDIATE.pdf CANDIDATE.pdf LOGO_MASTER.png
Requires PyMuPDF (fitz). A passing test certifies only cover geometry,
RPE and page structure; all-page render comparison still needs approval.
"""
import sys, hashlib
import fitz

GOLDEN="7759224d295123bfdab5203dd82dfc7822228b0a3e60885a6b1003a1b4d7c938"
LOGO="ad2710edac3834c467331d2497716c45f8e4cdaf37eaeb658203d531ea9ceea6"
def sha(path):
    return hashlib.sha256(open(path,"rb").read()).hexdigest()
def norm(rect):
    return tuple(rect)
def near(a,b,tol):
    return all(abs(x-y)<=tol for x,y in zip(a,b))
def circles(page):
    a=[]
    for o in page.get_drawings():
        r=o["rect"]
        if o.get("fill") is not None and 26<=r.width<=36 and 26<=r.height<=36 and 105<=r.y0<=230:
            a.append((r,o["fill"]))
    return sorted(a,key=lambda e:e[0].x0)
def band(page):
    a=[d["rect"] for d in page.get_drawings() if d.get("fill") is not None and d["rect"].width>500 and d["rect"].height>75]
    assert len(a)==1,"cover_band_count"
    return a[0]
def inspect(reference,candidate,master):
    assert sha(reference)==GOLDEN, "wrong_reference_pdf"
    assert sha(master)==LOGO, "altered_master_logo"
    original=fitz.open(reference);new=fitz.open(candidate)
    assert len(new)==18,"guide_page_count"
    assert all(abs(p.rect.width-595.28)<2 and abs(p.rect.height-841.89)<2 for p in new),"not_A4"
    a=original[0].get_image_rects(original[0].get_images(full=True)[0][0])[0]
    b=new[0].get_image_rects(new[0].get_images(full=True)[0][0])[0]
    assert near(norm(a),norm(b),.7),"logo_position_or_size_mismatch"
    assert near(norm(band(original[0])),norm(band(new[0])),.8),"cover_band_geometry_mismatch"
    v=circles(original[4]);w=circles(new[4])
    assert len(v)==len(w)==10,"rpe_count_mismatch"
    for i,((r1,c1),(r2,c2)) in enumerate(zip(v,w)):
        assert abs(r1.x0-r2.x0)<.75 and abs(r1.width-r2.width)<.75 and abs(r1.height-r2.height)<.75, "rpe_geometry_"+str(i+1)
        assert abs(r1.y0-r2.y0)<4,"rpe_position_"+str(i+1)
        assert all(abs(x-y)<.013 for x,y in zip(c1,c2)),"rpe_color_"+str(i+1)
    labels=[]
    for block in new[4].get_text("dict")["blocks"]:
        for line in block.get("lines",[]):
            for item in line["spans"]:
                if item["text"].strip() in [str(i) for i in range(1,11)] and 125<item["bbox"][1]<230:labels.append(item)
    assert len(labels)==10 and sorted(int(x["text"]) for x in labels)==list(range(1,11)),"rpe_duplicate_labels"
    for item in labels:
        idx=int(item["text"])-1
        center=(item["bbox"][0]+item["bbox"][2])/2
        assert abs(center-(w[idx][0].x0+w[idx][0].x1)/2)<1.35,"rpe_number_not_centered"
    for pg,heading in ((3,"Workout, note e simboli"),(4,"RPE: la scala da 1 a 10"),(16,"Come evolve il programma")):
        assert heading in new[pg].get_text(),f"section_{pg+1}_missing"
    print("PASS: A4/18p, cover master geometry, brand SHA, 10 RPE circles/labels. FULL-PAGE QA STILL REQUIRED.")
if __name__=="__main__":
    if len(sys.argv)!=4:raise SystemExit("usage: check_visual_contract.py reference.pdf candidate.pdf logo.png")
    inspect(*sys.argv[1:])
