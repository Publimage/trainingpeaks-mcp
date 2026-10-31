"""Generate and (optionally) replace CHASING athlete + 24W weekly PDF guides.

Sources: pinned athlete guide text staged from the canonical Google Doc and
live verified TrainingPeaks plan + native Strength workouts. Existing fueling
PDF, 31 native notes, 276 workouts, plan visibility and price must be retained.
"""
import asyncio,base64,hashlib,json,textwrap,unicodedata,re,copy
from datetime import date,timedelta
from pathlib import Path
import httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE

PLAN=685173; PERSON=6682479; OWNER=2116886; START=date(2027,1,4); END=date(2027,6,20)
NOTE=2664007; ROOT=Path(__file__).resolve().parents[2]
TEXT=ROOT/"data/chasing_athlete_guide_v12.txt"
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Advanced | Italiano"
OLD={97265:("CHASING THE SLOT 24W — Guida Atleta v1.1.pdf",145361),
     97222:("CHASING_THE_SLOT_24W_Guida_Settimana_per_Settimana_v1.0.pdf",222837)}
KEEP={97223:("CHASING_THE_SLOT_24W_Guida_Fueling_Nutrizione_v1.0.pdf",121278)}
NAMES=("CHASING_THE_SLOT_24W_Guida_Atleta_v1.2.pdf",
       "CHASING_THE_SLOT_24W_Guida_Settimana_per_Settimana_v1.2.pdf")
DAYS=("LUN","MAR","MER","GIO","VEN","SAB","DOM")
TYPES={1:"NUOTO",2:"BICI",3:"CORSA"}
NOTES={
  1:"Calibrazione: T1500, prova di corsa 5 km e P20 bici. Ripetere protocolli comparabili.",
  5:"Retest T1500 e P20 bici, evitando qualita supplementare non prescritta.",
  6:"Prima esposizione breve VO2 bici: 4x2 minuti, resto aerobico facile.",
  7:"VO2 bici con ripetute di 3 minuti; controllo del costo interno.",
  8:"Over-Under bici 2x9 minuti, senza forzare oltre il carico previsto.",
  9:"Settimana di scarico da 12 ore endurance. T1500 nuoto e richiamo bici soglia 2x6.",
 10:"Salita progressiva bici 3x6 il martedi e retest P20 giovedi.",
 11:"Endurance 16h30: preservare la funzione della bici facile e del continuo nuoto.",
 13:"Retest corsa 5 km; confronto solo con protocollo e condizioni assimilabili.",
 15:"Primo picco da 20 ore endurance. Continuo nuoto 3000 m al passo controllato.",
 16:"Assorbimento post-picco e micro-richiamo bici HI 6x1; priorita al recupero.",
 17:"Tre retest: 5 km lunedi, T1500 martedi, P20 bici giovedi. Forza venerdi.",
 19:"Rehearsal selettivo: nuoto 4000 m senza pause, bici sabato 6 ore + brick 20.",
 20:"Recupero di carico dopo rehearsal: 14h45 endurance, principalmente facile.",
 21:"Ultimo picco da 20 ore, prevalenza easy. Bici lunga con soli 2x40 IM Pace.",
 22:"Prima riduzione taper: 15h50, specificita familiare senza sviluppo nuovo.",
 23:"Taper: riduzione marcata volume, preservare riposo e richiami semplici.",
 24:"Settimana gara: brevi attivazioni, gara fuori dal monte ore del calendario."
}
class Stop(Exception): pass
def need(ok,msg):
 if not ok:raise Stop(msg)
def norm(s):
 s=str(s).replace("◆","[CHIAVE]").replace("↳","[BRICK]").replace("◎","[TEST]")
 for a,b in (("–","-"),("—","-"),("’","'"),("‘","'"),("“",'"'),("”",'"'),("×","x"),("→","->"),("≥",">="),("≤","<="),("₂","2"),("₁","1"),("°"," gradi")):
  s=s.replace(a,b)
 return unicodedata.normalize("NFKD",s).encode("ascii","ignore").decode("ascii").replace("\x00","")
def esc(s):
 return norm(s).replace("\\","\\\\").replace("(","\\(").replace(")","\\)")
class Sheet:
 def __init__(self,subject):
  self.subject=subject;self.pages=[];self.cmd=[];self.y=745;self.number=0
  self.new_page()
 def line(self,x,y,text,size=10,bold=False,color=(.13,.18,.24)):
  r,g,b=color
  self.cmd.append(f"{r:.3f} {g:.3f} {b:.3f} rg BT /F{2 if bold else 1} {size:.2f} Tf {x:.1f} {y:.1f} Td ({esc(text)}) Tj ET")
 def new_page(self):
  if self.cmd:self.pages.append("\n".join(self.cmd).encode("ascii"))
  self.cmd=[];self.number+=1;self.y=735
  self.cmd.append(".12 .18 .23 rg 0 790 595 52 re f")
  self.line(44,810,"CHASING THE SLOT",16,True,(1,1,1))
  self.line(44,765,self.subject,12,True)
  self.cmd.append(".18 .39 .49 RG .7 w 44 752 m 551 752 l S")
  self.line(44,32,f"CHASING THE SLOT | Piano 24 settimane | Versione 1.2 | {self.number}",8,False,(.40,.45,.48))
  self.y=731
 def assure(self,pixels=20):
  if self.y-pixels<57:self.new_page()
 def paragraph(self,text,size=9.3,leading=12,maxchars=101,after=8,color=None):
  t=norm(text).strip()
  for raw in t.split("\n"):
   chunk=textwrap.wrap(raw,maxchars,break_long_words=False,break_on_hyphens=False) or [""]
   for line in chunk:
    self.assure(leading)
    self.line(47,self.y,line,size,False,color or (.17,.21,.25));self.y-=leading
  self.y-=after
 def heading(self,txt,size=12):
  self.assure(26);self.y-=7
  self.line(45,self.y,txt,size,True,(.12,.35,.47));self.y-=22
 def page_break(self):self.new_page()
 def finish(self):
  if self.cmd:self.pages.append("\n".join(self.cmd).encode("ascii"));self.cmd=[]
  return self.pages

def pdf(pages):
 objects=[None,None,None,None]
 objects[0]=b"<< /Type /Catalog /Pages 2 0 R >>"
 kids=[]
 for i,raw in enumerate(pages):
  page_id=5+2*i;content_id=page_id+1;kids.append(f"{page_id} 0 R")
  objects.extend([f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_id} 0 R >>".encode(),
                  f"<< /Length {len(raw)} >>\nstream\n".encode()+raw+b"\nendstream"])
 objects[1]=f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode()
 objects[2]=b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
 objects[3]=b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
 out=bytearray(b"%PDF-1.4\n%IRONMAN-CHASING\n")
 offsets=[0]
 for i,obj in enumerate(objects,1):
  offsets.append(len(out));out.extend(f"{i} 0 obj\n".encode()+obj+b"\nendobj\n")
 xref=len(out)
 out.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
 for off in offsets[1:]:out.extend(f"{off:010d} 00000 n \n".encode())
 out.extend(f"trailer\n<< /Root 1 0 R /Size {len(objects)+1} >>\nstartxref\n{xref}\n%%EOF\n".encode())
 need(out.startswith(b"%PDF-") and out.endswith(b"%%EOF\n") and len(pages)>=1,"PDF_BINARY_INVALID")
 return bytes(out)

def athlete(text):
 need("RELEASE OTTOBRE 2026" in text and "W17" in text and len(text)>14000,"ATHLETE_SOURCE_STALE")
 d=Sheet("Guida Atleta - edizione aggiornata 2026")
 d.heading("Come leggere il piano aggiornato",14)
 d.paragraph("Guida operativa per allenamenti, test, zone, recupero e gestione del carico. Il calendario e il Workout Builder su TrainingPeaks prevalgono su qualsiasi esempio precedente.")
 for para in text.splitlines():
  line=para.strip()
  if not line:continue
  if re.match(r"^\d\d\s*\|",line):d.heading(line[:90],12)
  elif len(line)<70 and (line.endswith(":") or line.isupper()):d.heading(line,10.4)
  else:d.paragraph(line,size=9.1,leading=12,maxchars=100,after=6)
 pages=d.finish();need(len(pages)>=5,"ATHLETE_PAGES_MISSING")
 return pdf(pages),len(pages)

def weekly(classics,natives):
 weeks={w:[] for w in range(1,25)}
 for x in classics:
  dt=date.fromisoformat(str(x["workoutDay"])[:10]);w=(dt-START).days//7+1
  need(1<=w<=24,"CLASSIC_OUTSIDE_PLAN")
  sport=TYPES.get(x.get("workoutTypeValueId"))
  need(sport is not None,"UNKNOWN_CLASSIC_SPORT")
  weeks[w].append({"day":(dt-START).days%7,"sport":sport,"min":round((x.get("totalTimePlanned") or 0)*60),"title":x.get("title") or ""})
 for x in natives:
  dt=date.fromisoformat(str(x.get("prescribedDate"))[:10]);w=(dt-START).days//7+1
  need(1<=w<=21,"ST_OUTSIDE_RELEASE")
  m=re.search(r"Forza\s+([A-Z]\d+)",x.get("title") or "")
  minutes=int(re.search(r"\d+",m.group(1)).group()) if m else 0
  need(minutes>0,"NATIVE_STRENGTH_DURATION")
  weeks[w].append({"day":(dt-START).days%7,"sport":"FORZA","min":minutes,"title":x.get("title") or ""})
 d=Sheet("Guida Settimana per Settimana - calendario verificato")
 d.heading("Come usare le pagine settimanali",14)
 d.paragraph("Le 24 pagine successive derivano dagli allenamenti presenti su TrainingPeaks dopo le correzioni approvate. Le durate sono previste; non rappresentano obblighi da recuperare quando il corpo richiede una riduzione.")
 d.paragraph("NUOTO, BICI e CORSA contribuiscono al monte ore ENDURANCE. La FORZA viene contabilizzata separatamente. Per ripetizioni, recuperi, zone e attrezzatura seguire sempre il singolo Workout Builder nativo.")
 d.paragraph("W09 e W17 sono settimane di scarico/test. Il lungo W19 e la settimana W21 svolgono funzioni differenti. Prima della gara il volume decresce senza nuove prove massimali.")
 d.page_break()
 for week in range(1,25):
  if week>1:d.page_break()
  items=weeks[week];items.sort(key=lambda x:(x["day"],{"NUOTO":0,"BICI":1,"CORSA":2,"FORZA":3}[x["sport"]]))
  ec=sum(x["min"] for x in items if x["sport"]!="FORZA");sc=sum(x["min"] for x in items if x["sport"]=="FORZA")
  d.heading(f"SETTIMANA {week:02d}  |  Endurance {ec//60}h{ec%60:02d}  |  Forza {sc} min",12.3)
  if week in NOTES:d.paragraph(NOTES[week],size=9.8,leading=13,maxchars=93,after=13)
  last=None
  for x in items:
   day=x["day"];name=DAYS[day]
   if last is None or day!=last:
    d.assure(31);d.y-=5;d.line(48,d.y,name,10,True,(.15,.39,.48));d.y-=17
    last=day
   duration=f'{x["min"]} min' if x["sport"]=="FORZA" else f'{x["min"]} min'
   title=norm(x["title"])
   prefix=f'  {x["sport"]:<5}  {duration:<8} '
   lines=textwrap.wrap(title,73,break_long_words=False,break_on_hyphens=False) or [""]
   for k,txt in enumerate(lines[:2]):
    d.assure(14);d.line(52,d.y,(prefix if k==0 else " "*23)+txt,8.5);d.y-=13
   d.y-=1
  d.y-=13
  d.paragraph("Programmazione soggetta ad autoregolazione: se dolore, fatica o alterazioni del gesto emergono, ridurre il lavoro e non recuperare minuti mancati nelle giornate successive.",size=8.7,leading=12,maxchars=100,after=10)
 pages=d.finish()
 need(len(pages)>=25 and len(classics)==249 and len(natives)==27,"WEEKLY_SOURCE_OR_PAGE_COUNT")
 return pdf(pages),len(pages)

def nid(v):return int(v.get("id") or v.get("calendarNoteId") or v.get("noteId"))
def att(v):return {int(x["id"]):(str(x["fileName"]),int(x["contentLength"])) for x in v.get("attachments") or []}
async def run(publish=False):
 source=TEXT.read_text(encoding="utf-8")
 async with TPClient() as c:
  me=await c._get_user_data()
  need(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_COACH")
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  need(not p.is_error and p.data.get("planId")==PLAN and
       p.data.get("planPersonId")==PERSON and p.data.get("title")==TITLE and
       p.data.get("isPublic") is True and int(p.data.get("price") or 0)==199 and
       p.data.get("workoutCount")==276,"PLAN_METADATA_DRIFT")
  ranges=[("2027-01-04","2027-02-28"),("2027-03-01","2027-04-25"),("2027-04-26","2027-06-20")]
  classics=[]
  for a,b in ranges:
   r=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{a}/{b}")
   need(not r.is_error and isinstance(r.data,list),"CLASSIC_READ_FAIL")
   classics.extend(r.data)
  need(len(classics)==249 and len({w["workoutId"] for w in classics})==249,"CLASSIC_COUNT_DRIFT")
  _,token,error=await _access(c)
  need(not error and token,"NATIVE_ST_ACCESS_FAILED")
  natives=[]
  async with httpx.AsyncClient(timeout=30,follow_redirects=False) as h:
   for w in range(1,22):
    a=(START+timedelta(weeks=w-1)).isoformat()
    b=(START+timedelta(weeks=w-1,days=6)).isoformat()
    r=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/workouts/calendar/{PERSON}/{a}/{b}",headers=_headers(token))
    need(r.status_code==200 and isinstance(r.json(),list),"NATIVE_ST_READ_FAIL_"+str(w))
    natives.extend(r.json())
  need(len(natives)==27 and len({str(x.get("id")) for x in natives})==27,"NATIVE_27_DRIFT")
  guide,pg_a=athlete(source)
  weekly_pdf,pg_w=weekly(classics,natives)
  generated=[(NAMES[0],guide,pg_a),(NAMES[1],weekly_pdf,pg_w)]
  n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/2027-01-04/2027-06-20")
  need(not n.is_error and isinstance(n.data,list) and len(n.data)==31,"NATIVE_NOTES_31_DRIFT")
  note=next((x for x in n.data if nid(x)==NOTE),None)
  need(note and note.get("title")=="START | Come usare Chasing the Slot","START_NOTE_NOT_FOUND")
  existing=att(note)
  before_expected={**OLD,**KEEP}
  mid_expected=copy.deepcopy(before_expected)
  if publish:
   need(existing==before_expected,"START_PDF_BASELINE_CHANGED")
  stats=[{"name":name,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),"pages":pages} for name,data,pages in generated]
  print(json.dumps({"stage":"CHASING_GUIDES_PDF_PREVIEW_PASS","generated":stats,"classic":len(classics),"strength":len(natives),"weeks":24,"provider_writes":0}),flush=True)
  if not publish:return 0
  source_notes={nid(x):copy.deepcopy(x) for x in n.data if nid(x)!=NOTE}
  start_non_pdf={k:copy.deepcopy(v) for k,v in note.items() if k!="attachments"}
  await c._ensure_client()
  tok=await c._ensure_access_token()
  need(tok.success,"AUTH_MISSING")
  newids={}
  for filename,blob,pages in generated:
   payload={"planId":PLAN,"noteId":NOTE,"fileName":filename,"contentType":"application/pdf",
            "data":base64.b64encode(blob).decode("ascii")}
   ambiguous=False
   try:
    r=await c._client.request("POST",f"{c.base_url}/plans/v1/plans/{PLAN}/calendarNote/{NOTE}/attachments",
                            headers=c._get_headers(),json=payload,timeout=60)
    status=r.status_code
   except Exception:
    ambiguous=True;status=None
   check=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/2027-01-04/2027-06-20")
   need(not check.is_error,"MID_NOTE_READ_FAILED")
   start=next(x for x in check.data if nid(x)==NOTE)
   match=[x for x in start.get("attachments") or [] if x.get("fileName")==filename and int(x.get("contentLength") or 0)==len(blob)]
   need(len(match)==1,"AMBIGUOUS_UPLOAD_STOP_NO_RETRY_"+filename)
   newids[int(match[0]["id"])]=(filename,len(blob))
   print(json.dumps({"stage":"PDF_UPLOAD_VERIFIED","name":filename,"id":int(match[0]["id"]),"bytes":len(blob)}),flush=True)
  # Preserve old copies until BOTH new guides are independently readable.
  check=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/2027-01-04/2027-06-20")
  middle=next(x for x in check.data if nid(x)==NOTE)
  need(att(middle)=={**OLD,**KEEP,**newids},"MID_ATTACHMENTS_NOT_EXACT")
  for old_id in OLD:
   try:
    await c._request("DELETE",f"/plans/v1/plans/{PLAN}/calendarNote/{NOTE}/attachments/{old_id}",_retry_on_401=False)
   except Exception:
    pass
   check=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/2027-01-04/2027-06-20")
   need(not check.is_error,"DELETE_READBACK_FAILED")
   curr=next(x for x in check.data if nid(x)==NOTE)
   need(old_id not in att(curr) and all(i in att(curr) for i in newids),"OLD_ATTACHMENT_DELETE_UNVERIFIED_STOP")
   print(json.dumps({"stage":"OLD_GUIDE_REMOVED_VERIFIED","attachment_id":old_id}),flush=True)
  final=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/2027-01-04/2027-06-20")
  need(not final.is_error and len(final.data)==31,"FINAL_NOTE_COUNT")
  for other in final.data:
   if nid(other)!=NOTE:need(other==source_notes[nid(other)],"OTHER_NOTE_CHANGED")
  curr=next(x for x in final.data if nid(x)==NOTE)
  need(att(curr)=={**KEEP,**newids},"FINAL_ATTACHMENT_SET_WRONG")
  need({k:v for k,v in curr.items() if k!="attachments"}==start_non_pdf,"START_NOTE_BODY_DRIFT")
  meta=await c.get(f"/plans/v1/plans/{PLAN}")
  need(not meta.is_error and meta.data.get("workoutCount")==276 and
       meta.data.get("isPublic") is True and int(meta.data.get("price") or 0)==199,"FINAL_PUBLIC_METADATA_DRIFT")
  print(json.dumps({"stage":"CHASING_GUIDES_V12_RELEASE_VERIFIED","attachments":att(curr),
                    "source":{"classic":249,"native_strength":27,"notes":31},"public":True,
                    "workouts":276,"price":199,"athlete_calendar_writes":0,"library_writes":0}),flush=True)
  return 0
